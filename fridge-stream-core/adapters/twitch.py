"""
Twitch chat adapter (read-only).

Uses anonymous IRC (justinfanXXXXX) — no OAuth required to listen. With the streamer's
own Twitch sign-in it also opens EventSub (adapters/twitch_eventsub.py) for the paid events
IRC doesn't carry: power-ups with their bits, celebrations, charity, Hype Trains.

Settings come from the ``twitch:`` block of config.yaml (``channel``, ``avatars``,
``third_party_emotes``, ``paid_events``). main.py starts it when ``twitch.enabled`` is true.
With Connect Twitch (scope ``user:write:chat``) ``send_message`` posts Core's replies into
the channel through Helix "Send Chat Message" (main.py ``_post_reply``); without it main.py
shows them on the overlay instead.
"""

from __future__ import annotations

import asyncio
import codecs
import logging
import random
import re
from typing import Any, Optional

from adapters.base import BaseAdapter
from adapters.twitch_auth import get_auth
from adapters.twitch_avatars import TwitchAvatars
from adapters.twitch_emotes import ThirdPartyEmotes, parse_twitch_emotes, strip_action
from adapters.twitch_eventsub import EventSubClient
from adapters.twitch_eventsub import _http_httpx as _helix_json
from core.event_bus import EventBus
from core.metrics import MetricsAggregator
from core.models import ChatEvent, ChatUser, Platform
from core.platform_links import twitch_channel

log = logging.getLogger("adapters.twitch")

# Helix (Twitch's official API) addresses used for posting replies (TwitchAdapter.send_message)
HELIX_CHAT_URL = "https://api.twitch.tv/helix/chat/messages"
HELIX_USERS_URL = "https://api.twitch.tv/helix/users"
TWITCH_CHAT_MAX_CHARS = 500     # Twitch refuses longer chat messages
WRITE_SCOPE = "user:write:chat"

HOST = "irc.chat.twitch.tv"
PORT = 6667     # plain-text IRC; chat is public, and the anonymous login sends no secret
# A dead link (Wi-Fi blip, router reset, PC asleep) sends no FIN, so a read with no timeout
# waits forever. After IDLE_PING seconds of silence we PING Twitch ourselves; no answer
# within PONG_TIMEOUT means the link is dead and we reconnect.
IDLE_PING = 60.0
PONG_TIMEOUT = 20.0

# Regexes for the IRC lines Core reads (tags are the IRCv3 "@k=v;k=v" prefix)
PRIVMSG_RE = re.compile(
    r"^(?:@(?P<tags>[^ ]+) )?:(?P<nick>[^!]+)![^ ]+ PRIVMSG #(?P<chan>[^ ]+) :(?P<msg>.*)$"
)
ROOMSTATE_RE = re.compile(r"^@(?P<tags>[^ ]+) :tmi\.twitch\.tv ROOMSTATE #")
# a mod deleted one message / timed out or banned someone (no user = /clear)
CLEARMSG_RE = re.compile(r"^@(?P<tags>[^ ]+) :tmi\.twitch\.tv CLEARMSG #[^ ]+(?: :(?P<msg>.*))?$")
CLEARCHAT_RE = re.compile(r"^(?:@(?P<tags>[^ ]+) )?:tmi\.twitch\.tv CLEARCHAT #[^ ]+(?: :(?P<user>[^ ]+))?$")
USERNOTICE_RE = re.compile(
    r"^@(?P<tags>[^ ]+) :tmi\.twitch\.tv USERNOTICE #(?P<chan>[^ ]+)(?: :(?P<msg>.*))?$"
)


