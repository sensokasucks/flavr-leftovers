"""
Kick sign-in for Stream Core ("Connect Kick" on the Kick card in Settings).

Kick has no sign-in that works without a secret (no device code, no public app type), and
Stream Core's code is public, so Core cannot ship one Kick app for everybody the way it does
for Twitch (adapters/twitch_auth.py). Each streamer registers their **own** Kick app at
kick.com/settings/developer and pastes its Client ID and Client Secret into Settings → Kick
(``kick.client_id`` / ``kick.client_secret`` in config.yaml). docs/KICK_APP_SETUP.md walks
through it step by step.

Signing in is Kick's OAuth 2.1 code flow with PKCE:

1. **Connect Kick** (POST /api/admin/kick/auth/start) makes a random ``state`` and PKCE
   verifier and gives the dashboard the id.kick.com address to open in a new tab.
2. The streamer presses Allow at Kick, and Kick sends the browser back to
   ``http://localhost:<core.port>/kick/callback`` (``redirect_uri()``; it must match the
   Redirect URL in the Kick app exactly). api/server.py hands the code to ``finish_login``.
3. Core swaps the code for tokens at id.kick.com (with the secret and the verifier) and asks
   api.kick.com who signed in.

The tokens live in ``data/kick_token.json`` (runtime state, git-ignored) and are never sent
anywhere but Kick. Core refreshes the access token before it expires (Kick gives new access
*and* refresh tokens each time). **Disconnect** revokes the token at Kick and deletes the file.

Reading Kick chat does not need any of this: adapters/kick.py reads it over Kick's public
Pusher socket. The sign-in is for posting into Kick chat (``send_chat``, used by
``KickAdapter.send_message`` and the card's **Send test message**).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlencode

log = logging.getLogger("adapters.kick_auth")

# What the sign-in asks for: who signed in (to know which channel to post in) and posting
# into chat. Kick shows these on its Allow page. Add a scope here only together with the
# feature that needs it; a streamer signed in before then is told to press Reconnect
# (status()["missing_scopes"]).
SCOPES = ["user:read", "chat:write"]

ID_BASE = "https://id.kick.com/oauth"
AUTHORIZE_URL = f"{ID_BASE}/authorize"
TOKEN_URL = f"{ID_BASE}/token"
REVOKE_URL = f"{ID_BASE}/revoke"
API_BASE = "https://api.kick.com/public/v1"
USERS_URL = f"{API_BASE}/users"
CHAT_URL = f"{API_BASE}/chat"

# Path of the page Kick sends the browser back to; api/server.py serves it. The Redirect URL
# in the streamer's Kick app must be exactly redirect_uri(port), so keep the two in step
# (and docs/KICK_APP_SETUP.md, which tells them what to paste).
CALLBACK_PATH = "/kick/callback"

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "kick_token.json"
REFRESH_MARGIN_SEC = 5 * 60        # refresh when this close to expiry
LOGIN_TIMEOUT_SEC = 10 * 60        # a Connect Kick press is good for this long
CHAT_MAX_CHARS = 500               # Kick refuses longer chat messages


class Http:
    """How KickAuth talks to Kick. Tests pass a fake with the same ``request`` signature.

    ``request`` returns (status, json body or {}); a body that isn't JSON comes back as {}.
    ``form`` is sent form-encoded (id.kick.com wants that), ``json`` as a JSON body
    (api.kick.com wants that).
    """

    async def request(self, method: str, url: str, *, form: Optional[dict] = None,
                      json_body: Optional[dict] = None, params: Optional[dict] = None,
                      headers: Optional[dict] = None) -> tuple[int, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.request(method, url, data=form, json=json_body, params=params, headers=headers)
            try:
                body = r.json()
            except ValueError:
                body = {}
            return r.status_code, body


def redirect_uri(port: int | str = 3850) -> str:
    """The Redirect URL to paste into the Kick app: ``http://localhost:<core.port>/kick/callback``.

    ``localhost``, not 127.0.0.1: Kick's sign-in page rewrites 127.0.0.1 to localhost, and then
    the address no longer matches the app's setting (Kick's docs say so too).
    """
    return f"http://localhost:{int(port or 3850)}{CALLBACK_PATH}"


def _pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge) for one sign-in, as RFC 7636 describes."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _seconds(raw: Any, default: float) -> float:
    """Kick's ``expires_in`` (a number, sometimes sent as a string) in seconds."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _scope_list(raw: Any) -> list[str]:
    """Kick's ``scope`` answer ("user:read chat:write") as a list."""
    if isinstance(raw, list):
        return [str(s) for s in raw]
    return [s for s in str(raw or "").split() if s]


