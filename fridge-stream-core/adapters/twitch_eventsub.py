"""
Twitch EventSub (WebSocket): the paid events Twitch only sends here, not in IRC chat.

* ``channel.bits.use``: bits power-ups with their exact bits (Gigantify an Emote, Message
  Effects, On-screen Celebrations, the channel's own custom power-ups). Cheers still come
  from chat, so they are skipped here.
* ``channel.charity_campaign.donate``: donations to the channel's charity campaign.
* ``channel.hype_train.end`` (v2): a Hype Train's summary (level, type, top contributors).

It needs the streamer's own Twitch sign-in ("Connect Twitch") with the scopes in
``adapters.twitch_auth.PAID_SCOPES``. Signed in as another account, or with an older
sign-in that lacks those scopes, it stays off and says why (``status()``); chat keeps
working either way. Everything is between this PC and Twitch.

Each event becomes an ``_emit_alert`` call on the Twitch adapter (alert kinds ``powerup``,
``celebration``, ``charity``, ``hypetrain``), so the overlay, the Paid list and the end
credits treat it like any other platform alert.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("adapters.twitch_eventsub")

WS_URL = "wss://eventsub.wss.twitch.tv/ws"
SUBS_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"

# (subscription type, version, scope it needs)
SUBSCRIPTIONS: list[tuple[str, str, str]] = [
    ("channel.bits.use", "1", "bits:read"),
    ("channel.charity_campaign.donate", "1", "channel:read:charity"),
    ("channel.hype_train.end", "2", "channel:read:hype_train"),
]

IDLE_RECHECK_SEC = 30.0            # not signed in yet / wrong account: look again this often
BACKOFF_MAX = 60.0                 # seconds; reconnect waits double from 3 s up to this

# Power-up type from Twitch -> the item name shown on the alert / Paid list
POWER_UPS = {
    "gigantify_an_emote": "Gigantified emote",
    "message_effect": "Message effect",
    "celebration": "On-screen celebration",
}
TRAIN_TYPES = {"golden_kappa": "Golden Kappa Train", "treasure": "Treasure Train"}

# (method, url, json body, headers) -> (status, json or {})
Http = Callable[[str, str, Optional[dict], Optional[dict]], Awaitable[tuple[int, Any]]]


async def _http_httpx(method: str, url: str, body: Optional[dict], headers: Optional[dict]) -> tuple[int, Any]:
    """Default ``Http``: one JSON request; a body that isn't JSON comes back as {}."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.request(method, url, json=body, headers=headers)
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data


# ----------------------------------------------------------------------
# Events → alert kwargs (plain functions, tested on their own)
# ----------------------------------------------------------------------


def _who(ev: dict, prefix: str = "user") -> dict[str, str]:
    """``<prefix>_login / _name / _id`` of an event -> username / display_name / user_id."""
    login = str(ev.get(f"{prefix}_login") or "")
    return {"username": login, "display_name": str(ev.get(f"{prefix}_name") or login),
            "user_id": str(ev.get(f"{prefix}_id") or "")}


def bits_use_alert(ev: dict) -> Optional[dict[str, Any]]:
    """``channel.bits.use`` → ``_emit_alert`` kwargs. Cheers → None (chat already has them)."""
    kind = str(ev.get("type") or "")
    if kind == "cheer":
        return None
    try:
        bits = max(0, int(ev.get("bits") or 0))
    except (TypeError, ValueError):
        bits = 0
    item, alert_kind = "", "powerup"
    if kind == "power_up":
        pu = ev.get("power_up") or {}
        ptype = str(pu.get("type") or "")
        if ptype == "celebration":
            alert_kind = "celebration"
        item = POWER_UPS.get(ptype, "Power-up")
        emote = (pu.get("emote") or {}).get("name")
        if ptype == "gigantify_an_emote" and emote:
            item = f"Gigantified {emote}"
    elif kind == "custom_power_up":
        item = str((ev.get("custom_power_up") or {}).get("title") or "Custom power-up")
    elif kind == "combo":
        item = "Combo"            # Twitch retired Combos in 2026; kept in case one arrives
    else:
        item = "Power-up"
    text = str((ev.get("message") or {}).get("text") or "").strip()
    return {"kind": alert_kind, **_who(ev), "amount": float(bits) if bits else None,
            "currency": "bits", "item": item, "message": text}


def _money(amount: dict) -> tuple[Optional[float], str]:
    """Twitch money ``{"value": 550, "decimal_places": 2, "currency": "USD"}`` → (5.5, "USD")."""
    if not isinstance(amount, dict):
        return None, ""
    try:
        value = int(amount.get("value"))
        places = int(amount.get("decimal_places", amount.get("decimal_place", 2)) or 0)
    except (TypeError, ValueError):
        return None, str(amount.get("currency") or "")
    return round(value / (10 ** places), places), str(amount.get("currency") or "")


