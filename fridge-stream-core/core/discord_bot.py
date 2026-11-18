"""
Discord bot: Stream Core logs in to Discord as the streamer's OWN bot and takes video requests.

Why our own small client (no discord.py): Core already has websockets + httpx, and a new library
would need a pip install on the streamer's PC. Discord's bot API is two plain parts:
  1. the Gateway, a WebSocket (wss://gateway.discord.gg) that pushes events to us:
     HELLO (op 10) -> we IDENTIFY (op 2) with the token and the intents we want, then send a
     heartbeat (op 1) every heartbeat_interval ms and get HEARTBEAT_ACK (op 11) back. Events arrive
     as DISPATCH (op 0) with a name in "t": READY, GUILD_CREATE, MESSAGE_CREATE, INTERACTION_CREATE.
     op 7 (reconnect) / op 9 (invalid session) / a dropped socket -> we connect and IDENTIFY again.
  2. the REST API (https://discord.com/api/v10) for everything we do: post a message, add a
     reaction, list the server's channels and roles, answer a button press.

Intents (what the gateway sends): GUILDS (1<<0), GUILD_MESSAGES (1<<9) and MESSAGE_CONTENT
(1<<15). MESSAGE_CONTENT is a "privileged" intent: the streamer switches it on once in the
Discord developer portal (Bot > Message Content Intent). Without it Discord closes the socket
with code 4014, and the Setup page says what to switch on. Button presses (INTERACTION_CREATE)
come without any intent.

What the bot does (all on the streamer's server, in the channels picked on Setup > Discord):
  request channel   a message with a YouTube link -> VideoRequestQueue.submit; the bot reacts ⏳
                    (or replies why not and reacts ❌). The ⏳ becomes ✅ approved, ❌ denied,
                    ▶️ playing, 🏁 played. Optional: "Now playing" posts, deleting other chatter.
  mod channel       one message per request with Approve / Deny / Play now buttons. Only people
                    with Administrator or Manage Server, or one of the "approver" roles, may press
                    them; the message is edited to say who decided.

Settings: the ``discord:`` block of config.yaml (DEFAULTS below, core/config.py). The bot token
stays in config.yaml on the PC: the dashboard only ever sees whether one is set (token_set).
main.py makes one DiscordBot as StreamCore.discord (core_state.discord) and starts it when
discord.enabled is on; api/video_request_routes.py restarts it after a settings save.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from core.video_requests import VideoRequestQueue, find_youtube_link, fmt_length

log = logging.getLogger("core.discord")

API = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
INTENTS = (1 << 0) | (1 << 9) | (1 << 15)      # GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT
# Permissions the invite link asks for: View Channel, Send Messages, Manage Messages (only used to
# tidy the request channel), Embed Links, Read Message History, Add Reactions.
INVITE_PERMISSIONS = 1024 | 2048 | 8192 | 16384 | 65536 | 64
PERM_ADMIN = 1 << 3
PERM_MANAGE_GUILD = 1 << 5
USER_AGENT = "DiscordBot (https://github.com/sensokasucks/flavr-leftovers, 1.0)"

# Reactions on the request message for each queue change (VideoRequestQueue listener names).
STATUS_EMOJI = {"added": "⏳", "approved": "✅", "denied": "❌", "playing": "▶️", "played": "🏁",
                "skipped": "⏭️", "failed": "⚠️"}

DEFAULTS: Dict[str, Any] = {
    "enabled": False,           # log the bot in (Setup > Discord > Connect)
    "token": "",                # the bot's token (Bot tab of the developer portal); never sent to the dashboard
    "guild_id": "",             # the server the channels below belong to
    "request_channel_id": "",   # where viewers post YouTube links
    "mod_channel_id": "",       # where Approve / Deny / Play now buttons are posted ("" = none)
    "approver_role_ids": [],    # roles that may press the buttons (admins always may)
    "requester_role_ids": [],   # roles that may request ([] = everyone)
    "clean_channel": False,     # delete messages without a YouTube link in the request channel
}

# Close codes after which retrying is pointless until the streamer changes something.
FATAL_CLOSE = {
    4004: "Discord refused the bot token. Copy a fresh one from the Bot tab and save it.",
    4013: "Discord refused the bot's settings (invalid intents). Update Stream Core.",
    4014: "Turn on Message Content Intent: developer portal > your app > Bot > Privileged Gateway Intents, then press Connect.",
}


def read_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict((config or {}).get("discord") or {})
    out = copy.deepcopy(DEFAULTS)
    for key in DEFAULTS:
        if key in raw and raw[key] is not None:
            out[key] = raw[key]
    out["enabled"] = bool(out["enabled"])
    out["clean_channel"] = bool(out["clean_channel"])
    out["token"] = str(out["token"] or "").strip()
    for key in ("guild_id", "request_channel_id", "mod_channel_id"):
        out[key] = str(out[key] or "").strip()
    for key in ("approver_role_ids", "requester_role_ids"):
        out[key] = [str(r) for r in (out[key] or []) if str(r).strip()][:50]
    return out


def public_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Settings for the dashboard: the token itself never leaves Core."""
    out = copy.deepcopy(settings)
    out["token_set"] = bool(out.pop("token", ""))
    return out


