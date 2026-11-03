"""
YouTube sign-in for Stream Core ("Connect YouTube" on the YouTube card in Settings).

Reading YouTube chat needs no sign-in (adapters/youtube.py, innertube or an API key). This
sign-in is only for **posting** Core's replies into the live chat (YouTube Data API
``liveChatMessages.insert``), which Google allows only with the channel owner's OAuth token.

Google won't let an open-source program ship one shared app with its secret, so (like Kick,
adapters/kick_auth.py) each streamer makes their **own** Google Cloud OAuth client of type
"TVs and Limited Input devices" and pastes its Client ID and Client Secret into Settings →
YouTube (``youtube.client_id`` / ``youtube.client_secret``). docs/YOUTUBE_APP_SETUP.md has
the steps. That client type uses Google's device code flow, the same as Connect Twitch:

1. **Connect YouTube** (POST /api/admin/youtube/auth/start) asks Google for a short code.
2. The streamer opens google.com/device, types the code, picks the channel's Google
   account and presses Allow. Core polls Google until the tokens arrive (``_poll``).
3. Core asks the YouTube API which channel signed in (``channels?mine=true``).

The tokens live in ``data/youtube_token.json`` (runtime state, git-ignored) and are only
ever sent to Google. Core refreshes the access token before it expires. **Disconnect**
revokes the token at Google and deletes the file.

Quota: each posted message costs 50 of the project's 10,000 free daily API units (about 200
replies a day). Finding the stream's chat id costs 1 unit, once per video.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("adapters.youtube_auth")

# The one scope Core asks for. "youtube" (manage your YouTube account) is the narrowest
# scope that can post live chat messages AND is allowed for the device code flow. Add a scope
# here only with the feature that needs it; older sign-ins then show "press Reconnect"
# (status()["missing_scopes"]).
SCOPES = ["https://www.googleapis.com/auth/youtube"]

DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
API_BASE = "https://www.googleapis.com/youtube/v3"
CHANNELS_URL = f"{API_BASE}/channels"
VIDEOS_URL = f"{API_BASE}/videos"
CHAT_URL = f"{API_BASE}/liveChat/messages"

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "youtube_token.json"
REFRESH_MARGIN_SEC = 5 * 60        # refresh when this close to expiry
CHAT_MAX_CHARS = 200               # YouTube refuses longer live chat messages

# (method, url, form data, json body, headers) -> (status, json or {})
Http = Callable[[str, str, Optional[dict], Optional[dict], Optional[dict]], Awaitable[tuple[int, Any]]]


async def _http_httpx(method: str, url: str, form: Optional[dict], body: Optional[dict],
                      headers: Optional[dict]) -> tuple[int, Any]:
    """Default ``Http``: ``form`` goes form-encoded (Google's sign-in wants that), ``body`` as
    JSON (the YouTube API wants that). A body that isn't JSON comes back as {}."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.request(method, url, data=form, json=body, headers=headers)
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data


def _google_message(body: Any) -> str:
    """The human-readable reason in a Google error answer ("" if none). Google answers either
    {"error": "...", "error_description": "..."} (sign-in) or {"error": {"message": ...}} (API)."""
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or "")
    return str(body.get("error_description") or err or "")


