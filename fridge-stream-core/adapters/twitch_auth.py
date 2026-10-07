"""
Twitch sign-in for Stream Core ("Connect Twitch" in the dashboard).

Stream Core ships as one public Twitch app (``BUILTIN_CLIENT_ID``, registered by the
project owner; a Client ID only names the app and is not a secret). Signing in uses
Twitch's device code flow: Core asks Twitch for a short code, the streamer types it at
twitch.tv/activate, and Core polls until Twitch hands over the tokens. The whole
exchange is between this PC and id.twitch.tv; no third-party server is involved.

The tokens live in ``data/twitch_token.json`` (runtime state, git-ignored) and are never
sent anywhere but Twitch. Core refreshes the access token before it expires and checks it
with Twitch about once an hour, as Twitch asks. **Disconnect** revokes the token at Twitch
and deletes the file.

Advanced: someone can use their own app instead (``twitch.client_id`` and, for a
confidential app, ``twitch.client_secret`` in config.yaml). With a secret and no sign-in,
Core falls back to an app access token (client credentials), which is enough for chatter
pictures but not for posting into chat.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("adapters.twitch_auth")

# Stream Core's own public app on dev.twitch.tv (client type "Public": no secret exists).
BUILTIN_CLIENT_ID = "timu942xi1c5yqua2b5uv6vtu68yy2"
# What the sign-in asks for. Reading chat and posting into it (replies to commands) are
# the only things Core will ever do with the account. Chatter pictures need no scope.
SCOPES = ["user:read:chat", "user:write:chat"]

ID_BASE = "https://id.twitch.tv/oauth2"
DEVICE_URL = f"{ID_BASE}/device"
TOKEN_URL = f"{ID_BASE}/token"
VALIDATE_URL = f"{ID_BASE}/validate"
REVOKE_URL = f"{ID_BASE}/revoke"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "twitch_token.json"
REFRESH_MARGIN_SEC = 5 * 60        # refresh when this close to expiry
VALIDATE_EVERY_SEC = 60 * 60       # Twitch wants tokens validated hourly
APP_TOKEN_MARGIN_SEC = 10 * 60

# (method, url, form data, headers) -> (status, json or {})
Http = Callable[[str, str, Optional[dict], Optional[dict]], Awaitable[tuple[int, Any]]]


async def _http_httpx(method: str, url: str, data: Optional[dict], headers: Optional[dict]) -> tuple[int, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.request(method, url, data=data, headers=headers)
        try:
            body = r.json()
        except ValueError:
            body = {}
        return r.status_code, body


class TwitchAuth:
    """One per Core. The adapter and the dashboard share it (see ``get_auth``)."""

    def __init__(self, client_id: str = "", client_secret: str = "", path: Optional[Path] = None,
                 http: Optional[Http] = None, clock: Callable[[], float] = time.time):
        self._own_client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._path = path or DATA_PATH
        self._http = http or _http_httpx
        self._now = clock
        self._tok: dict[str, Any] = {}      # access_token, refresh_token, expires_at, login, user_id, scopes, client_id
        self._validated_at = 0.0
        self._app_tok: dict[str, Any] = {}  # access_token, expires_at (client credentials)
        self._lock = asyncio.Lock()
        self._pending: dict[str, Any] = {}  # device_code, user_code, verification_uri, expires_at, interval
        self._poll_task: Optional[asyncio.Task] = None
        self._last_error = ""
        self._load()

    # ── configuration ───────────────────────────────────────
    @property
    def client_id(self) -> str:
        return self._own_client_id or BUILTIN_CLIENT_ID

    @property
    def uses_builtin_app(self) -> bool:
        return not self._own_client_id

    def configure(self, client_id: str = "", client_secret: str = "") -> None:
        """Apply config.yaml's twitch.client_id / client_secret. A token from another app is dropped."""
        self._own_client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._app_tok = {}
        if self._tok and self._tok.get("client_id") != self.client_id:
            log.info("Twitch app changed; the stored sign-in belonged to the old app and was dropped")
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
        pending = None
        if self._pending and self._pending.get("expires_at", 0) > self._now():
            pending = {
                "user_code": self._pending.get("user_code", ""),
                "verification_uri": self._pending.get("verification_uri", "https://www.twitch.tv/activate"),
                "expires_in": int(self._pending.get("expires_at", 0) - self._now()),
            }
        return {
            "connected": self.connected,
            "login": self.login,
            "user_id": self.user_id,
            "scopes": list(self._tok.get("scopes") or []),
            "expires_in": int(max(0.0, float(self._tok.get("expires_at", 0)) - self._now())) if self.connected else 0,
            "builtin_app": self.uses_builtin_app,
            "has_secret": bool(self._client_secret),
            "pending": pending,
            "error": self._last_error,
        }

    # ── device code sign-in ─────────────────────────────────
    async def start_login(self) -> dict[str, Any]:
        """Ask Twitch for a code. Returns ``status()`` with ``pending`` filled; polling runs in the background."""
        self.cancel_login()
        self._last_error = ""
        status, body = await self._http("POST", DEVICE_URL,
                                        {"client_id": self.client_id, "scopes": " ".join(SCOPES)}, None)
        if status != 200 or not isinstance(body, dict) or not body.get("device_code"):
            msg = _twitch_message(body) or f"HTTP {status}"
            self._last_error = f"Twitch did not give a sign-in code: {msg}"
            log.warning(self._last_error)
            return self.status()
        self._pending = {
            "device_code": str(body["device_code"]),
            "user_code": str(body.get("user_code", "")),
            "verification_uri": str(body.get("verification_uri") or "https://www.twitch.tv/activate"),
            "expires_at": self._now() + float(body.get("expires_in", 1800)),
            "interval": max(1.0, float(body.get("interval", 5))),
        }
        self._poll_task = asyncio.create_task(self._poll(), name="twitch-device-poll")
        return self.status()

    def cancel_login(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None
        self._pending = {}

    async def poll_once(self) -> bool:
        """One token request for the pending code. True when the sign-in finished (either way)."""
        if not self._pending:
            return True
        if self._pending["expires_at"] <= self._now():
            self._last_error = "The sign-in code expired. Press Connect Twitch again."
            self._pending = {}
            return True
        status, body = await self._http("POST", TOKEN_URL, {
            "client_id": self.client_id,
            "scopes": " ".join(SCOPES),
            "device_code": self._pending["device_code"],
            "grant_type": DEVICE_GRANT,
        }, None)
        if status == 200 and isinstance(body, dict) and body.get("access_token"):
            self._pending = {}
            await self._accept_tokens(body)
            return True
        msg = _twitch_message(body)
        if "authorization_pending" in msg:
            return False
        if "slow_down" in msg:
            self._pending["interval"] += 5.0
            return False
        self._last_error = f"Twitch sign-in failed: {msg or f'HTTP {status}'}"
        log.warning(self._last_error)
        self._pending = {}
        return True

    async def _poll(self) -> None:
        try:
            while self._pending:
                await asyncio.sleep(self._pending.get("interval", 5.0))
                if await self.poll_once():
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:  # network hiccup: give up on this code, the user can press again
            self._last_error = f"Twitch sign-in failed: {e}"
            log.warning(self._last_error)
            self._pending = {}

    async def _accept_tokens(self, body: dict[str, Any]) -> None:
        self._tok = {
            "access_token": str(body["access_token"]),
            "refresh_token": str(body.get("refresh_token") or self._tok.get("refresh_token") or ""),
            "expires_at": self._now() + float(body.get("expires_in", 3600)),
            "scopes": list(body.get("scope") or self._tok.get("scopes") or []),
            "login": self._tok.get("login", ""),
            "user_id": self._tok.get("user_id", ""),
            "client_id": self.client_id,
        }
        self._validated_at = 0.0
        await self._validate()       # fills login / user_id
        self._save()
        log.info("Twitch connected as %s", self.login or "(unknown)")

    # ── using the token ─────────────────────────────────────
    async def token(self) -> Optional[str]:
        """A usable access token: the signed-in user's (refreshed as needed), else an app token
        when a client secret is configured, else None."""
        async with self._lock:
            if self._tok.get("access_token"):
                if float(self._tok.get("expires_at", 0)) - self._now() < REFRESH_MARGIN_SEC:
                    await self._refresh()
                elif self._now() - self._validated_at > VALIDATE_EVERY_SEC:
                    await self._validate()
                if self._tok.get("access_token"):
                    return str(self._tok["access_token"])
            if self._client_secret:
                return await self._app_token()
            return None

    def invalidate(self) -> None:
        """Twitch answered 401: refresh before the next use."""
        if self._tok:
            self._tok["expires_at"] = 0.0
        self._app_tok = {}

    async def disconnect(self) -> None:
        """Forget the sign-in: revoke the token at Twitch (best effort) and delete the file."""
        self.cancel_login()
        tok = self._tok.get("access_token")
        self._tok = {}
        self._app_tok = {}
        self._last_error = ""
        self._save()
        if tok:
            try:
                await self._http("POST", REVOKE_URL, {"client_id": self.client_id, "token": tok}, None)
            except Exception as e:
                log.debug("Twitch revoke failed: %s", e)
        log.info("Twitch disconnected")

    def stop(self) -> None:
        self.cancel_login()

    # ── private ─────────────────────────────────────────────
    async def _refresh(self) -> None:
        refresh = self._tok.get("refresh_token")
        if not refresh:
            self._drop("Twitch sign-in expired (no refresh token). Press Connect Twitch again.")
            return
        data = {"client_id": self.client_id, "grant_type": "refresh_token", "refresh_token": refresh}
        if self._client_secret:
            data["client_secret"] = self._client_secret
        try:
            status, body = await self._http("POST", TOKEN_URL, data, None)
        except Exception as e:
            log.warning("Twitch token refresh failed: %s (will retry)", e)
            return
        if status == 200 and isinstance(body, dict) and body.get("access_token"):
            self._tok["access_token"] = str(body["access_token"])
            self._tok["refresh_token"] = str(body.get("refresh_token") or refresh)
            self._tok["expires_at"] = self._now() + float(body.get("expires_in", 3600))
            if body.get("scope"):
                self._tok["scopes"] = list(body["scope"])
            self._validated_at = self._now()
            self._save()
            log.info("Twitch token refreshed")
        elif status in (400, 401):
            # Twitch invalidated the refresh token (password change, revoked app, 30-day limit)
            self._drop(f"Twitch sign-in expired: {_twitch_message(body) or f'HTTP {status}'}. Press Connect Twitch again.")
        else:
            log.warning("Twitch token refresh answered HTTP %s (will retry)", status)

    async def _validate(self) -> None:
        tok = self._tok.get("access_token")
        if not tok:
            return
        try:
            status, body = await self._http("GET", VALIDATE_URL, None, {"Authorization": f"OAuth {tok}"})
        except Exception as e:
            log.debug("Twitch validate failed: %s", e)
            return
        if status == 200 and isinstance(body, dict):
            self._tok["login"] = str(body.get("login") or self._tok.get("login") or "")
            self._tok["user_id"] = str(body.get("user_id") or self._tok.get("user_id") or "")
            if body.get("scopes"):
                self._tok["scopes"] = list(body["scopes"])
            if body.get("expires_in") is not None:
                self._tok["expires_at"] = self._now() + float(body["expires_in"])
            self._validated_at = self._now()
            self._save()
        elif status == 401:
            await self._refresh()

    async def _app_token(self) -> Optional[str]:
        if self._app_tok.get("access_token") and float(self._app_tok.get("expires_at", 0)) - self._now() > APP_TOKEN_MARGIN_SEC:
            return str(self._app_tok["access_token"])
        try:
            status, body = await self._http("POST", TOKEN_URL, {
                "client_id": self.client_id, "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            }, None)
        except Exception as e:
            log.warning("Twitch app token request failed: %s", e)
            return None
        if status == 200 and isinstance(body, dict) and body.get("access_token"):
            self._app_tok = {"access_token": str(body["access_token"]),
                             "expires_at": self._now() + float(body.get("expires_in", 3600))}
            return str(self._app_tok["access_token"])
        log.warning("Twitch app token refused: %s", _twitch_message(body) or f"HTTP {status}")
        return None

    def _drop(self, why: str) -> None:
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
        try:
            if not self._tok:
                if self._path.exists():
                    self._path.unlink()
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._tok), encoding="utf-8")
        except OSError as e:
            log.debug("could not write %s: %s", self._path, e)


def _twitch_message(body: Any) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or "")
    return ""


_shared: Optional[TwitchAuth] = None


def get_auth(config: Optional[dict] = None) -> TwitchAuth:
    """The Core-wide TwitchAuth, configured from ``config["twitch"]`` when given."""
    global _shared
    if _shared is None:
        _shared = TwitchAuth()
    if config is not None:
        tw = config.get("twitch") or {}
        own = str(tw.get("client_id") or "")
        secret = str(tw.get("client_secret") or "")
        if own != _shared._own_client_id or secret != _shared._client_secret:
            _shared.configure(own, secret)
    return _shared