class DiscordBot:
    """One bot connection (see the module notes). start() / stop() from main.py and the routes."""

    def __init__(self, get_config: Callable[[], Dict[str, Any]], queue: VideoRequestQueue,
                 note: Optional[Callable[[str, str], None]] = None,
                 http: Optional[httpx.AsyncClient] = None) -> None:
        # get_config: the live config, queue: the video request queue (we listen to its changes),
        # note: a Stream events line, http: tests pass a client with a fake transport
        self._get_config = get_config
        self.queue = queue
        self._note = note or (lambda text, kind: None)
        self._http = http
        self._task: Optional[asyncio.Task] = None
        self._hb_task: Optional[asyncio.Task] = None
        self._ws = None
        self._seq: Optional[int] = None
        self._acked = True
        self.status: Dict[str, Any] = {"state": "off", "text": "Not connected.", "since": time.time()}
        self.user: Dict[str, Any] = {}          # the bot's own user (READY), its id is the app id
        self.guilds: Dict[str, str] = {}        # server id -> name (READY / GUILD_CREATE)
        queue.add_listener(self._on_queue_change)

    # ── settings / status ──
    @property
    def settings(self) -> Dict[str, Any]:
        return read_settings(self._get_config() or {})

    def _set_status(self, state: str, text: str) -> None:
        if self.status.get("state") != state or self.status.get("text") != text:
            self.status = {"state": state, "text": text, "since": time.time()}
            if state in ("error", "online"):
                self._note(f"Discord: {text}", "system" if state == "online" else "error")

    def public_status(self) -> Dict[str, Any]:
        app_id = str(self.user.get("id") or "")
        invite = (f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot&permissions={INVITE_PERMISSIONS}"
                  if app_id else "")
        return {**self.status, "bot_name": self.user.get("username", ""), "app_id": app_id, "invite": invite,
                "guilds": [{"id": k, "name": v} for k, v in self.guilds.items()]}

    # ── start / stop ──
    def start(self) -> None:
        """Connect when discord.enabled is on and a token is set (safe to call again)."""
        s = self.settings
        if not s["enabled"]:
            self._set_status("off", "Switched off.")
            return
        if not s["token"]:
            self._set_status("error", "Paste the bot token first.")
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="discord-gateway")

    async def stop(self) -> None:
        for t in (self._hb_task, self._task):
            if t is not None and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = self._hb_task = None
        self._set_status("off", "Not connected.")

    async def restart(self) -> None:
        await self.stop()
        self.start()

    # ── REST ──
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=10.0)
        return self._http

    async def api(self, method: str, path: str, body: Any = None) -> Any:
        """One REST call as the bot. Returns the JSON answer ({} for 204). Waits out one 429
        (rate limit) and tries once more; raises httpx.HTTPStatusError on other failures."""
        headers = {"Authorization": f"Bot {self.settings['token']}", "User-Agent": USER_AGENT}
        for attempt in range(2):
            r = await self._client().request(method, API + path, headers=headers,
                                             json=body if body is not None else None)
            if r.status_code == 429 and attempt == 0:
                try:
                    wait = float(r.json().get("retry_after", 1.0))
                except ValueError:
                    wait = 1.0
                await asyncio.sleep(min(wait, 10.0))
                continue
            r.raise_for_status()
            return r.json() if r.content else {}
        return {}

    async def _safe(self, method: str, path: str, body: Any = None) -> Any:
        """api() that logs instead of raising (reactions, edits: never worth stopping for)."""
        try:
            return await self.api(method, path, body)
        except httpx.HTTPError as e:
            log.warning("Discord %s %s failed: %s", method, path, e)
            return None

    async def channels(self, guild_id: str) -> List[Dict[str, str]]:
        """Text channels of a server (Setup page dropdowns), in Discord's order."""
        rows = await self.api("GET", f"/guilds/{guild_id}/channels")
        text = [c for c in rows if c.get("type") in (0, 5)]
        text.sort(key=lambda c: c.get("position", 0))
        return [{"id": str(c["id"]), "name": str(c.get("name", ""))} for c in text]

    async def roles(self, guild_id: str) -> List[Dict[str, str]]:
        rows = await self.api("GET", f"/guilds/{guild_id}/roles")
        rows = [r for r in rows if r.get("name") != "@everyone" and not (r.get("tags") or {}).get("bot_id")]
        rows.sort(key=lambda r: -int(r.get("position", 0)))
        return [{"id": str(r["id"]), "name": str(r.get("name", ""))} for r in rows]

    async def send(self, channel_id: str, content: str, reply_to: str = "", components: Optional[list] = None) -> Optional[dict]:
        """Post a message (no pings: allowed_mentions is empty, so @everyone in a title is harmless)."""
        body: Dict[str, Any] = {"content": content[:1900], "allowed_mentions": {"parse": []}}
        if reply_to:
            body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
        if components is not None:
            body["components"] = components
        return await self._safe("POST", f"/channels/{channel_id}/messages", body)

    async def react(self, channel_id: str, message_id: str, emoji: str, on: bool = True) -> None:
        path = f"/channels/{channel_id}/messages/{message_id}/reactions/{quote(emoji)}/@me"
        await self._safe("PUT" if on else "DELETE", path)

    # ── gateway ──
    async def _run(self) -> None:
        """Keep the gateway connection up; reconnect after 2 s growing to 60 s."""
        backoff = 2.0
        while True:
            self._set_status("connecting", "Connecting to Discord...")
            try:
                async with websockets.connect(GATEWAY, max_size=2 ** 23, ping_interval=None) as ws:
                    self._ws = ws
                    async for raw in ws:
                        if await self._handle(json.loads(raw)):
                            backoff = 2.0
            except ConnectionClosed as e:
                code = getattr(e.rcvd, "code", None) if getattr(e, "rcvd", None) else None
                if code in FATAL_CLOSE:
                    self._set_status("error", FATAL_CLOSE[code])
                    log.warning("Discord closed the connection (%s): %s", code, FATAL_CLOSE[code])
                    return
                log.info("Discord connection closed (%s); reconnecting in %.0f s", code, backoff)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - network trouble: wait and try again
                log.warning("Discord connection failed: %s; reconnecting in %.0f s", e, backoff)
            finally:
                self._ws = None
                if self._hb_task is not None:
                    self._hb_task.cancel()
                    self._hb_task = None
            self._set_status("connecting", f"Lost the connection; trying again in {int(backoff)} s.")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _heartbeat(self, interval_ms: float) -> None:
        """op 1 every interval (the first after a random part of it, as Discord asks). A missing
        ACK means a dead connection: close it, _run reconnects."""
        await asyncio.sleep(interval_ms / 1000.0 * random.random())
        while self._ws is not None:
            if not self._acked:
                await self._ws.close(code=4000)
                return
            self._acked = False
            await self._ws.send(json.dumps({"op": 1, "d": self._seq}))
            await asyncio.sleep(interval_ms / 1000.0)

    async def _handle(self, msg: Dict[str, Any]) -> bool:
        """One gateway message. Returns True once logged in (READY), to reset the backoff."""
        op = msg.get("op")
        if msg.get("s") is not None:
            self._seq = msg["s"]
        if op == 10:            # HELLO
            self._acked = True
            self._hb_task = asyncio.create_task(self._heartbeat(float(msg["d"]["heartbeat_interval"])))
            await self._ws.send(json.dumps({"op": 2, "d": {
                "token": self.settings["token"], "intents": INTENTS,
                "properties": {"os": "windows", "browser": "fridge-stream-core", "device": "fridge-stream-core"}}}))
        elif op == 11:          # HEARTBEAT_ACK
            self._acked = True
        elif op == 1:           # Discord asks for a heartbeat now
            await self._ws.send(json.dumps({"op": 1, "d": self._seq}))
        elif op in (7, 9):      # reconnect / invalid session: start over with a fresh IDENTIFY
            await self._ws.close(code=4000)
        elif op == 0:
            return await self._dispatch(str(msg.get("t") or ""), msg.get("d") or {})
        return False

    async def _dispatch(self, name: str, d: Dict[str, Any]) -> bool:
        if name == "READY":
            self.user = d.get("user") or {}
            for g in d.get("guilds") or []:
                self.guilds.setdefault(str(g.get("id")), str(g.get("name") or g.get("id")))
            self._set_status("online", f"Online as {self.user.get('username', 'the bot')}.")
            return True
        if name == "GUILD_CREATE":
            self.guilds[str(d.get("id"))] = str(d.get("name") or d.get("id"))
        elif name == "GUILD_DELETE":
            self.guilds.pop(str(d.get("id")), None)
        elif name == "MESSAGE_CREATE":
            try:
                await self.on_message(d)
            except Exception:  # noqa: BLE001
                log.exception("Discord message handling failed")
        elif name == "INTERACTION_CREATE":
            try:
                await self.on_interaction(d)
            except Exception:  # noqa: BLE001
                log.exception("Discord button handling failed")
        return False

    # ── requests ──
    @staticmethod
    def _name(d: Dict[str, Any]) -> str:
        """The name people see: the server nickname, else the display name, else the username."""
        member = d.get("member") or {}
        author = d.get("author") or member.get("user") or d.get("user") or {}
        return str(member.get("nick") or author.get("global_name") or author.get("username") or "someone")

    async def on_message(self, d: Dict[str, Any]) -> None:
        """MESSAGE_CREATE: a YouTube link in the request channel becomes a request."""
        s = self.settings
        author = d.get("author") or {}
        if author.get("bot") or not s["request_channel_id"] or str(d.get("channel_id")) != s["request_channel_id"]:
            return
        channel, mid = str(d["channel_id"]), str(d["id"])
        link = find_youtube_link(str(d.get("content") or ""))
        if not link:
            if s["clean_channel"]:
                await self._safe("DELETE", f"/channels/{channel}/messages/{mid}")
            return
        roles = [str(r) for r in ((d.get("member") or {}).get("roles") or [])]
        if s["requester_role_ids"] and not set(roles) & set(s["requester_role_ids"]):
            await self._refuse(channel, mid, "Requests are for members with a certain role here.")
            return
        result = await self.queue.submit(link, by=self._name(d), source="discord", by_id=str(author.get("id", "")),
                                         ref={"channel_id": channel, "message_id": mid})
        if not result["ok"]:
            await self._refuse(channel, mid, result["reason"])

    async def _refuse(self, channel: str, mid: str, reason: str) -> None:
        await self.react(channel, mid, "❌")
        if self.queue.settings["bot_replies"]:
            await self.send(channel, reason, reply_to=mid)

    def _mod_text(self, item: Dict[str, Any]) -> str:
        line = f"**{item['title']}** ({fmt_length(item.get('length'))}) requested by **{item['by']}**\n<{item['url']}>"
        st = item["status"]
        if st == "pending":
            return "🎬 New video request: " + line
        who = f" by {item['decided_by']}" if item.get("decided_by") else ""
        tail = {"approved": f"✅ Approved{who}", "denied": f"❌ Denied{who}" + (f": {item['reason']}" if item.get("reason") else ""),
                "playing": "▶️ Playing now", "played": "🏁 Played", "skipped": "⏭️ Skipped",
                "failed": "⚠️ Couldn't play" + (f": {item['reason']}" if item.get("reason") else "")}.get(st, st)
        return f"{tail}: {line}"

    @staticmethod
    def _buttons(item: Dict[str, Any]) -> list:
        """Approve / Deny / Play now while it waits; only Play now once approved; none after."""
        rid = item["id"]
        btn = lambda label, style, act: {"type": 2, "style": style, "label": label, "custom_id": f"vr:{act}:{rid}"}  # noqa: E731
        if item["status"] == "pending":
            row = [btn("Approve", 3, "approve"), btn("Deny", 4, "deny"), btn("Play now", 1, "play")]
        elif item["status"] == "approved":
            row = [btn("Play now", 1, "play"), btn("Deny", 4, "deny")]
        else:
            return []
        return [{"type": 1, "components": row}]

    async def _on_queue_change(self, item: Dict[str, Any], change: str) -> None:
        """VideoRequestQueue listener: swap reactions on the request message, post / edit the
        mod-channel message, and the optional replies and "Now playing" post."""
        if self.status.get("state") != "online":
            return
        s, vs = self.settings, self.queue.settings
        ref = item.setdefault("ref", {})
        channel, mid = ref.get("channel_id"), ref.get("message_id")
        if item.get("source") == "discord" and channel and mid and change in STATUS_EMOJI:
            old = ref.get("emoji")
            if old and old != STATUS_EMOJI[change]:
                await self.react(channel, mid, old, on=False)
            await self.react(channel, mid, STATUS_EMOJI[change])
            ref["emoji"] = STATUS_EMOJI[change]
            if vs["bot_replies"] and change == "denied":
                await self.send(channel, "Not this time" + (f": {item['reason']}" if item.get("reason") else "."), reply_to=mid)
        if change == "playing" and vs["now_playing_post"] and s["request_channel_id"]:
            await self.send(s["request_channel_id"], f"▶️ Now playing: **{item['title']}** (requested by {item['by']})")
        if s["mod_channel_id"]:
            if change == "added":
                msg = await self.send(s["mod_channel_id"], self._mod_text(item), components=self._buttons(item))
                if msg:
                    ref["mod_channel_id"], ref["mod_message_id"] = s["mod_channel_id"], str(msg.get("id", ""))
            elif ref.get("mod_message_id"):
                await self._safe("PATCH", f"/channels/{ref['mod_channel_id']}/messages/{ref['mod_message_id']}",
                                 {"content": self._mod_text(item)[:1900], "components": self._buttons(item),
                                  "allowed_mentions": {"parse": []}})

    def _may_decide(self, d: Dict[str, Any]) -> bool:
        member = d.get("member") or {}
        try:
            perms = int(member.get("permissions") or 0)
        except ValueError:
            perms = 0
        if perms & (PERM_ADMIN | PERM_MANAGE_GUILD):
            return True
        roles = {str(r) for r in member.get("roles") or []}
        return bool(roles & set(self.settings["approver_role_ids"]))

    async def on_interaction(self, d: Dict[str, Any]) -> None:
        """INTERACTION_CREATE: a press on one of our mod-channel buttons (custom_id vr:<act>:<id>)."""
        if d.get("type") != 3:
            return
        cid = str((d.get("data") or {}).get("custom_id") or "")
        parts = cid.split(":")
        if len(parts) != 3 or parts[0] != "vr" or not parts[2].isdigit():
            return
        act, rid = parts[1], int(parts[2])
        answer = f"/interactions/{d['id']}/{d['token']}/callback"
        if not self._may_decide(d):
            await self._safe("POST", answer, {"type": 4, "data": {"content": "Only the streamer's mods can decide on requests.", "flags": 64}})
            return
        who = self._name(d)
        if act == "approve":
            res = self.queue.approve(rid, by=who)
        elif act == "deny":
            res = self.queue.deny(rid, by=who)
        elif act == "play":
            res = await self.queue.play(rid, by=who)
        else:
            return
        item = self.queue.get(rid)
        if res.get("ok") and item is not None:
            # type 7 = edit the message the button is on (the listener's PATCH may also land; same text)
            await self._safe("POST", answer, {"type": 7, "data": {"content": self._mod_text(item)[:1900],
                                                                   "components": self._buttons(item),
                                                                   "allowed_mentions": {"parse": []}}})
        else:
            await self._safe("POST", answer, {"type": 4, "data": {"content": res.get("reason") or "That didn't work.", "flags": 64}})
