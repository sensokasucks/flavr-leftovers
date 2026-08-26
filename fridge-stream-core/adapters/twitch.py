"""Twitch chat via anonymous IRC (no OAuth required to listen)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from adapters.base import BaseAdapter
from core.models import ChatEvent, ChatUser, Platform
from core.metrics import MetricsAggregator

log = logging.getLogger("fridge.twitch")

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6667


class TwitchAdapter(BaseAdapter):
    platform = Platform.TWITCH

    def __init__(self, config=None, *, metrics=None, emit=None):
        super().__init__(config, metrics=metrics, emit=emit)
        self.channel = (config or {}).get("channel", "").lstrip("#").lower()

    async def run(self) -> None:
        if not self.channel:
            log.error("twitch.channel is empty")
            return
        nick = "justinfan%d" % (10000 + (hash(self.channel) % 80000))
        while not self._stopping:
            try:
                reader, writer = await asyncio.open_connection(IRC_HOST, IRC_PORT)
                def send(line: str) -> None:
                    writer.write((line + "\r\n").encode("utf-8"))
                send("PASS SCHMOOPIIE")
                send(f"NICK {nick}")
                send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                send(f"JOIN #{self.channel}")
                await writer.drain()
                log.info("Twitch IRC joined #%s as %s", self.channel, nick)
                while not self._stopping:
                    line = await reader.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if text.startswith("PING"):
                        send("PONG :tmi.twitch.tv")
                        await writer.drain()
                        continue
                    await self._handle(text)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Twitch IRC error: %s — reconnecting", exc)
                await asyncio.sleep(5)

    async def _handle(self, line: str) -> None:
        # Very small PRIVMSG parser with optional tags
        if "PRIVMSG" not in line:
            return
        tags = {}
        rest = line
        if line.startswith("@"):
            tag_part, rest = line[1:].split(" ", 1)
            for part in tag_part.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    tags[k] = v
        m = re.search(r":(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :(.*)$", rest)
        if not m:
            return
        username, message = m.group(1), m.group(2)
        badges_raw = tags.get("badges", "")
        badges = [b.split("/")[0] for b in badges_raw.split(",") if b]
        user = ChatUser(
            username=username,
            display_name=tags.get("display-name") or username,
            user_id=tags.get("user-id", ""),
            platform=Platform.TWITCH,
            is_mod=tags.get("mod") == "1" or "moderator" in badges,
            is_subscriber="subscriber" in badges,
            is_vip="vip" in badges,
            is_broadcaster="broadcaster" in badges,
            badges=badges,
            color=tags.get("color", ""),
        )
        event = ChatEvent(
            user=user,
            message=message,
            platform=Platform.TWITCH,
            message_id=tags.get("id", ""),
        )
        if self.metrics:
            self.metrics.record_message()
        await self._emit(event)