def _kick_message(body: Any) -> str:
    """The human-readable reason in a Kick error answer ("" if none)."""
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error_description") or body.get("error") or "")
    return ""


class KickAuth:
    """One per Core. The Kick adapter, the dashboard and the callback page share it (``get_auth``).

    ``http`` and ``clock`` can be swapped in tests so no request goes to Kick.
    Times stored here (``expires_at``) are ``clock()`` seconds.
    """

    def __init__(self, client_id: str = "", client_secret: str = "", port: int | str = 3850,
                 path: Optional[Path] = None, http: Optional[Http] = None,
                 clock: Callable[[], float] = time.time):
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._port = port
        self._path = path or DATA_PATH
        self._http = http or Http()
        self._now = clock
        self._tok: dict[str, Any] = {}      # access_token, refresh_token, expires_at, login, user_id, scopes, client_id
        self._pending: dict[str, Any] = {}  # state, verifier, redirect_uri, expires_at, authorize_url
        self._lock = asyncio.Lock()
        self._last_error = ""
        self._load()

    # ── configuration ───────────────────────────────────────
    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def has_app(self) -> bool:
        """True once both the Client ID and the Client Secret of the streamer's Kick app are set."""
        return bool(self._client_id and self._client_secret)

    @property
    def redirect_uri(self) -> str:
        return redirect_uri(self._port)

    def configure(self, client_id: str = "", client_secret: str = "", port: int | str = 3850) -> None:
        """Apply config.yaml's kick.client_id / client_secret and core.port. A token from another app is dropped."""
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._port = port
        if self._tok and self._tok.get("client_id") != self._client_id:
            log.info("Kick app changed; the stored sign-in belonged to the old app and was dropped")
            self._tok = {}
            self._save()

    # ── status (never includes tokens) ──────────────────────
    @property
    def connected(self) -> bool:
        return bool(self._tok.get("access_token"))

    @property
    def login(self) -> str:
        return str(self._tok.get("login") or "")

    @property
    def user_id(self) -> str:
        return str(self._tok.get("user_id") or "")

    def status(self) -> dict[str, Any]:
        """What the dashboard's Kick card shows (GET /api/admin/kick/auth). Never contains tokens or the secret."""
        pending = None
        if self._pending and self._pending.get("expires_at", 0) > self._now():
            pending = {"authorize_url": self._pending.get("authorize_url", ""),
                       "expires_in": int(self._pending["expires_at"] - self._now())}
        return {
            "connected": self.connected,
            "login": self.login,
            "user_id": self.user_id,
            "scopes": list(self._tok.get("scopes") or []),
            "expires_in": int(max(0.0, float(self._tok.get("expires_at", 0)) - self._now())) if self.connected else 0,
            "has_app": self.has_app,
            "has_client_id": bool(self._client_id),
            "has_secret": bool(self._client_secret),
            "redirect_uri": self.redirect_uri,
            "pending": pending,
            "error": self._last_error,
            # signed in before Core asked for these: press Reconnect once to allow them
            "missing_scopes": [s for s in SCOPES if s not in (self._tok.get("scopes") or [])]
            if self.connected else [],
        }

    # ── sign-in ─────────────────────────────────────────────
    def start_login(self) -> dict[str, Any]:
        """Make a fresh state + PKCE pair. Returns ``status()`` with ``pending.authorize_url`` to open."""
        self._pending = {}
        self._last_error = ""
        if not self.has_app:
            self._last_error = ("Paste your Kick app's Client ID and Client Secret first and press Save "
                                "(see How to make your Kick app).")
            return self.status()
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        # Parameter order as in Kick's docs; redirect_uri is localhost, so no 127.0.0.1 workaround
        query = urlencode({
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        })
        self._pending = {
            "state": state,
            "verifier": verifier,
            "redirect_uri": self.redirect_uri,
            "expires_at": self._now() + LOGIN_TIMEOUT_SEC,
            "authorize_url": f"{AUTHORIZE_URL}?{query}",
        }
        return self.status()

    def cancel_login(self) -> None:
        """Forget a Connect Kick press that was never finished at Kick."""
        self._pending = {}

    async def finish_login(self, code: str = "", state: str = "", error: str = "") -> tuple[bool, str]:
        """The browser came back to /kick/callback. Returns (ok, sentence for the callback page).

        ``state`` must match the latest Connect Kick press, so a link from anywhere else does
        nothing (and leaves that press waiting). A matching answer uses the press up.
        """
        pending = self._pending
        if not pending or not state or not secrets.compare_digest(str(state), str(pending.get("state", ""))):
            return False, "This sign-in link is not the one Core is waiting for. Press Connect Kick again."
        self._pending = {}
        if pending.get("expires_at", 0) <= self._now():
            msg = "The sign-in took too long. Press Connect Kick again."
            self._last_error = msg
            return False, msg
        if error or not code:
            msg = f"Kick did not sign you in ({error or 'no code'}). Press Connect Kick to try again."
            self._last_error = msg
            return False, msg
        try:
            status, body = await self._http.request("POST", TOKEN_URL, form={
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": pending["redirect_uri"],
                "code_verifier": pending["verifier"],
                "code": code,
            })
        except Exception as e:
            msg = f"Could not reach Kick: {e}"
            self._last_error = msg
            log.warning(msg)
            return False, msg
        if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
            why = _kick_message(body) or f"HTTP {status}"
            msg = (f"Kick refused the sign-in: {why}. Check the Client Secret, and that the app's "
                   f"Redirect URL is exactly {pending['redirect_uri']}")
            self._last_error = msg
            log.warning(msg)
            return False, msg
        self._tok = {
            "access_token": str(body["access_token"]),
            "refresh_token": str(body.get("refresh_token") or ""),
            "expires_at": self._now() + _seconds(body.get("expires_in"), 3600),
            "scopes": _scope_list(body.get("scope")) or list(SCOPES),
            "login": "",
            "user_id": "",
            "client_id": self._client_id,
        }
        self._last_error = ""
        await self._fetch_user()
        self._save()
        log.info("Kick connected as %s", self.login or "(unknown)")
        return True, f"Kick is connected as {self.login or 'your account'}."

    # ── using the token ─────────────────────────────────────
    async def token(self) -> Optional[str]:
        """A usable user access token (refreshed when close to expiry), else None."""
        async with self._lock:
            if not self._tok.get("access_token"):
                return None
            if float(self._tok.get("expires_at", 0)) - self._now() < REFRESH_MARGIN_SEC:
                await self._refresh()
            return str(self._tok["access_token"]) if self._tok.get("access_token") else None

    def invalidate(self) -> None:
        """Kick answered 401: refresh before the next use."""
        if self._tok:
            self._tok["expires_at"] = 0.0

    async def send_chat(self, text: str, reply_to_message_id: str = "") -> tuple[bool, str]:
        """Post ``text`` into the signed-in streamer's own Kick chat. Returns (sent, why not).

        Called by KickAdapter.send_message and POST /api/admin/kick/auth/test. Longer text is
        cut to CHAT_MAX_CHARS. ``reply_to_message_id`` is the Kick message id (ChatEvent.message_id)
        to answer, so Kick shows it as a reply. A 401 refreshes once and tries again.
        """
        text = (text or "").strip()
        if not text:
            return False, "Nothing to send."
        if len(text) > CHAT_MAX_CHARS:
            text = text[:CHAT_MAX_CHARS - 1] + "…"
        for attempt in (1, 2):
            tok = await self.token()
            if not tok:
                return False, "Kick is not connected. Press Connect Kick on Settings → Kick."
            try:
                uid = int(self.user_id)
            except ValueError:
                await self._fetch_user()
                try:
                    uid = int(self.user_id)
                except ValueError:
                    return False, "Core doesn't know which Kick channel you signed in with. Press Reconnect."
            body: dict[str, Any] = {"broadcaster_user_id": uid, "content": text, "type": "user"}
            if reply_to_message_id:
                body["reply_to_message_id"] = str(reply_to_message_id)
            try:
                status, answer = await self._http.request(
                    "POST", CHAT_URL, json_body=body, headers={"Authorization": f"Bearer {tok}"})
            except Exception as e:
                return False, f"Could not reach Kick: {e}"
            if status == 200:
                return True, ""
            if status == 401 and attempt == 1:
                self.invalidate()
                continue
            why = _kick_message(answer) or f"HTTP {status}"
            if status == 403:
                why += " (press Reconnect so Kick allows posting in chat)"
            log.warning("Kick chat post refused: %s", why)
            return False, f"Kick refused the message: {why}"
        return False, "Kick refused the message."

    async def disconnect(self) -> None:
        """Forget the sign-in: revoke the token at Kick (best effort) and delete the file."""
        self.cancel_login()
        tok = self._tok.get("access_token")
        self._tok = {}
        self._last_error = ""
        self._save()
        if tok:
            try:
                await self._http.request("POST", REVOKE_URL,
                                         params={"token": tok, "token_hint_type": "access_token"})
            except Exception as e:
                log.debug("Kick revoke failed: %s", e)
        log.info("Kick disconnected")

    # ── private ─────────────────────────────────────────────
    async def _refresh(self) -> None:
        """Swap the refresh token for new tokens. Network errors keep the old ones for a retry."""
        refresh = self._tok.get("refresh_token")
        if not refresh:
            self._drop("Kick sign-in expired (no refresh token). Press Connect Kick again.")
            return
        try:
            status, body = await self._http.request("POST", TOKEN_URL, form={
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh,
            })
        except Exception as e:
            log.warning("Kick token refresh failed: %s (will retry)", e)
            return
        if status == 200 and isinstance(body, dict) and body.get("access_token"):
            self._tok["access_token"] = str(body["access_token"])
            # Kick hands out a new refresh token every time; the old one stops working
            self._tok["refresh_token"] = str(body.get("refresh_token") or refresh)
            self._tok["expires_at"] = self._now() + _seconds(body.get("expires_in"), 3600)
            if body.get("scope"):
                self._tok["scopes"] = _scope_list(body["scope"])
            self._save()
            log.info("Kick token refreshed")
        elif status in (400, 401):
            # Kick no longer takes the refresh token (app secret changed, access removed at Kick)
            self._drop(f"Kick sign-in expired: {_kick_message(body) or f'HTTP {status}'}. Press Connect Kick again.")
        else:
            log.warning("Kick token refresh answered HTTP %s (will retry)", status)

    async def _fetch_user(self) -> None:
        """Fill login / user_id from GET api.kick.com/public/v1/users (no ids = the signed-in user)."""
        tok = self._tok.get("access_token")
        if not tok:
            return
        try:
            status, body = await self._http.request("GET", USERS_URL, headers={"Authorization": f"Bearer {tok}"})
        except Exception as e:
            log.debug("Kick user lookup failed: %s", e)
            return
        rows = body.get("data") if isinstance(body, dict) else None
        if status == 200 and isinstance(rows, list) and rows and isinstance(rows[0], dict):
            me = rows[0]
            self._tok["login"] = str(me.get("name") or self._tok.get("login") or "")
            self._tok["user_id"] = str(me.get("user_id") or self._tok.get("user_id") or "")
            self._save()
        else:
            log.warning("Kick user lookup answered HTTP %s", status)

    def _drop(self, why: str) -> None:
        """Forget the sign-in locally (no revoke) and show ``why`` on the dashboard."""
        self._tok = {}
        self._last_error = why
        self._save()
        log.warning(why)

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("access_token"):
                self._tok = data
        except (OSError, ValueError):
            self._tok = {}

    def _save(self) -> None:
        """Write the token file, or delete it when signed out."""
        try:
            if not self._tok:
                if self._path.exists():
                    self._path.unlink()
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._tok), encoding="utf-8")
        except OSError as e:
            log.debug("could not write %s: %s", self._path, e)


_shared: Optional[KickAuth] = None


def get_auth(config: Optional[dict] = None) -> KickAuth:
    """The Core-wide KickAuth, configured from ``config["kick"]`` and ``config["core"]["port"]`` when given."""
    global _shared
    if _shared is None:
        _shared = KickAuth()
    if config is not None:
        kc = config.get("kick") or {}
        cid = str(kc.get("client_id") or "").strip()
        secret = str(kc.get("client_secret") or "").strip()
        port = (config.get("core") or {}).get("port") or 3850
        if cid != _shared._client_id or secret != _shared._client_secret or str(port) != str(_shared._port):
            _shared.configure(cid, secret, port)
    return _shared