def charity_alert(ev: dict) -> Optional[dict[str, Any]]:
    """``channel.charity_campaign.donate`` → ``_emit_alert`` kwargs."""
    amount, currency = _money(ev.get("amount") or {})
    who = _who(ev)
    if not who["username"] and not who["display_name"]:
        return None
    return {"kind": "charity", **who, "amount": amount, "currency": currency or "USD",
            "item": str(ev.get("charity_name") or "charity")}


def _contribution(c: dict) -> str:
    """One Hype Train top contribution as text, e.g. ``Name (1,000 bits)``."""
    name = str(c.get("user_name") or c.get("user_login") or "someone")
    ctype = str(c.get("type") or "")
    try:
        total = int(c.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    if ctype == "bits" and total:
        return f"{name} ({total:,} bits)"
    if ctype == "subscription":
        return f"{name} (subs)"
    return name


def hype_train_alert(ev: dict) -> Optional[dict[str, Any]]:
    """``channel.hype_train.end`` v2 → a summary alert (level, type, top contributors)."""
    try:
        level = max(1, int(ev.get("level") or 1))
    except (TypeError, ValueError):
        level = 1
    train = TRAIN_TYPES.get(str(ev.get("type") or ""), "Hype Train")
    if ev.get("is_shared_train"):
        train = "Shared " + train[0].lower() + train[1:]
    tops = [_contribution(c) for c in (ev.get("top_contributions") or []) if isinstance(c, dict)]
    message = ("Top: " + ", ".join(tops)) if tops else ""
    return {"kind": "hypetrain", **_who(ev, "broadcaster_user"), "display_name": train,
            "level": level, "item": train, "message": message}


# EventSub type -> converter. Keep in sync with SUBSCRIPTIONS above.
HANDLERS: dict[str, Callable[[dict], Optional[dict[str, Any]]]] = {
    "channel.bits.use": bits_use_alert,
    "channel.charity_campaign.donate": charity_alert,
    "channel.hype_train.end": hype_train_alert,
}


# ----------------------------------------------------------------------
# The connection
# ----------------------------------------------------------------------

# The running client (set by start()), so the module-level status() / bits_live() can answer
_current: Optional["EventSubClient"] = None


def status() -> dict[str, Any]:
    """For the dashboard: is the paid-events link on, and if not, why."""
    if _current is None:
        return {"state": "off", "message": "Twitch paid events are off (Twitch chat isn't running)."}
    return _current.status()


def bits_live() -> bool:
    """True while power-ups arrive here with their bits (chat's own power-up lines then
    stay off the Paid list, so nothing is listed twice)."""
    return bool(_current and _current.live and "channel.bits.use" in _current.subscribed)


class EventSubClient:
    """One WebSocket to Twitch EventSub for the channel's paid events.

    ``auth`` is the shared TwitchAuth; ``on_alert`` gets the kwargs for the adapter's
    ``_emit_alert``. ``http`` / ``connect`` can be swapped in tests.
    """

    def __init__(self, auth, channel: str, on_alert: Callable[[dict], Awaitable[None]],
                 http: Optional[Http] = None, connect=None):
        self.auth = auth
        self.channel = (channel or "").lower()
        self.on_alert = on_alert
        self._http = http or _http_httpx
        self._connect = connect             # tests: a fake websockets.connect
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._seen: OrderedDict[str, None] = OrderedDict()
        self.live = False
        self.subscribed: set[str] = set()
        self.state = "off"
        self.message = ""

    # ---- status ------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """``state`` off / on / retrying, a plain ``message``, and the subscribed event types."""
        return {"state": self.state, "message": self.message, "events": sorted(self.subscribed)}

    def _set(self, state: str, message: str) -> None:
        """Change the status; logs only when it actually changed."""
        if (state, message) != (self.state, self.message):
            (log.info if state in ("on", "off") else log.warning)("Twitch paid events: %s", message)
        self.state, self.message = state, message

    def why_not(self) -> str:
        """'' when the sign-in can run EventSub, else what the streamer should do."""
        if not self.auth.connected:
            return "Connect Twitch (Settings → Twitch) to get bits power-ups, celebrations, charity and Hype Trains."
        if self.auth.login and self.channel and self.auth.login.lower() != self.channel:
            return (f"Signed in as {self.auth.login}, not {self.channel}. Twitch only sends these events to the "
                    "channel owner's own sign-in.")
        have = set(self.auth.status().get("scopes") or [])
        missing = [scope for _, _, scope in SUBSCRIPTIONS if scope not in have]
        if len(missing) == len(SUBSCRIPTIONS):
            return "Press Reconnect under Settings → Twitch once, so Twitch allows the paid events."
        return ""

    # ---- running -----------------------------------------------------

    def start(self) -> None:
        """Run the connection loop in the background (called by the Twitch adapter)."""
        global _current
        _current = self
        self._stop.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="twitch-eventsub")

    async def stop(self) -> None:
        """Stop the loop and wait for it to finish."""
        global _current
        self._stop.set()
        self.live = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if _current is self:
            _current = None

    async def _wait(self, seconds: float) -> bool:
        """Sleep, or return True at once when stopping."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _loop(self) -> None:
        """Wait until the sign-in allows EventSub, then keep one session up, reconnecting with backoff."""
        backoff = 3.0
        url = WS_URL
        while not self._stop.is_set():
            why = self.why_not()
            if why:
                self.live = False
                self.subscribed = set()
                self._set("off", why)
                if await self._wait(IDLE_RECHECK_SEC):
                    return
                continue
            try:
                url = await self._session(url)
                backoff = 3.0
                if url:
                    continue            # Twitch asked us to move to another address
                url = WS_URL
            except asyncio.CancelledError:
                raise
            except Exception as e:
                url = WS_URL
                self.live = False
                self._set("retrying", f"Twitch paid events disconnected ({e or type(e).__name__}); "
                                      f"retrying in {backoff:.0f} s.")
            if await self._wait(backoff):
                return
            backoff = min(backoff * 2, BACKOFF_MAX)

    async def _session(self, url: str) -> str:
        """One connection. Returns a reconnect address, or '' when the link closed."""
        connect = self._connect
        if connect is None:
            import websockets

            connect = websockets.connect
        # After a session_reconnect, Twitch carries the subscriptions over to the new address;
        # only a fresh connection to WS_URL has to subscribe again.
        resubscribe = url == WS_URL
        async with connect(url, max_size=2**20) as ws:
            keepalive = 10.0
            while not self._stop.is_set():
                try:
                    # Twitch sends a keepalive every ``keepalive`` seconds; silence beyond that means a dead link
                    raw = await asyncio.wait_for(ws.recv(), timeout=keepalive + 10.0)
                except asyncio.TimeoutError:
                    raise ConnectionError("Twitch went quiet")
                msg = json.loads(raw)
                meta = msg.get("metadata") or {}
                payload = msg.get("payload") or {}
                mtype = meta.get("message_type")
                if mtype == "session_welcome":
                    session = payload.get("session") or {}
                    keepalive = float(session.get("keepalive_timeout_seconds") or 10)
                    if resubscribe:
                        await self._subscribe_all(str(session.get("id") or ""))
                    self.live = bool(self.subscribed)
                    if self.live:
                        self._set("on", "Twitch paid events on: " + ", ".join(sorted(self.subscribed)) + ".")
                elif mtype == "session_reconnect":
                    return str((payload.get("session") or {}).get("reconnect_url") or "")
                elif mtype == "notification":
                    await self._notification(str(meta.get("message_id") or ""), payload)
                elif mtype == "revocation":
                    sub = (payload.get("subscription") or {})
                    self.subscribed.discard(str(sub.get("type") or ""))
                    self._set("off" if not self.subscribed else "on",
                              f"Twitch stopped sending {sub.get('type')} ({sub.get('status')}). "
                              "Press Reconnect under Settings → Twitch.")
        self.live = False
        return ""

    async def _subscribe_all(self, session_id: str) -> None:
        """Subscribe this session to every event the sign-in has the scope for."""
        self.subscribed = set()
        have = set(self.auth.status().get("scopes") or [])
        skipped = []
        for stype, version, scope in SUBSCRIPTIONS:
            if scope not in have:
                skipped.append(stype)
                continue
            if await self._subscribe(stype, version, session_id):
                self.subscribed.add(stype)
        if skipped:
            log.info("Twitch paid events skipped (sign in again to allow): %s", ", ".join(skipped))
        if not self.subscribed:
            raise ConnectionError("Twitch refused every paid-event subscription")

    async def _subscribe(self, stype: str, version: str, session_id: str) -> bool:
        """One Helix subscription request; a 401 refreshes the token and tries once more."""
        body = {"type": stype, "version": version,
                "condition": {"broadcaster_user_id": self.auth.user_id},
                "transport": {"method": "websocket", "session_id": session_id}}
        for attempt in (1, 2):
            token = await self.auth.token()
            if not token:
                return False
            status, data = await self._http("POST", SUBS_URL, body, {
                "Client-Id": self.auth.client_id, "Authorization": f"Bearer {token}"})
            if status in (200, 202):
                return True
            if status == 409:            # already there (a quick reconnect)
                return True
            if status == 401 and attempt == 1:
                self.auth.invalidate()
                continue
            msg = (data or {}).get("message") if isinstance(data, dict) else ""
            log.warning("Twitch refused %s: HTTP %s %s", stype, status, msg or "")
            return False
        return False

    async def _notification(self, message_id: str, payload: dict) -> None:
        """Turn one event into an alert, skipping duplicates (the last 500 message ids are kept)."""
        if message_id:
            if message_id in self._seen:
                return              # Twitch may send a message twice
            self._seen[message_id] = None
            while len(self._seen) > 500:
                self._seen.popitem(last=False)
        stype = str((payload.get("subscription") or {}).get("type") or "")
        handler = HANDLERS.get(stype)
        if handler is None:
            return
        try:
            alert = handler(payload.get("event") or {})
        except Exception:
            log.exception("could not read Twitch %s event", stype)
            return
        if alert:
            alert["event_id"] = message_id
            await self.on_alert(alert)