class IrcLineReader:
    """Bytes off the socket → complete IRC lines.

    Decodes with an incremental UTF-8 decoder, so an emoji (or any multi-byte character)
    split across two reads is kept whole instead of being dropped.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._buf = ""

    def feed(self, data: bytes) -> list[str]:
        """Add bytes; return the lines completed so far (an unfinished line waits for more)."""
        self._buf += self._decoder.decode(data)
        if "\r\n" not in self._buf:
            return []
        *lines, self._buf = self._buf.split("\r\n")
        return lines


def _parse_tags(raw: str) -> dict[str, str]:
    """IRCv3 tag string ``a=1;b=x\\sy`` -> {"a": "1", "b": "x y"}."""
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = _untag(v)
        else:
            out[part] = ""
    return out


def _untag(v: str) -> str:
    """IRCv3 tag value escapes: \\s space, \\: semicolon, \\\\ backslash, \\r, \\n."""
    out = []
    i = 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            n = v[i + 1]
            out.append({"s": " ", ":": ";", "\\": "\\", "r": "\r", "n": "\n"}.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def twitch_reply_to(tags: dict[str, str]) -> Optional[dict]:
    """Twitch's reply button adds reply-parent-* tags. Returns ChatEvent.reply_to, or None."""
    parent_id = tags.get("reply-parent-msg-id") or ""
    who = tags.get("reply-parent-display-name") or tags.get("reply-parent-user-login") or ""
    if not parent_id or not who:
        return None
    return {"user": who, "message": (tags.get("reply-parent-msg-body") or "")[:200], "message_id": parent_id}


# PRIVMSG msg-id values for messages that were bought: "Highlight My Message" with channel
# points, and the bits power-ups (Gigantify an Emote, Message Effects; see POWERUP_KINDS)
HIGHLIGHT_KINDS = {
    "highlighted-message": "highlighted",
    "gigantified-emote-message": "gigantified",
    "animated-message": "animated",
}


# bits power-ups: they go on the Paid list (Twitch's chat doesn't say how many bits).
# main.py reads this; when EventSub delivers power-ups with bits it skips these chat lines.
POWERUP_KINDS = {"gigantified", "animated"}


def twitch_highlight(tags: dict[str, str]) -> Optional[str]:
    """Channel-point message styles ("Highlight My Message" etc.) → ChatEvent.highlight."""
    return HIGHLIGHT_KINDS.get(tags.get("msg-id") or "")


def strip_reply_mention(msg: str, reply_to: Optional[dict]) -> str:
    """A Twitch reply starts with "@Name ": drop it, the "Replying to" line says who."""
    if not reply_to or not msg.startswith("@"):
        return msg
    head, _, rest = msg.partition(" ")
    if head[1:].lower() == str(reply_to.get("user", "")).lower():
        return rest.strip() or msg
    return msg


def shift_emotes(emotes: list[dict], original: str, stripped: str) -> list[dict]:
    """Emote positions point into the message as sent. Once the "@Name " reply prefix is
    dropped they must move left by its length, or the picture lands mid-word."""
    if stripped == original:
        return emotes
    cut = original.find(stripped, original.find(" ") + 1)
    if cut < 0:
        return []
    out = []
    for e in emotes:
        start, end = e.get("start", 0) - cut, e.get("end", 0) - cut
        if start >= 0 and end < len(stripped):
            out.append({**e, "start": start, "end": end})
    return out


def _int(raw: Any, default: int = 1) -> int:
    """Tag value as an int of at least 1, or ``default`` when it isn't a number."""
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def usernotice_alert(tags: dict[str, str], msg: str = "") -> Optional[dict[str, Any]]:
    """USERNOTICE tags → `_emit_alert` kwargs, or None for notices that aren't subs.

    A gift bomb arrives as one `submysterygift` (the count) followed by one `subgift`
    per recipient carrying `msg-param-community-gift-id`; only the bomb alerts.
    """
    kind = tags.get("msg-id") or ""
    who = {
        "username": tags.get("login") or "",
        "display_name": tags.get("display-name") or tags.get("login") or "",
        "user_id": tags.get("user-id") or "",
    }
    if kind in ("sub", "primepaidupgrade", "giftpaidupgrade", "anongiftpaidupgrade"):
        return {"kind": "subscribe", **who, "message": msg}
    if kind == "resub":
        months = _int(tags.get("msg-param-cumulative-months") or tags.get("msg-param-months"))
        return {"kind": "resub", **who, "months": months, "message": msg}
    if kind in ("subgift", "anonsubgift"):
        if tags.get("msg-param-community-gift-id"):
            return None
        return {"kind": "gift", **who, "qty": 1}
    if kind in ("submysterygift", "anonsubmysterygift"):
        return {"kind": "gift", **who, "qty": _int(tags.get("msg-param-mass-gift-count"))}
    if kind == "raid":
        # the raider is msg-param-login / -displayName; login / display-name are the same person
        raider = tags.get("msg-param-login") or who["username"]
        return {
            "kind": "raid",
            "username": raider,
            "display_name": tags.get("msg-param-displayName") or who["display_name"] or raider,
            "user_id": who["user_id"],
            "viewers": _int(tags.get("msg-param-viewerCount"), 0),
        }
    return None