class YouTubeAuth:
    """One per Core. The YouTube adapter and the dashboard share it (``get_auth``).

    ``http`` and ``clock`` can be swapped in tests so nothing goes to Google.
    Times stored here (``expires_at``) are ``clock()`` seconds.
    """

    def __init__(self, client_id: str = "", client_secret: str = "", path: Optional[Path] = None,
                 http: Optional[Http] = None, clock: Callable[[], float] = time.time):
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._path = path or DATA_PATH
        self._http = http or _http_httpx
        self._now = clock
        self._tok: dict[str, Any] = {}      # access_token, refresh_token, expires_at, channel_id, channel_title, scopes, client_id
        self._pending: dict[str, Any] = {}  # device_code, user_code, verification_url, expires_at, interval
        self._poll_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._last_error = ""
        # liveChatId per video id (videos.list costs quota, so asked once per stream)
        self._chat_ids: dict[str, str] = {}
        self._load()

    # ── configuration ───────────────────────────────────────
    def configure(self, client_id: str = "", client_secret: str = "") -> None:
        """Apply config.yaml's youtube.client_id / client_secret. A sign-in made with another
        client can't be refreshed with this one, so it is dropped."""
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        if self._tok and self._tok.get("client_id") != self._client_id:
            log.info("YouTube app changed; the stored sign-in belonged to the old app and was dropped")
            self._tok = {}
            self._save()

    @property
    def has_app(self) -> bool:
        """True once both the Client ID and the Client Secret of the streamer's Google client are set."""
        return bool(self._client_id and self._client_secret)

    # ── status (never includes tokens or the secret) ────────
    @property
    def connected(self) -> bool:
        return bool(self._tok.get("access_token"))

    @property
    def channel_id(self) -> str:
        return str(self._tok.get("channel_id") or "")

    @property
    def channel_title(self) -> str:
        return str(self._tok.get("channel_title") or "")

    def status(self) -> dict[str, Any]:
        """What the dashboard's YouTube card shows (GET /api/admin/youtube/auth)."""
        pending = None
        if self._pending and self._pending.get("expires_at", 0) > self._now():
            pending = {
                "user_code": self._pending.get("user_code", ""),
                "verification_url": self._pending.get("verification_url", "https://www.google.com/device"),
                "expires_in": int(self._pending["expires_at"] - self._now()),
            }
        scopes = list(self._tok.get("scopes") or [])
        return {
            "connected": self.connected,
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "scopes": scopes,
            "has_app": self.has_app,
            "has_client_id": bool(self._client_id),
            "has_secret": bool(self._client_secret),
            "pending": pending,
            "error": self._last_error,
            "missing_scopes": [s for s in SCOPES if s not in scopes] if self.connected else [],
        }

    # ── device code sign-in ─────────────────────────────────
    async def start_login(self) -> dict[str, Any]:
        """Ask Google for a code to type at google.com/device; polls in the background. Returns ``status()``."""
        self.cancel_login()
        self._last_error = ""
        if not self.has_app:
            self._last_error = ("Paste your Google client's Client ID and Client Secret first and press "
                                "Save (see How to make your Google client).")
            return self.status()
        try:
            status, body = await self._http("POST", DEVICE_URL,
                                             {"client_id": self._client_id, "scope": " ".join(SCOPES)}, None, None)
        except Exception as e:
            self._last_error = f"Could not reach Google: {e}"
            return self.status()
        if status != 200 or not isinstance(body, dict) or not body.get("device_code"):
            why = _google_message(body) or f"HTTP {status}"
            if "invalid_client" in why or "Unauthorized" in why:
                why += " (the Client ID must be from a \"TVs and Limited Input devices\" client)"
            self._last_error = f"Google refused the sign-in: {why}"
            return self.status()
        self._pending = {
            "device_code": str(body["device_code"]),
            "user_code": str(body.get("user_code") or ""),
            "verification_url": str(body.get("verification_url") or "https://www.google.com/device"),
            "expires_at": self._now() + float(body.get("expires_in", 1800)),
            "interval": max(5.0, float(body.get("interval", 5))),
        }
        try:
            self._poll_task = asyncio.get_running_loop().create_task(self._poll(), name="youtube-auth-poll")
        except RuntimeError:
            self._poll_task = None   # tests without a loop call poll_once themselves
        return self.status()

    def cancel_login(self) -> None:
        """Stop waiting for the code (Cancel button, or a new Connect press)."""
        self._pending = {}
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None

    async def poll_once(self) -> bool:
        """One token request for the waiting code. True when the sign-in finished (either way)."""
        if not self._pending:
            return True
        if self._pending.get("expires_at", 0) <= self._now():
            self._pending = {}
            self._last_error = "The code ran out before it was entered. Press Connect YouTube again."
            return True
        try:
            status, body = await self._http("POST", TOKEN_URL, {
                "client_id": self._client_id, "client_secret": self._client_secret,
                "device_code": self._pending["device_code"], "grant_type": DEVICE_GRANT,
            }, None, None)
        except Exception as e:
            log.debug("YouTube sign-in poll failed: %s", e)
            return False
        if status == 200 and isinstance(body, dict) and body.get("access_token"):
            self._pending = {}
            await self._accept_tokens(body)
            return True
        err = body.get("error") if isinstance(body, dict) else ""
        if err == "authorization_pending":
            return False
        if err == "slow_down":
            self._pending["interval"] = float(self._pending.get("interval", 5)) + 5
            return False
        self._pending = {}
        self._last_error = ("You pressed Cancel/Deny at Google." if err == "access_denied"
                            else f"Google refused the sign-in: {_google_message(body) or f'HTTP {status}'}")
        return True

    async def _poll(self) -> None:
        """Ask every ``interval`` seconds (Google says how often) until the code is entered or runs out."""
        try:
            while self._pending:
                await asyncio.sleep(float(self._pending.get("interval", 5)))
                if await self.poll_once():
                    return
        except asyncio.CancelledError:
            pass

    async def _accept_tokens(self, body: dict[str, Any]) -> None:
        """Store a fresh token answer from Google and look up which channel signed in."""
        self._tok = {
            "access_token": str(body["access_token"]),
            "refresh_token": str(body.get("refresh_token") or self._tok.get("refresh_token") or ""),
            "expires_at": self._now() + float(body.get("expires_in", 3600)),
            "scopes": str(body.get("scope") or " ".join(SCOPES)).split(),
            "channel_id": "",
            "channel_title": "",
            "client_id": self._client_id,
        }
        self._last_error = ""
        await self._fetch_channel()
        self._save()
        log.info("YouTube connected as %s", self.channel_title or "(unknown channel)")

    async def _fetch_channel(self) -> None:
        """Fill channel_id / channel_title from ``channels?part=snippet&mine=true`` (1 quota unit)."""
        tok = self._tok.get("access_token")
        if not tok:
            return
        try:
            status, body = await self._http("GET", f"{CHANNELS_URL}?part=snippet&mine=true", None, None,
                                             {"Authorization": f"Bearer {tok}"})
        except Exception as e:
            log.debug("YouTube channel lookup failed: %s", e)
            return
        items = body.get("items") if isinstance(body, dict) else None
        if status == 200 and items:
            self._tok["channel_id"] = str(items[0].get("id") or "")
            self._tok["channel_title"] = str((items[0].get("snippet") or {}).get("title") or "")
        elif status == 200:
            self._last_error = "That Google account has no YouTube channel. Connect with the channel's own account."

    # ── using the token ─────────────────────────────────────
    async def token(self) -> Optional[str]:
        """A usable access token (refreshed when close to expiry), or None when not signed in."""
        async with self._lock:
            if not self._tok.get("access_token"):
                return None
            if float(self._tok.get("expires_at", 0)) - self._now() < REFRESH_MARGIN_SEC:
                await self._refresh()
            return str(self._tok["access_token"]) if self._tok.get("access_token") else None

    def invalidate(self) -> None:
        """Google answered 401: refresh before the next use."""
        if self._tok:
            self._tok["expires_at"] = 0.0

    async def live_chat_id(self, video_id: str) -> tuple[str, str]:
        """(liveChatId of ``video_id``'s live chat, why not). From ``videos.list
        liveStreamingDetails`` with the sign-in (no API key needed); remembered per video."""
        video_id = (video_id or "").strip()
        if not video_id:
            return "", "no live video set (Settings → YouTube → Live video, or Live controls)"
        if video_id in self._chat_ids:
            return self._chat_ids[video_id], ""
        tok = await self.token()
        if not tok:
            return "", "YouTube is not connected"
        try:
            status, body = await self._http(
                "GET", f"{VIDEOS_URL}?part=liveStreamingDetails&id={video_id}", None, None,
                {"Authorization": f"Bearer {tok}"})
        except Exception as e:
            return "", f"could not reach YouTube: {e}"
        items = body.get("items") if isinstance(body, dict) else None
        if status != 200:
            return "", f"YouTube refused the video lookup: {_google_message(body) or f'HTTP {status}'}"
        chat = str(((items or [{}])[0].get("liveStreamingDetails") or {}).get("activeLiveChatId") or "")
        if not chat:
            return "", "that video has no live chat right now (not live yet, or the stream ended)"
        self._chat_ids[video_id] = chat
        return chat, ""

    async def send_chat(self, text: str, live_chat_id: str) -> tuple[bool, str]:
        """Post ``text`` into the live chat ``live_chat_id`` (liveChatMessages.insert, 50 quota
        units). Returns (sent, why not). Longer text is cut to CHAT_MAX_CHARS. A 401 refreshes
        once and tries again. Called by YouTubeAdapter.send_message and the card's Send test message."""
        text = (text or "").strip()
        if not text:
            return False, "Nothing to send."
        if len(text) > CHAT_MAX_CHARS:
            text = text[:CHAT_MAX_CHARS - 1] + "…"
        body = {"snippet": {"liveChatId": live_chat_id, "type": "textMessageEvent",
                            "textMessageDetails": {"messageText": text}}}
        for attempt in (1, 2):
            tok = await self.token()
            if not tok:
                return False, "YouTube is not connected. Press Connect YouTube on Settings → YouTube."
            try:
                status, answer = await self._http("POST", f"{CHAT_URL}?part=snippet", None, body,
                                                  {"Authorization": f"Bearer {tok}"})
            except Exception as e:
                return False, f"Could not reach YouTube: {e}"
            if status == 200:
                return True, ""
            if status == 401 and attempt == 1:
                self.invalidate()
                continue
            why = _google_message(answer) or f"HTTP {status}"
            if status == 403 and "quota" in why.lower():
                why += " (the Google project's daily API quota is used up; it resets at midnight Pacific time)"
            elif status == 403:
                why += " (connect with the channel owner's account, or press Reconnect)"
            if status in (403, 404) and "chat" in why.lower():
                # the stream ended or the chat id is stale: look it up again next time
                self._chat_ids = {k: v for k, v in self._chat_ids.items() if v != live_chat_id}
            log.warning("YouTube chat post refused: %s", why)
            return False, f"YouTube refused the message: {why}"
        return False, "YouTube refused the message."

    async def disconnect(self) -> None:
        """Forget the sign-in: revoke the token at Google (best effort) and delete the file."""
        self.cancel_login()
        tok = self._tok.get("refresh_token") or self._tok.get("access_token")
        self._tok = {}
        self._chat_ids = {}
        self._last_error = ""
        self._save()
        if tok:
            try:
                await self._http("POST", REVOKE_URL, {"token": tok}, None, None)
            except Exception as e:
                log.debug("YouTube revoke failed: %s", e)
        log.info("YouTube disconnected")

    def stop(self) -> None:
        """Core is shutting down: stop a sign-in in progress (the saved token stays)."""
        self.cancel_login()

    # ── private ─────────────────────────────────────────────
    async def _refresh(self) -> None:
        """Swap the refresh token for a new access token (Google keeps the same refresh token).
        Network errors keep the old one for a retry; a refused refresh drops the sign-in."""
        refresh = self._tok.get("refresh_token")
        if not refresh:
            self._drop("YouTube sign-in expired. Press Connect YouTube again.")
            return
        try:
            status, body = await self._http("POST", TOKEN_URL, {
                "client_id": self._client_id, "client_secret": self._client_secret,
                "grant_type": "refresh_token", "refresh_token": refresh,
            }, None, None)
        except Exception as e:
            log.warning("YouTube token refresh failed: %s (will retry)", e)
            return
        if status == 200 and isinstance(body, dict) and body.get("access_token"):
            self._tok["access_token"] = str(body["access_token"])
            self._tok["expires_at"] = self._now() + float(body.get("expires_in", 3600))
            if body.get("refresh_token"):
                self._tok["refresh_token"] = str(body["refresh_token"])
            self._save()
        elif status in (400, 401):
            # revoked, password changed, or a "Testing" Google project's 7-day limit
            self._drop("YouTube sign-in expired or was removed. Press Connect YouTube again "
                       "(a Google project left in Testing signs out after 7 days; see the setup steps).")
        else:
            log.warning("YouTube token refresh answered HTTP %s (will retry)", status)

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


_shared: Optional[YouTubeAuth] = None


def get_auth(config: Optional[dict] = None) -> YouTubeAuth:
    """The Core-wide YouTubeAuth, configured from ``config["youtube"]`` when given."""
    global _shared
    if _shared is None:
        _shared = YouTubeAuth()
    if config is not None:
        yc = config.get("youtube") or {}
        cid = str(yc.get("client_id") or "").strip()
        secret = str(yc.get("client_secret") or "").strip()
        if cid != _shared._client_id or secret != _shared._client_secret:
            _shared.configure(cid, secret)
    return _shared
