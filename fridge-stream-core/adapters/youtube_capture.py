"""
Notes YouTube live chat fields Core doesn't know yet (InnerTube mode).

YouTube adds chat features (replies to Super Chats, for one) without documenting the
data. The first time an unknown action, chat item or field shows up, Core logs it once
and saves the whole item to ``data/youtube_new_fields.jsonl`` (runtime state, git-ignored)
so it can be read and supported later. One line per new thing, at most MAX_LINES lines
per file and MAX_ITEM_BYTES per line; nothing is sent anywhere.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("adapters.youtube")

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "youtube_new_fields.jsonl"
MAX_LINES = 200
MAX_ITEM_BYTES = 64 * 1024

# Actions that carry nothing for chat, or that Core already reads.
KNOWN_ACTIONS = {
    "addChatItemAction", "replayChatItemAction", "clickTrackingParams",
    "addLiveChatTickerItemAction", "markChatItemAsDeletedAction",
    "markChatItemsByAuthorAsDeletedAction", "removeChatItemAction",
    "removeChatItemByAuthorAction", "replaceChatItemAction", "addBannerToLiveChatCommand",
    "removeBannerForLiveChatCommand", "showLiveChatTooltipCommand",
    "updateLiveChatPollAction", "showLiveChatActionPanelAction",
    "closeLiveChatActionPanelAction", "liveChatReportModerationStateCommand",
}

# Chat item renderers: the ones Core reads plus common ones with nothing to show.
KNOWN_ITEMS = {
    "liveChatTextMessageRenderer", "liveChatPaidMessageRenderer",
    "liveChatMembershipItemRenderer", "liveChatPaidStickerRenderer",
    "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer",
    "liveChatSponsorshipsGiftRedemptionAnnouncementRenderer",
    "liveChatViewerEngagementMessageRenderer", "liveChatPlaceholderItemRenderer",
    "liveChatModeChangeMessageRenderer", "liveChatAutoModMessageRenderer",
    "liveChatDonationAnnouncementRenderer", "liveChatBannerRenderer",
}

# Fields of the renderers Core reads that are known not to matter (layout, colours,
# tracking). Anything else is new. beforeContentButtons and friends stay "new" on
# purpose: the reply chip YouTube draws in front of a message may live there.
KNOWN_FIELDS = {
    "id", "message", "authorName", "authorPhoto", "authorBadges", "authorExternalChannelId",
    "timestampUsec", "timestampText", "contextMenuEndpoint", "contextMenuAccessibility",
    "trackingParams", "purchaseAmountText", "headerBackgroundColor", "headerTextColor",
    "bodyBackgroundColor", "bodyTextColor", "authorNameTextColor", "timestampColor",
    "textInputBackgroundColor", "isV2Style", "headerSubtext", "headerPrimaryText", "empty",
    "sticker", "moneyChipBackgroundColor", "moneyChipTextColor", "stickerDisplayWidth",
    "stickerDisplayHeight", "backgroundColor", "showItemEndpoint", "creatorHeartButton",
    "pdgPurchasedNoveltyLoggingDirectives", "pdgLikeButton", "lowerBumper",
    "headerOverlayImage", "trackingParamsForCreatorHeart",
    # read by Core: gift header, Super Chat Reply button, reply / leaderboard chips
    # (an unknown chip icon is noted on its own, "chip:<icon>")
    "header", "replyButton", "beforeContentButtons",
}


class FieldScout:
    """Remembers what it already reported, so each new thing is saved once per run."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or DATA_PATH
        self._seen: set[str] = set()

    def check_action(self, action: dict) -> None:
        for key in action:
            if key not in KNOWN_ACTIONS:
                self._note(f"action:{key}", action)

    def check_item(self, item: dict) -> None:
        for key, renderer in item.items():
            if key not in KNOWN_ITEMS:
                self._note(f"item:{key}", item)
            elif isinstance(renderer, dict):
                for field in renderer:
                    if field not in KNOWN_FIELDS:
                        self._note(f"field:{key}.{field}", item)

    def note(self, what: str, sample: Any) -> None:
        """Saves one sample of something new (once per run)."""
        self._note(what, sample)

    def _note(self, what: str, sample: Any) -> None:
        if what in self._seen:
            return
        self._seen.add(what)
        log.info("[YouTube] new chat data: %s (saved to %s)", what, self._path.name)
        try:
            text = json.dumps(sample, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        if len(text.encode("utf-8")) > MAX_ITEM_BYTES:
            text = json.dumps({"truncated": True, "start": text[: MAX_ITEM_BYTES // 2]}, ensure_ascii=False)
        line = json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "new": what}, ensure_ascii=False)
        line = line[:-1] + ', "sample": ' + text + "}\n"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as f:
                    if sum(1 for _ in f) >= MAX_LINES:
                        return
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            log.debug("could not save YouTube sample: %s", e)
