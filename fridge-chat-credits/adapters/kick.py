"""Kick.com chat via the public Pusher socket. No viewer polling."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from adapters.base import BaseAdapter
from core.models import ChatEvent, ChatUser, Platform

log = logging.getLogger("adapters.kick")

PUSHER_URL = (
    "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679"
    "?protocol=7&client=js&version=8.4.0-rc2&flash=false"
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://kick.com/",
    "Origin": "https://kick.com",
}


class KickAdapter(BaseAdapter):
    platform = Platform.KICK

    def __init__(self, config: dict, bus):
        super().__init__(config, bus)
        kick_cfg = config.get("kick", {})
        self.slug = (kick_cfg.get("channel_slug") or "").strip().lstrip("@")
        raw_id = kick_cfg.get("chatroom_id")
        self.chatroom_id: Optional[int] = (
            int(raw_id) if raw_id not in (None, "", 0, "0") else None
        )
        self._ws_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not self.slug or self.slug.startswith("YOUR_"):
            log.warning("Kick channel_slug not set — adapter off")
            return
        if not self.chatroom_id:
            self.chatroom_id = await self._resolve_chatroom_id(self.slug)
        if not self.chatroom_id:
            log.error(
                "Could not resolve Kick chatroom for '%s'. "
                "Set kick.chatroom_id in config.yaml "
                "(open https://kick.com/api/v2/channels/%s and copy chatroom.id)",
                self.slug,
                self.slug,
            )
            return
        self._running = True
        self._stop.clear()
        self._ws_task = asyncio.create_task(self._ws_loop(), name="kick-ws")
        log.info("Kick listening on '%s' (chatroom %s)", self.slug, self.chatroom_id)

    async def stop(self) -> None:
        self._running = False
        self._stop.set()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

    async def _resolve_chatroom_id(self, slug: str) -> Optional[int]:
        urls = [
            f"https://kick.com/api/v2/channels/{slug}",
            f"https://kick.com/api/v1/channels/{slug}",
        ]
        async with httpx.AsyncClient(
            timeout=15.0, headers=BROWSER_HEADERS, follow_redirects=True
        ) as client:
            for url in urls:
                try:
                    r = await client.get(url)
                    if r.status_code in (403, 404):
                        log.warning("Kick %s → %s", r.status_code, url)
                        continue
                    r.raise_for_status()
                    data = r.json()
                    chatroom = data.get("chatroom") or {}
                    cid = chatroom.get("id") or data.get("chatroom_id")
                    if cid:
                        return int(cid)
                    nested = (data.get("data") or {}).get("chatroom") or {}
                    if nested.get("id"):
                        return int(nested["id"])
                except Exception as e:
                    log.warning("Kick lookup failed %s: %s", url, e)
        return None

    async def _ws_loop(self) -> None:
        backoff = 3.0
        while self._running:
            try:
                async with websockets.connect(
                    PUSHER_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2**22,
                ) as ws:
                    log.info("Kick Pusher connected")
                    backoff = 3.0
                    await ws.send(json.dumps({
                        "event": "pusher:subscribe",
                        "data": {"auth": "", "channel": f"chatrooms.{self.chatroom_id}.v2"},
                    }))
                    await ws.send(json.dumps({
                        "event": "pusher:subscribe",
                        "data": {"auth": "", "channel": f"chatrooms.{self.chatroom_id}"},
                    }))
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_raw(raw)
            except ConnectionClosed as e:
                log.warning("Kick WS closed: %s — retry in %.1fs", e, backoff)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("Kick WS error: %s — retry in %.1fs", e, backoff)
            if not self._running:
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 1.5, 30.0)

    async def _handle_raw(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8", "ignore"))
        except json.JSONDecodeError:
            return
        event_name = msg.get("event", "")
        if event_name not in (
            "App\\Events\\ChatMessageEvent",
            "App\\Events\\ChatMessageSentEvent",
        ):
            return
        data = msg.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return
        if isinstance(data, dict):
            await self._on_chat_message(data)

    async def _on_chat_message(self, data: dict[str, Any]) -> None:
        sender = data.get("sender") or {}
        username = (
            sender.get("username")
            or sender.get("slug")
            or (sender.get("identity") or {}).get("username")
            or ""
        )
        content = (data.get("content") or data.get("message") or "").strip()
        if not username or not content:
            return
        identity = sender.get("identity") or {}
        badges = []
        for b in identity.get("badges") or sender.get("badges") or []:
            if isinstance(b, dict):
                badges.append(str(b.get("type") or b.get("name") or b))
            else:
                badges.append(str(b))
        low = [b.lower() for b in badges]
        user = ChatUser(
            platform=Platform.KICK,
            id=str(sender.get("id") or username),
            username=username,
            display_name=sender.get("username") or username,
            is_mod=any(b in ("moderator", "mod", "broadcaster") for b in low),
            is_vip=any("vip" in b for b in low),
            is_subscriber=any("subscriber" in b or b == "sub" for b in low),
            badges=badges,
            color=identity.get("color"),
        )
        await self._emit(ChatEvent(
            platform=Platform.KICK,
            user=user,
            message=content,
            message_id=str(data.get("id") or ""),
        ))
