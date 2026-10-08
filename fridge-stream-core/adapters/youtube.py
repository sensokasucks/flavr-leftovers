"""
YouTube Live Chat adapter (read-only).

Two modes (config youtube.mode):

  official  – YouTube Data API v3 liveChatMessages.list
              Needs api_key + video_id (or live_chat_id). Uses daily quota.

  innertube – Unofficial InnerTube endpoint the website itself uses.
              Needs only video_id. No API key / quota. Payload shape can change.

Default mode is innertube when no api_key is set; official when api_key is present
unless mode is forced.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

import httpx

from adapters.base import BaseAdapter
from adapters.youtube_avatar import best_photo
from adapters.youtube_capture import FieldScout
from core.event_bus import EventBus
from core.metrics import MetricsAggregator
from core.models import ChatEvent, ChatUser, Platform

log = logging.getLogger("adapters.youtube")

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHAT_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"
INNERTUBE_CHAT_URL = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


_NUM_RE = re.compile(r"\d[\d,.]*")


def _first_int(text: str) -> Optional[int]:
    m = _NUM_RE.search(text or "")
    if not m:
        return None
    try:
        return int(re.sub(r"\D", "", m.group(0)))
    except ValueError:
        return None


def _member_months(header: str) -> int:
    """'Member for 6 months' / 'Member for 1 year' → months (at least 1)."""
    n = _first_int(header) or 1
    return n * 12 if "year" in (header or "").lower() else n


def official_member_alert(snippet: dict, author: dict) -> tuple[bool, Optional[dict]]:
    """Data API membership events → (is a membership event, `_emit_alert` kwargs or None).

    Gift *recipients* (`giftMembershipReceivedEvent`) are membership events with no
    alert: the gifter's `membershipGiftingEvent` already covers them.
    """
    kind = snippet.get("type") or ""
    name = author.get("displayName") or ""
    # Same name as the chatter's ChatUser.username so Credits can tag them.
    who = {"username": name, "display_name": name, "user_id": str(author.get("channelId") or "")}
    if kind == "newSponsorEvent":
        return True, {"kind": "subscribe", **who}
    if kind == "memberMilestoneChatEvent":
        d = snippet.get("memberMilestoneChatDetails") or {}
        return True, {"kind": "resub", **who, "months": max(1, int(d.get("memberMonth") or 1)),
                      "message": d.get("userComment") or ""}
    if kind == "membershipGiftingEvent":
        d = snippet.get("membershipGiftingDetails") or {}
        return True, {"kind": "gift", **who, "qty": max(1, int(d.get("giftMembershipsCount") or 1))}
    if kind == "giftMembershipReceivedEvent":
        return True, None
    return False, None


class YouTubeAdapter(BaseAdapter):
    platform = Platform.YOUTUBE

    def __init__(self, config: dict, bus: EventBus, metrics: MetricsAggregator):
        super().__init__(config, bus, metrics)
        cfg = config.get("youtube", {}) or {}
        self.api_key = (cfg.get("api_key") or "").strip()
        self.video_id = (cfg.get("video_id") or "").strip()
        self.live_chat_id = (cfg.get("live_chat_id") or "").strip()
        self.channel_id = (cfg.get("channel_id") or "").strip()
        mode = (cfg.get("mode") or "").strip().lower()
        if mode in ("official", "api", "data"):
            self.mode = "official"
        elif mode in ("innertube", "unofficial", "web"):
            self.mode = "innertube"
        else:
            # Auto: prefer official when a real key is present
            self.mode = (
                "official"
                if self.api_key and not self.api_key.startswith("YOUR_")
                else "innertube"
            )
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._page_token = ""
        self._seen_ids: set[str] = set()
        self._seen_max = 500
        # notes chat data YouTube added that Core doesn't read yet (data/youtube_new_fields.jsonl)
        self.scout = FieldScout()

    async def start(self) -> None:
        if not self.video_id and not self.live_chat_id:
            log.warning("YouTube needs video_id (or live_chat_id) — adapter disabled")
            return
        if self.mode == "official" and (
            not self.api_key or self.api_key.startswith("YOUR_")
        ):
            log.warning(
                "YouTube mode=official but api_key missing — falling back to innertube"
            )
            self.mode = "innertube"
        if self.mode == "innertube" and not self.video_id:
            log.warning("YouTube innertube mode needs video_id — adapter disabled")
            return

        self._running = True
        self._stop.clear()
        name = f"youtube-{self.mode}"
        self._task = asyncio.create_task(self._loop(), name=name)
        log.info(
            "YouTube adapter starting (mode=%s, video_id=%s)",
            self.mode,
            self.video_id or "(live_chat_id only)",
        )

    async def stop(self) -> None:
        self._running = False
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("YouTube adapter stopped")

    async def _loop(self) -> None:
        if self.mode == "official":
            await self._loop_official()
        else:
            await self._loop_innertube()

    # ------------------------------------------------------------------
    # Official Data API v3
    # ------------------------------------------------------------------

    async def _loop_official(self) -> None:
        interval = 5.0
        async with httpx.AsyncClient(timeout=20.0) as client:
            if not self.live_chat_id:
                self.live_chat_id = await self._resolve_chat_id(client)
                if not self.live_chat_id:
                    log.error(
                        "Could not resolve YouTube liveChatId for video %s",
                        self.video_id,
                    )
                    return
            log.info("YouTube official liveChatId=%s", self.live_chat_id)
            while self._running:
                try:
                    interval = await self._poll_official(client)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("YouTube official poll error: %s", e)
                    interval = 8.0
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=max(2.0, interval)
                    )
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

    async def _poll_official(self, client: httpx.AsyncClient) -> float:
        params: dict[str, Any] = {
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
            await self._on_official_item(item)
        return max(2.0, interval_ms / 1000.0)

    async def _on_official_item(self, item: dict) -> None:
        mid = str(item.get("id") or "")
        if mid and mid in self._seen_ids:
            return
        snippet = item.get("snippet") or {}
        author = item.get("authorDetails") or {}
        is_member_event, alert = official_member_alert(snippet, author)
        if is_member_event:
            if mid:
                self._remember(mid)
            if alert:
                await self._emit_alert(**alert)
            # A milestone comment is something the viewer typed: keep it in chat too.
            if snippet.get("type") != "memberMilestoneChatEvent" or not (alert or {}).get("message"):
                return
            snippet = dict(snippet, textMessageDetails={"messageText": alert["message"]})
        ttd = snippet.get("textMessageDetails") or {}
        text = ttd.get("messageText") or snippet.get("displayMessage") or ""
        name = author.get("displayName") or ""
        if not name or not text:
            return
        if mid:
            self._remember(mid)
        user = ChatUser(
            platform=Platform.YOUTUBE,
            id=str(author.get("channelId") or name),
            username=name,
            display_name=name,
            is_mod=bool(author.get("isChatModerator") or author.get("isChatOwner")),
            is_vip=bool(author.get("isChatSponsor")),
            is_subscriber=bool(author.get("isChatSponsor")),
            profile_image_url=best_photo(author.get("profileImageUrl") or "") or None,
        )
        # Super Chat / paid
        paid = None
        currency = None
        is_paid = False
        ffe = snippet.get("fanFundingEventDetails") or {}
        if ffe.get("amountMicros"):
            try:
                paid = int(ffe["amountMicros"]) / 1_000_000.0
            except (TypeError, ValueError):
                paid = None
            currency = ffe.get("currency")
            is_paid = True
        log.info("[YouTube] %s: %s", user.username, text)
        await self._emit(
            ChatEvent(
                platform=Platform.YOUTUBE,
                user=user,
                message=text,
                message_id=mid or None,
                paid_amount=paid,
                paid_currency=currency,
                is_paid=is_paid,
                raw=item,
            )
        )

    # ------------------------------------------------------------------
    # InnerTube (no API key / no quota)
    # ------------------------------------------------------------------

    async def _loop_innertube(self) -> None:
        interval = 4.0
        async with httpx.AsyncClient(
            timeout=25.0, headers=BROWSER_HEADERS, follow_redirects=True
        ) as client:
            api_key, continuation, client_version = await self._bootstrap_innertube(
                client
            )
            if not api_key or not continuation:
                log.error(
                    "YouTube innertube bootstrap failed for video %s "
                    "(is the stream live with chat enabled?)",
                    self.video_id,
                )
                return
            log.info("YouTube innertube ready (video=%s)", self.video_id)
            while self._running:
                try:
                    continuation, interval = await self._poll_innertube(
                        client, api_key, continuation, client_version
                    )
                    if not continuation:
                        log.warning("YouTube innertube continuation lost — stopping")
                        break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("YouTube innertube poll error: %s", e)
                    interval = 8.0
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=max(2.0, interval)
                    )
                    break
                except asyncio.TimeoutError:
                    pass

    async def _bootstrap_innertube(
        self, client: httpx.AsyncClient
    ) -> tuple[str, str, str]:
        """
        Load the live chat page for the video and pull:
          - INNERTUBE_API_KEY
          - initial continuation token
          - client version (best-effort)
        """
        urls = [
            f"https://www.youtube.com/live_chat?v={self.video_id}&is_popout=1",
            f"https://www.youtube.com/watch?v={self.video_id}",
        ]
        api_key = ""
        continuation = ""
        client_version = "2.20240101.00.00"

        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                text = r.text
                # API key
                m = re.search(r'"INNERTUBE_API_KEY":\s*"([^"]+)"', text)
                if m:
                    api_key = m.group(1)
                m = re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":\s*"([^"]+)"', text)
                if m:
                    client_version = m.group(1)
                # Continuation — several shapes over time
                for pat in (
                    r'"continuation"\s*:\s*"([A-Za-z0-9_\-%]+)"',
                    r'"continuationCommand"\s*:\s*\{\s*"token"\s*:\s*"([^"]+)"',
                ):
                    m = re.search(pat, text)
                    if m:
                        continuation = m.group(1)
                        break
                # Prefer ytInitialData embedded continuation for live chat
                if not continuation:
                    m = re.search(
                        r"ytInitialData\s*=\s*(\{.+?\})\s*;\s*</script>",
                        text,
                        re.DOTALL,
                    )
                    if m:
                        try:
                            data = json.loads(m.group(1))
                            continuation = self._find_continuation(data) or ""
                        except json.JSONDecodeError:
                            pass
                if api_key and continuation:
                    return api_key, continuation, client_version
            except Exception as e:
                log.debug("innertube bootstrap via %s failed: %s", url, e)

        return api_key, continuation, client_version

    def _find_continuation(self, obj: Any, depth: int = 0) -> Optional[str]:
        if depth > 12:
            return None
        if isinstance(obj, dict):
            if "continuation" in obj and isinstance(obj["continuation"], str):
                # Prefer live chat continuations (often long base64-ish)
                val = obj["continuation"]
                if len(val) > 20:
                    return val
            cmd = obj.get("continuationCommand")
            if isinstance(cmd, dict) and isinstance(cmd.get("token"), str):
                return cmd["token"]
            for v in obj.values():
                found = self._find_continuation(v, depth + 1)
                if found:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = self._find_continuation(v, depth + 1)
                if found:
                    return found
        return None

    async def _poll_innertube(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        continuation: str,
        client_version: str,
    ) -> tuple[str, float]:
        body = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": client_version,
                    "hl": "en",
                    "gl": "US",
                }
            },
            "continuation": continuation,
        }
        r = await client.post(
            INNERTUBE_CHAT_URL,
            params={"key": api_key},
            json=body,
            headers={**BROWSER_HEADERS, "Content-Type": "application/json"},
        )
        if r.status_code != 200:
            log.warning("YouTube innertube HTTP %s", r.status_code)
            return continuation, 8.0
        data = r.json()
        next_cont = continuation
        interval = 4.0

        # continuationContents.liveChatContinuation is the usual shape
        cont_root = (
            (data.get("continuationContents") or {}).get("liveChatContinuation")
            or data.get("liveChatContinuation")
            or {}
        )
        actions = cont_root.get("actions") or []
        for action in actions:
            await self._on_innertube_action(action)

        # Next continuation + timeout hint
        for citem in cont_root.get("continuations") or []:
            timed = citem.get("timedContinuationData") or {}
            invalid = citem.get("invalidationContinuationData") or {}
            reload_ = citem.get("reloadContinuationData") or {}
            for block in (timed, invalid, reload_):
                tok = block.get("continuation")
                if tok:
                    next_cont = tok
                timeout_ms = block.get("timeoutMs")
                if timeout_ms is not None:
                    try:
                        interval = max(2.0, int(timeout_ms) / 1000.0)
                    except (TypeError, ValueError):
                        pass

        return next_cont, interval

    async def _on_innertube_action(self, action: dict) -> None:
        self.scout.check_action(action)
        item = (action.get("addChatItemAction") or {}).get("item")
        if not item:
            replay = action.get("replayChatItemAction") or {}
            for sub in replay.get("actions") or []:
                self.scout.check_action(sub)
                item = (sub.get("addChatItemAction") or {}).get("item")
                if item:
                    break
        if not isinstance(item, dict):
            return
        self.scout.check_item(item)

        gift = item.get("liveChatSponsorshipsGiftPurchaseAnnouncementRenderer")
        if isinstance(gift, dict):
            await self._on_innertube_gift(gift)
            return

        renderer = (
            item.get("liveChatTextMessageRenderer")
            or item.get("liveChatPaidMessageRenderer")
            or item.get("liveChatMembershipItemRenderer")
            or item.get("liveChatPaidStickerRenderer")
        )
        if not isinstance(renderer, dict):
            return

        mid = str(renderer.get("id") or "")
        if mid and mid in self._seen_ids:
            return
        if mid:
            self._remember(mid)

        author = renderer.get("authorName") or {}
        name = author.get("simpleText") or ""
        if not name and isinstance(author.get("runs"), list):
            name = "".join(r.get("text", "") for r in author["runs"])
        author_id = str(renderer.get("authorExternalChannelId") or name)

        text, emotes = runs_to_text_and_emotes(renderer.get("message") or {})
        if "liveChatMembershipItemRenderer" in item and name:
            # New member: only headerSubtext ("Welcome to …!"). Milestone: headerPrimaryText
            # ("Member for 6 months") plus the viewer's own optional message.
            primary = self._runs_to_text(renderer.get("headerPrimaryText") or {})
            if primary:
                await self._emit_alert("resub", username=name, display_name=name, user_id=author_id,
                                       months=_member_months(primary), message=text)
            else:
                await self._emit_alert("subscribe", username=name, display_name=name, user_id=author_id)
        if not name or not text:
            return

        badges: list[str] = []
        is_mod = is_owner = is_member = False
        for b in renderer.get("authorBadges") or []:
            tip = (
                (b.get("liveChatAuthorBadgeRenderer") or {}).get("tooltip") or ""
            ).lower()
            if "mod" in tip:
                is_mod = True
                badges.append("moderator")
            elif "owner" in tip:
                is_owner = True
                badges.append("broadcaster")
            elif "member" in tip or "sponsor" in tip:
                is_member = True
                badges.append("member")
            elif tip:
                badges.append(tip)

        paid = None
        currency = None
        is_paid = "liveChatPaidMessageRenderer" in item or "liveChatPaidStickerRenderer" in item
        if is_paid:
            amt = renderer.get("purchaseAmountText") or {}
            amt_text = amt.get("simpleText") or ""
            if not amt_text and isinstance(amt.get("runs"), list):
                amt_text = "".join(r.get("text", "") for r in amt["runs"])
            # Keep amount as display string in message prefix if parse fails
            if amt_text and not text.startswith(amt_text):
                prefix = f"[{amt_text}] "
                text = prefix + text
                emotes = [dict(e, start=e["start"] + len(prefix), end=e["end"] + len(prefix)) for e in emotes]

        user = ChatUser(
            platform=Platform.YOUTUBE,
            id=author_id or name,
            username=name,
            display_name=name,
            is_mod=is_mod or is_owner,
            is_vip=is_member,
            is_subscriber=is_member,
            badges=badges,
            profile_image_url=best_photo(renderer.get("authorPhoto") or {}) or None,
        )
        log.info("[YouTube] %s: %s", user.username, text)
        await self._emit(
            ChatEvent(
                platform=Platform.YOUTUBE,
                user=user,
                message=text,
                message_id=mid or None,
                paid_amount=paid,
                paid_currency=currency,
                is_paid=is_paid,
                raw=renderer,
                emotes=emotes,
            )
        )

    async def _on_innertube_gift(self, gift: dict) -> None:
        """'Gifted 5 memberships' banner. Recipients' redemption items are ignored."""
        mid = str(gift.get("id") or "")
        if mid and mid in self._seen_ids:
            return
        if mid:
            self._remember(mid)
        header = (gift.get("header") or {}).get("liveChatSponsorshipsHeaderRenderer") or {}
        author = header.get("authorName") or {}
        name = author.get("simpleText") or self._runs_to_text(author)
        if not name:
            return
        qty = _first_int(self._runs_to_text(header.get("primaryText") or {})) or 1
        author_id = str(gift.get("authorExternalChannelId") or "")
        await self._emit_alert("gift", username=name, display_name=name, user_id=author_id, qty=qty)

    @staticmethod
    def _runs_to_text(node: Any) -> str:
        return runs_to_text_and_emotes(node)[0]

    def _remember(self, mid: str) -> None:
        self._seen_ids.add(mid)
        if len(self._seen_ids) > self._seen_max:
            # Drop arbitrary older half (set has no order; rebuild is fine for dedupe)
            self._seen_ids = set(list(self._seen_ids)[self._seen_max // 2 :])


# ----------------------------------------------------------------------
# Message runs -> text + emote ranges
# ----------------------------------------------------------------------

def _emoji_image(emoji: dict) -> str:
    thumbs = ((emoji.get("image") or {}).get("thumbnails") or [])
    best = ""
    best_w = -1
    for t in thumbs:
        if isinstance(t, dict) and t.get("url"):
            w = int(t.get("width") or 0)
            if w > best_w:
                best, best_w = str(t["url"]), w
    if best.startswith("//"):
        best = "https:" + best
    return best


def runs_to_text_and_emotes(node: Any) -> tuple[str, list[dict]]:
    """InnerTube message runs -> (text, emotes).

    * Standard emoji (🍅, 🥖 ...) come through as the emoji character itself, so emoji
      reactions and the audience show them like on Twitch / Kick. Their ``emojiId`` is the
      character; before, the ``:shortcut:`` label was used, which nothing recognised.
    * YouTube's own and channel member emoji (``isCustomEmoji``) stay as their
      ``:shortcut:`` text and get an emote range with the image, same shape as the Twitch
      ranges (``start``/``end`` inclusive code points, ``provider: "youtube"``).
    """
    if not isinstance(node, dict):
        return "", []
    if "simpleText" in node:
        return str(node["simpleText"] or ""), []
    runs = node.get("runs")
    if not isinstance(runs, list):
        return "", []
    text = ""
    emotes: list[dict] = []
    for r in runs:
        if not isinstance(r, dict):
            continue
        if r.get("text"):
            text += str(r["text"])
            continue
        emoji = r.get("emoji")
        if not isinstance(emoji, dict):
            continue
        emoji_id = str(emoji.get("emojiId") or "")
        shortcuts = [str(s) for s in (emoji.get("shortcuts") or []) if s]
        custom = bool(emoji.get("isCustomEmoji")) or "/" in emoji_id or len(emoji_id) > 16
        if not custom and emoji_id:
            text += emoji_id
            continue
        label = shortcuts[0] if shortcuts else (":" + emoji_id.rsplit("/", 1)[-1] + ":" if emoji_id else ":emoji:")
        url = _emoji_image(emoji)
        start = len(text)
        text += label
        if url:
            emotes.append({
                "provider": "youtube",
                "id": emoji_id,
                "name": label,
                "start": start,
                "end": start + len(label) - 1,
                "url": url,
                "static_url": url,
                "animated": False,
            })
    return text, emotes