def cheer_bits(tags: dict[str, str]) -> int:
    """Bits cheered in a chat message (the `bits` tag), 0 for a plain message."""
    try:
        return max(0, int(tags.get("bits") or 0))
    except (TypeError, ValueError):
        return 0


class TwitchAdapter(BaseAdapter):
    """Listens to one channel's chat over anonymous IRC and turns lines into ChatEvents / alerts."""

    platform = Platform.TWITCH

    def __init__(self, config: dict, bus: EventBus, metrics: MetricsAggregator):
        super().__init__(config, bus, metrics)
        cfg = config.get("twitch", {})
        self.channel = twitch_channel(cfg.get("channel") or "")
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._writer: Optional[asyncio.StreamWriter] = None
        # BTTV / FFZ / 7TV emotes, loaded once the channel's room-id is known
        self.emotes3p = ThirdPartyEmotes(bool(cfg.get("third_party_emotes", True)))
        # chatter pictures through Helix; needs the streamer's Twitch sign-in (or an own app with a secret)
        self.auth = get_auth(config)
        self.avatars = TwitchAvatars(bool(cfg.get("avatars", True)), auth=self.auth)
        # bits power-ups / celebrations / charity / Hype Trains (needs the streamer's sign-in)
        self.paid_events = bool(cfg.get("paid_events", True))
        self.eventsub: Optional[EventSubClient] = None
        # Posting replies (send_message): Helix JSON requests, swapped for a fake in tests;
        # the channel's numeric id, looked up once when the sign-in isn't the channel itself
        self._helix = _helix_json
        self._broadcaster_id = ""

    def can_send(self) -> tuple[bool, str]:
        """(can Core post into this Twitch chat now, why not). Asked by main.py ``_post_reply``.

        Needs Connect Twitch with ``user:write:chat`` (in twitch_auth.CHAT_SCOPES; a sign-in
        from before that scope existed has to press Reconnect). The reply is posted as the
        signed-in account, normally the channel owner.
        """
        if not self.channel:
            return False, "no Twitch channel set"
        if not self.auth.connected:
            return False, "Twitch is not connected (Settings → Twitch → Connect Twitch)"
        if WRITE_SCOPE not in (self.auth.status().get("scopes") or []):
            return False, "the Twitch sign-in can't post in chat; press Reconnect on the Twitch card"
        return True, ""

    async def _channel_id(self, token: str) -> str:
        """The channel's numeric Twitch id for Helix: the signed-in account's own when it is the
        channel (the usual case), else looked up once by name (GET /helix/users?login=)."""
        if self.auth.login and self.auth.login.lower() == self.channel:
            return self.auth.user_id
        if self._broadcaster_id:
            return self._broadcaster_id
        status, body = await self._helix(
            "GET", f"{HELIX_USERS_URL}?login={self.channel}", None,
            {"Client-Id": self.auth.client_id, "Authorization": f"Bearer {token}"})
        rows = body.get("data") if isinstance(body, dict) else None
        if status == 200 and rows:
            self._broadcaster_id = str(rows[0].get("id") or "")
        return self._broadcaster_id

    async def send_message(self, text: str, reply_to_message_id: str = "",
                           reply_to_user: str = "") -> bool:
        """Post ``text`` into the Twitch chat with Helix "Send Chat Message"; True when Twitch
        says it was sent.

        Called by main.py ``_post_reply`` after ``can_send``. ``reply_to_message_id`` is the IRC
        ``id`` tag of the line being answered (ChatEvent.message_id), so Twitch shows a threaded
        reply. Twitch may still drop a message (AutoMod, a blocked word, followers-only ...):
        it then answers ``is_sent: false`` with a ``drop_reason``, and this returns False so the
        overlay shows it instead. A 401 refreshes the sign-in once and tries again.
        """
        text = (text or "").strip()
        if not text:
            return False
        if len(text) > TWITCH_CHAT_MAX_CHARS:
            text = text[:TWITCH_CHAT_MAX_CHARS - 1] + "…"
        why = "Twitch refused the message"
        # noted before posting: IRC can deliver the echo before Helix answers
        self._remember_sent(text)
        for attempt in (1, 2):
            token = await self.auth.token()
            if not token or not self.auth.connected:
                why = "Twitch is not connected"
                break
            try:
                broadcaster = await self._channel_id(token)
            except Exception as e:
                why = f"could not reach Twitch: {e}"
                break
            if not broadcaster:
                why = f"could not find the Twitch channel {self.channel}"
                break
            body = {"broadcaster_id": broadcaster, "sender_id": self.auth.user_id, "message": text}
            if reply_to_message_id:
                body["reply_parent_message_id"] = str(reply_to_message_id)
            try:
                status, answer = await self._helix(
                    "POST", HELIX_CHAT_URL, body,
                    {"Client-Id": self.auth.client_id, "Authorization": f"Bearer {token}"})
            except Exception as e:
                why = f"could not reach Twitch: {e}"
                break
            if status == 401 and attempt == 1:
                self.auth.invalidate()
                continue
            rows = answer.get("data") if isinstance(answer, dict) else None
            if status == 200 and rows:
                row = rows[0] if isinstance(rows[0], dict) else {}
                if row.get("is_sent"):
                    self.last_send_error = ""
                    return True
                drop = row.get("drop_reason") or {}
                why = f"Twitch dropped the message: {drop.get('message') or drop.get('code') or 'no reason given'}"
            else:
                msg = answer.get("message") if isinstance(answer, dict) else ""
                why = f"Twitch refused the message: {msg or f'HTTP {status}'}"
                if status == 403:
                    why += " (press Reconnect on the Twitch card so Core may post in chat)"
            break
        self._forget_sent(text)
        self.last_send_error = why
        log.info("Twitch reply not posted, showing it on the overlay instead: %s", why)
        return False

    async def start(self) -> None:
        """Start the IRC loop (and EventSub) in the background; does nothing without a channel."""
        if not self.channel or self.channel.startswith("your_"):
            log.warning("Twitch channel not set — adapter disabled")
            self._set_stopped("No Twitch channel set. Type your channel name under Settings → Core + chat platforms.")
            return
        self._running = True
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="twitch-irc")
        log.info("Twitch IRC listening on #%s", self.channel)
        if self.paid_events:
            self.eventsub = EventSubClient(self.auth, self.channel, self._on_paid_event)
            self.eventsub.start()

    async def _on_paid_event(self, alert: dict) -> None:
        """EventSub callback: kwargs from twitch_eventsub's *_alert functions."""
        await self._emit_alert(**alert)

    async def stop(self) -> None:
        self._running = False
        self._set_stopped()
        self._stop.set()
        self.emotes3p.stop()
        self.avatars.stop()
        if self.eventsub is not None:
            await self.eventsub.stop()
            self.eventsub = None
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Twitch adapter stopped")

    async def _loop(self) -> None:
        """Connect, read until the link drops, wait (3 s growing to 30 s), repeat until stopped."""
        backoff = 3.0
        nick = f"justinfan{random.randint(10000, 99999)}"
        while self._running:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(HOST, PORT), timeout=20.0)
                self._writer = writer
                writer.write(
                    (
                        # tags = badges / ids / emotes; commands = CLEARCHAT, USERNOTICE, ROOMSTATE
                        "CAP REQ :twitch.tv/tags twitch.tv/commands\r\n"
                        f"NICK {nick}\r\n"
                        f"JOIN #{self.channel}\r\n"
                    ).encode("utf-8")
                )
                await writer.drain()
                log.info("Twitch IRC connected as %s on #%s", nick, self.channel)
                self._set_connected()
                backoff = 3.0
                await self._read_loop(reader, writer)
                if self._running:
                    raise ConnectionError("Twitch closed the chat connection")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                reason = str(e) or type(e).__name__
                if isinstance(e, (asyncio.TimeoutError, OSError)) and not str(e):
                    reason = "can't reach Twitch chat (network down?)"
                self._set_retrying(f"Twitch chat disconnected: {reason}. Retrying in {backoff:.0f} s.")
                log.warning("Twitch IRC error: %s — retry in %.1fs", reason, backoff)
            finally:
                if self._writer is not None:
                    try:
                        self._writer.close()
                    except Exception:
                        pass
                    self._writer = None
            if not self._running:
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 1.5, 30.0)

    async def _read_loop(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read lines until the socket closes; raise when the link goes silent."""
        lines = IrcLineReader()
        pinged = False
        while self._running:
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=PONG_TIMEOUT if pinged else IDLE_PING)
            except asyncio.TimeoutError:
                if pinged:
                    raise ConnectionError("no answer from Twitch for a while (connection went silent)")
                writer.write(b"PING :keepalive\r\n")
                await writer.drain()
                pinged = True
                continue
            if not data:
                return
            pinged = False  # anything at all means the link is alive
            for line in lines.feed(data):
                await self._on_line(writer, line)

    async def _on_line(self, writer: asyncio.StreamWriter, line: str) -> None:
        """Handle one IRC line: keepalive, room id, mod removals, sub / raid notices, chat."""
        if not line:
            return
        if line.startswith("PING"):
            writer.write(b"PONG :tmi.twitch.tv\r\n")
            await writer.drain()
            return
        if " PONG " in line[:40] or line.startswith("PONG"):
            return
        rs = ROOMSTATE_RE.match(line)
        if rs:
            self.emotes3p.set_room(_parse_tags(rs.group("tags")).get("room-id", ""))
            return
        cm = CLEARMSG_RE.match(line)
        if cm:
            tags = _parse_tags(cm.group("tags"))
            await self._emit_removed(message_id=tags.get("target-msg-id", ""))
            return
        cc = CLEARCHAT_RE.match(line)
        if cc:
            tags = _parse_tags(cc.group("tags") or "")
            who = (cc.group("user") or "").strip()
            if who:
                await self._emit_removed(user_id=tags.get("target-user-id", ""), username=who)
            else:
                await self._emit_removed(everything=True)
            return
        un = USERNOTICE_RE.match(line)
        if un:
            alert = usernotice_alert(_parse_tags(un.group("tags")), strip_action(un.group("msg") or ""))
            if alert:
                await self._emit_alert(**alert)
            return
        m = PRIVMSG_RE.match(line)
        if not m:
            return
        tags = _parse_tags(m.group("tags") or "")
        nick = m.group("nick")
        msg = strip_action(m.group("msg") or "")
        self.emotes3p.set_room(tags.get("room-id", ""))
        emotes = parse_twitch_emotes(tags.get("emotes", ""), msg)
        emotes = sorted(emotes + self.emotes3p.match(msg, emotes), key=lambda e: e["start"])
        display = tags.get("display-name") or nick
        reply_to = twitch_reply_to(tags)
        if reply_to:
            stripped = strip_reply_mention(msg, reply_to)
            emotes = shift_emotes(emotes, msg, stripped)
            msg = stripped
        badges = (tags.get("badges") or "").split(",")
        badge_names = [b.split("/")[0] for b in badges if b]
        user = ChatUser(
            platform=Platform.TWITCH,
            id=tags.get("user-id") or nick,
            username=nick,
            display_name=display,
            is_mod=tags.get("mod") == "1"
            or "moderator" in badge_names
            or "broadcaster" in badge_names,
            is_vip="vip" in badge_names,
            is_subscriber=tags.get("subscriber") == "1" or "subscriber" in badge_names,
            badges=badge_names,
            color=tags.get("color") or None,
        )
        pic = self.avatars.get(user.id)
        if pic:
            user.profile_image_url = pic
        uid, uname = user.id, user.username

        async def _found(url: str) -> None:
            await self.bus.publish_user_update(
                {"platform": "twitch", "id": uid, "username": uname, "profile_image_url": url}
            )

        # new chatter, or a saved link old enough to re-check (does nothing while it's fresh)
        self.avatars.request(uid, _found)
        log.debug("[Twitch] %s: %s", user.username, msg)
        bits = cheer_bits(tags)
        await self._emit(
            ChatEvent(
                platform=Platform.TWITCH,
                user=user,
                message=msg,
                message_id=tags.get("id"),
                emotes=emotes,
                # a cheer: Core fires the Bits alert from paid chat (like a Super Chat)
                paid_amount=float(bits) if bits else None,
                paid_currency="bits" if bits else None,
                is_paid=bits > 0,
                paid_kind="bits" if bits else None,
                reply_to=reply_to,
                highlight=twitch_highlight(tags),
            )
        )
