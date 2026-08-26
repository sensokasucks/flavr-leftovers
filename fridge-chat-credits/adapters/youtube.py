"""YouTube Live Chat poller (Data API v3). Opt-in — needs an API key + live video id."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from adapters.base import BaseAdapter
from core.models import ChatEvent, ChatUser, Platform

log = logging.getLogger("adapters.youtube")

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHAT_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"


class YouTubeAdapter(BaseAdapter):
    platform = Platform.YOUTUBE

    def __init__(self, config: dict, bus):
        super().__init__(config, bus)
        cfg = config.get("youtube", {})
        self.api_key = (cfg.get("api_key") or "").strip()
        self.video_id = (cfg.get("video_id") or "").strip()
        self.live_chat_id = (cfg.get("live_chat_id") or "").strip()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._page_token = ""

    async def start(self) -> None:
        if not self.api_key or self.api_key.startswith("YOUR_"):
            log.warning("YouTube api_key not set — adapter off")
            return
        if not self.live_chat_id and not self.video_id:
            log.warning("YouTube needs video_id or live_chat_id — adapter off")
            return
        self._running = True
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="youtube-chat")
        log.info("YouTube poller starting")

    async def stop(self) -> None:
        self._running = False
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        interval = 5.0
        async with httpx.AsyncClient(timeout=20.0) as client:
            if not self.live_chat_id:
                self.live_chat_id = await self._resolve_chat_id(client)
                if not self.live_chat_id:
                    log.error("Could not resolve YouTube liveChatId for video %s", self.video_id)
                    return
            log.info("YouTube liveChatId=%s", self.live_chat_id)
            while self._running:
                try:
                    interval = await self._poll(client)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("YouTube poll error: %s", e)
                    interval = 8.0
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=max(2.0, interval))
                    break
                except asyncio.TimeoutError:
                    pass

    async def _resolve_chat_id(self, client: httpx.AsyncClient) -> str:
        r = await client.get(
            VIDEOS_URL,
            params={
                "part": "liveStreamingDetails",
                "id": self.video_id,
                "key": self.api_key,
            },
        )
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items:
            return ""
        details = items[0].get("liveStreamingDetails") or {}
        return details.get("activeLiveChatId") or ""

    async def _poll(self, client: httpx.AsyncClient) -> float:
        params = {
            "liveChatId": self.live_chat_id,
            "part": "snippet,authorDetails",
            "key": self.api_key,
            "maxResults": 200,
        }
        if self._page_token:
            params["pageToken"] = self._page_token
        r = await client.get(CHAT_URL, params=params)
        if r.status_code == 403:
            log.error("YouTube API 403 — check api_key / quota / liveChatId")
            return 15.0
        r.raise_for_status()
        data = r.json()
        self._page_token = data.get("nextPageToken") or ""
        interval_ms = int(data.get("pollingIntervalMillis") or 5000)
        for item in data.get("items") or []:
            await self._on_item(item)
        return max(2.0, interval_ms / 1000.0)

    async def _on_item(self, item: dict) -> None:
        snippet = item.get("snippet") or {}
        author = item.get("authorDetails") or {}
        text = ""
        ttd = snippet.get("textMessageDetails") or {}
        text = ttd.get("messageText") or snippet.get("displayMessage") or ""
        name = author.get("displayName") or ""
        if not name or not text:
            return
        user = ChatUser(
            platform=Platform.YOUTUBE,
            id=str(author.get("channelId") or name),
            username=name,
            display_name=name,
            is_mod=bool(author.get("isChatModerator") or author.get("isChatOwner")),
            is_vip=bool(author.get("isChatSponsor")),
            is_subscriber=bool(author.get("isChatSponsor")),
        )
        await self._emit(ChatEvent(
            platform=Platform.YOUTUBE,
            user=user,
            message=text,
            message_id=str(item.get("id") or ""),
        ))
