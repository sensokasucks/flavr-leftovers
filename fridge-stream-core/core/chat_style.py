"""
The chat overlay's look (``overlay/chat.html``): skin, custom CSS, behaviour options,
and the uploaded pictures and sounds. Edited in the dashboard (Chat overlay tab); the page
polls ``/api/overlay/chat-settings`` so every save applies live. See ``core/overlay_style.py``.
"""

from __future__ import annotations

from core.overlay_style import OverlayStyle

SKINS = ("classic", "plain", "custom")

# pictures: a background and one picture per badge kind (instead of the text chips)
IMAGE_SLOTS = ("background", "badge-broadcaster", "badge-mod", "badge-vip", "badge-sub", "badge-og", "badge-founder")
# sounds: every new message, and paid messages (Super Chat, Kicks) instead of it
SOUND_SLOTS = ("message", "paid")

OPTIONS = {
    "hide_after_sec": 0,        # 0 = messages stay
    "max_messages": 30,
    "newest_on_top": False,
    "show_avatars": True,       # chatter profile pictures next to the name (a saved choice wins)
    "sound_volume": 0.6,
    "sound_min_gap_sec": 2.0,   # busy chat: at most one sound this often
}
RANGES = {
    "hide_after_sec": (0, 600),
    "max_messages": (1, 200),
    "sound_volume": (0.0, 1.0),
    "sound_min_gap_sec": (0.0, 60.0),
}

CHAT_STYLE = OverlayStyle("chat", SKINS, image_slots=IMAGE_SLOTS, sound_slots=SOUND_SLOTS,
                          options=OPTIONS, ranges=RANGES)
