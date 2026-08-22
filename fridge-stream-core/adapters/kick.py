"""
Kick.com adapter.

Listens to live chat via the public Pusher WebSocket (same approach as the
original Node bridge). Viewer counts are polled from the unofficial but
stable /api/v2/channels/{slug} endpoint.

Later we can add the official Kick API (OAuth + chat:write + rewards)
without changing the rest of Core.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from adapters.base import BaseAdapter
from core.event_bus import EventBus
from core.metrics import MetricsAggregator
from core.models import ChatEvent, ChatUser, Platform

log = logging.getLogger("adapters.kick")

PUSHER_URL = (
    "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679"
    "?protocol=7&client=js&version=8.4.0-rc2&flash=false"
)

# Cloudflare blocks custom bot UAs on kick.com/api — look like a normal browser.
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

    def __init__(self, config: dict, bus: EventBus, metrics: MetricsAggregator):
        super().__init__(config, bus, metrics)
        kick_cfg = config.get("kick", {})
        self.slug: str = (kick_cfg.get("channel_slug") or "").strip().lstrip("@")
        # Optional manual override if Kick's REST API keeps returning 403
        raw_id = kick_cfg.get("chatroom_id")
        self.chatroom_id: Optional[int] = int(raw_id) if raw_id not in (None, "", 0, "0") else None
        self.poll_interval: float = float(kick_cfg.get("poll_viewer_interval_sec", 15))
        self._ws_task: Optional[asyncio.Task] = None
        self._viewer_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if not self.slug or self.slug.startswith("YOUR_"):
            log.warning("Kick channel_slug not configured – adapter disabled")
            return

        if not self.chatroom_id:
            self.chatroom_id = await self._resolve_chatroom_id(self.slug)
            if self.chatroom_id:
                # Persist so the next start skips the lookup (and survives 403s)
                self._persist_chatroom_id(self.chatroom_id)
        else:
            log.info("Using configured chatroom_id=%s (skipping API lookup)", self.chatroom_id)

        if not self.chatroom_id:
            log.error(
                "Could not resolve Kick chatroom id for '%s'. "
                "Kick/Cloudflare may be blocking API requests (403). "
                "Set kick.chatroom_id manually in config.yaml — "
                "open https://kick.com/api/v2/channels/%s in a browser and copy chatroom.id, "
                "or re-run wizard.py after opening that URL once in a normal browser.",
                self.slug,
                self.slug,
            )
            return

        self._running = True
        self._stop_event.clear()
        self._ws_task = asyncio.create_task(self._ws_loop(), name="kick-ws")
        self._viewer_task = asyncio.create_task(self._viewer_loop(), name="kick-viewers")
        log.info("Kick adapter started for channel '%s' (chatroom %s)", self.slug, self.chatroom_id)

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        for task in (self._ws_task, self._viewer_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        log.info("Kick adapter stopped")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_chatroom_id(data: Any) -> Optional[int]:
        """Pull chatroom id from any of the shapes Kick has returned over time."""
        if not isinstance(data, dict):
            return None

        def _from_obj(obj: Any) -> Optional[int]:
            if not isinstance(obj, dict):
                return None
            chatroom = obj.get("chatroom")
            if isinstance(chatroom, dict) and chatroom.get("id") is not None:
                return int(chatroom["id"])
            if chatroom is not None and not isinstance(chatroom, dict):
                try:
                    return int(chatroom)
                except (TypeError, ValueError):
                    pass
            for key in ("chatroom_id", "chatroomId", "id"):
                # Only treat top-level "id" as chatroom when nested under chatroom-ish keys
                if key == "id":
                    continue
                val = obj.get(key)
                if val is not None:
                    try:
                        return int(val)
                    except (TypeError, ValueError):
                        pass
            return None

        cid = _from_obj(data)
        if cid is not None:
            return cid
        nested = data.get("data")
        if isinstance(nested, dict):
            cid = _from_obj(nested)
            if cid is not None:
                return cid
        return None

    async def _resolve_chatroom_id(self, slug: str) -> Optional[int]:
        """
        Try several public endpoints and header variants.

        Kick/Cloudflare often 403s automated clients. When a lookup succeeds we
        persist the id to config.yaml so later starts do not need the API again.
        """
        encoded = slug  # slug is already path-safe for Kick
        urls = [
            f"https://kick.com/api/v2/channels/{encoded}",
            f"https://kick.com/api/v1/channels/{encoded}",
            f"https://kick.com/api/v1/channels/{encoded}/chat",
            f"https://kick.com/api/v2/channels/{encoded}/chatroom",
        ]
        header_variants = [
            BROWSER_HEADERS,
            {
                **BROWSER_HEADERS,
                "Accept": "application/json",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            {
                "User-Agent": BROWSER_HEADERS["User-Agent"],
                "Accept": "application/json",
            },
        ]

        saw_403 = False
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for headers in header_variants:
                for url in urls:
                    try:
                        r = await client.get(url, headers=headers)
                        if r.status_code == 403:
                            saw_403 = True
                            log.debug("Kick 403 for %s", url)
                            continue
                        if r.status_code == 404:
                            log.error("Kick channel '%s' not found (404)", slug)
                            return None
                        if r.status_code != 200:
                            log.debug("Kick %s → HTTP %s", url, r.status_code)
                            continue
                        try:
                            data = r.json()
                        except Exception:
                            continue
                        cid = self._extract_chatroom_id(data)
                        if cid:
                            log.info("Resolved Kick chatroom id: %s via %s", cid, url)
                            return cid
                    except Exception as e:
                        log.debug("Lookup failed for %s: %s", url, e)

        if saw_403:
            log.warning(
                "Kick/Cloudflare blocked chatroom lookup for '%s' (403). "
                "Open https://kick.com/api/v2/channels/%s in a browser, "
                "copy chatroom.id into config.yaml, or run wizard.py.",
                slug,
                slug,
            )
        return None

    def _persist_chatroom_id(self, chatroom_id: int) -> None:
        """Write resolved id back into config.yaml so future starts skip the API."""
        try:
            from core.config import load_config, save_config

            cfg = load_config()
            kick = dict(cfg.get("kick") or {})
            existing = kick.get("chatroom_id")
            if existing not in (None, "", 0, "0") and int(existing) == int(chatroom_id):
                return
            kick["chatroom_id"] = int(chatroom_id)
            cfg["kick"] = kick
            path = save_config(cfg)
            log.info("Saved kick.chatroom_id=%s to %s", chatroom_id, path)
            # Keep in-memory config in sync if Core holds a reference
            self.config["kick"] = kick
        except Exception:
            log.exception("Could not persist kick.chatroom_id=%s", chatroom_id)

    # ------------------------------------------------------------------
    # Viewer polling
    # ------------------------------------------------------------------

    async def _viewer_loop(self) -> None:
        while self._running:
            try:
                await self._poll_viewers()
            except Exception:
                log.exception("viewer poll error")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
                break
            except asyncio.TimeoutError:
                pass

    async def _poll_viewers(self) -> None:
        url = f"https://kick.com/api/v2/channels/{self.slug}"
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=BROWSER_HEADERS) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    return
                data = r.json()
                livestream = data.get("livestream") or {}
                if livestream.get("is_live"):
                    count = livestream.get("viewer_count") or livestream.get("viewers") or 0
                else:
                    count = 0
                self.metrics.set_viewers(Platform.KICK, int(count))
        except Exception as e:
            log.debug("viewer poll failed: %s", e)

    # ------------------------------------------------------------------
    # Pusher WebSocket
    # ------------------------------------------------------------------

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
                    await self._subscribe(ws)
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_raw(raw)
            except ConnectionClosed as e:
                log.warning("Kick WS closed: %s – reconnecting in %.1fs", e, backoff)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("Kick WS error: %s – reconnecting in %.1fs", e, backoff)

            if not self._running:
                break
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 1.5, 30.0)

    async def _subscribe(self, ws) -> None:
        # Primary chatroom channel
        await ws.send(json.dumps({
            "event": "pusher:subscribe",
            "data": {"auth": "", "channel": f"chatrooms.{self.chatroom_id}.v2"},
        }))
        # Older variant still receives some events
        await ws.send(json.dumps({
            "event": "pusher:subscribe",
            "data": {"auth": "", "channel": f"chatrooms.{self.chatroom_id}"},
        }))

    async def _handle_raw(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8", "ignore"))
        except json.JSONDecodeError:
            return

        event_name = msg.get("event", "")
        if event_name == "pusher:ping":
            # websockets library handles protocol pings; this is app-level
            return

        if event_name in (
            "App\\Events\\ChatMessageEvent",
            "App\\Events\\ChatMessageSentEvent",
        ):
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
            or sender.get("identity", {}).get("username")
            or "unknown"
        )
        content = (data.get("content") or data.get("message") or "").strip()
        if not content:
            return

        # Identity / badges (Kick sends a fair amount of info)
        identity = sender.get("identity") or {}
        badges = []
        for b in identity.get("badges") or sender.get("badges") or []:
            if isinstance(b, dict):
                badges.append(b.get("type") or b.get("name") or str(b))
            else:
                badges.append(str(b))

        is_mod = any(b.lower() in ("moderator", "mod", "broadcaster") for b in badges)
        is_sub = any("subscriber" in b.lower() or "sub" == b.lower() for b in badges)
        is_vip = any("vip" in b.lower() for b in badges)

        user = ChatUser(
            platform=Platform.KICK,
            id=str(sender.get("id") or username),
            username=username,
            display_name=sender.get("username") or username,
            is_mod=is_mod,
            is_vip=is_vip,
            is_subscriber=is_sub,
            badges=badges,
            color=identity.get("color"),
        )

        event = ChatEvent(
            platform=Platform.KICK,
            user=user,
            message=content,
            message_id=str(data.get("id") or data.get("message_id") or ""),
            raw=data,
        )

        log.info("[Kick] %s: %s", user.username, content)
        await self._emit(event)
