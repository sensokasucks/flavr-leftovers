"""
Stream alert catalog, payload builder, and overlay style helpers.

Overlays and the admin test tab share this so kinds stay consistent.
Adapters (or paid chat) can call `build_alert(...)` and publish on the bus.

The overlay DOM uses Streamlabs + StreamElements class/id names so existing
alert-box CSS (Nerd Or Die, OWN3D, SE packs, OBS Custom CSS) can drop in.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Optional

from core.overlay_style import OverlayStyle

# Canonical kinds the overlay knows how to style.
KINDS: dict[str, dict[str, Any]] = {
    "follow": {
        "label": "Follow",
        "title": "New follower",
        "template": "{name} followed!",
        "accent": "kick",
        "needs": [],
        "defaults": {},
    },
    "subscribe": {
        "label": "Subscribe",
        "title": "New subscriber",
        "template": "{name} subscribed!",
        "accent": "twitch",
        "needs": [],
        "defaults": {},
    },
    "resub": {
        "label": "Resub",
        "title": "Resubscription",
        "template": "{name} resubbed for {months} months!",
        "accent": "twitch",
        "needs": ["months"],
        "defaults": {"months": 3},
    },
    "gift": {
        "label": "Gifted sub",
        "title": "Gifted sub",
        "template": "{name} gifted {qty} sub(s)!",
        "accent": "twitch",
        "needs": ["qty"],
        "defaults": {"qty": 5},
    },
    "raid": {
        "label": "Raid",
        "title": "Incoming raid",
        "template": "{name} raided with {viewers} viewers!",
        "accent": "twitch",
        "needs": ["viewers"],
        "defaults": {"viewers": 42},
    },
    "host": {
        "label": "Host",
        "title": "Host",
        "template": "{name} is hosting!",
        "accent": "kick",
        "needs": [],
        "defaults": {},
    },
    "bits": {
        "label": "Bits / Cheer",
        "title": "Cheer",
        "template": "{name} cheered {amount} bits!",
        "accent": "twitch",
        "needs": ["amount"],
        "defaults": {"amount": 500, "currency": "bits"},
    },
    "superchat": {
        "label": "Super Chat",
        "title": "Super Chat",
        "template": "{name} Super Chatted {amount_fmt}!",
        "accent": "youtube",
        "needs": ["amount"],
        "defaults": {"amount": 4.99, "currency": "USD"},
    },
    "donation": {
        "label": "Donation",
        "title": "Donation",
        "template": "{name} donated {amount_fmt}!",
        "accent": "kick",
        "needs": ["amount"],
        "defaults": {"amount": 10, "currency": "USD"},
    },
    # Kinds below borrow the picture / sound of `falls_back` until they have their own.
    "supersticker": {
        "label": "Super Sticker",
        "title": "Super Sticker",
        "template": "{name} sent a Super Sticker ({amount_fmt})!",
        "accent": "youtube",
        "needs": ["amount"],
        "defaults": {"amount": 1.99, "currency": "USD", "item": "Dancing cat"},
        "falls_back": "superchat",
    },
    "jewels": {
        "label": "YouTube gift (Jewels)",
        "title": "Gift",
        "template": "{name} sent {item}!",
        "accent": "youtube",
        "needs": ["item"],
        "defaults": {"item": "Star"},
        "falls_back": "superchat",
    },
    "kicks": {
        "label": "KICKs",
        "title": "KICKs",
        "template": "{name} sent {amount_fmt}!",
        "accent": "kick",
        "needs": ["amount"],
        "defaults": {"amount": 100, "currency": "KICKs"},
        "falls_back": "donation",
    },
    # YouTube memberships: their own kinds, so a membership can look and sound different
    # from a Twitch / Kick sub. Until they have their own picture they borrow the sub's.
    # Twitch events that only arrive through EventSub (adapters/twitch_eventsub.py)
    "powerup": {
        "label": "Bits power-up",
        "title": "Power-up",
        "template": "{name} used {item} ({amount_fmt})!",
        "accent": "twitch",
        "needs": ["amount"],
        "defaults": {"amount": 100, "currency": "bits", "item": "Gigantified emote"},
        "falls_back": "bits",
    },
    "celebration": {
        "label": "On-screen celebration",
        "title": "Celebration",
        "template": "{name} started a celebration ({amount_fmt})!",
        "accent": "twitch",
        "needs": ["amount"],
        "defaults": {"amount": 300, "currency": "bits", "item": "On-screen celebration"},
        "falls_back": "bits",
    },
    "charity": {
        "label": "Charity donation",
        "title": "Charity donation",
        "template": "{name} gave {amount_fmt} to {item}!",
        "accent": "twitch",
        "needs": ["amount"],
        "defaults": {"amount": 10, "currency": "USD", "item": "Direct Relief"},
        "falls_back": "donation",
    },
    "hypetrain": {
        "label": "Hype Train summary",
        "title": "Hype Train",
        "template": "{item} ended at level {level}!",
        "accent": "twitch",
        "needs": ["level"],
        "defaults": {"level": 3, "item": "Hype Train"},
        "falls_back": "raid",
    },
    "member": {
        "label": "YouTube new member",
        "title": "New member",
        "template": "{name} became a member!",
        "accent": "youtube",
        "needs": [],
        "defaults": {},
        "falls_back": "subscribe",
    },
    "member_milestone": {
        "label": "YouTube member milestone",
        "title": "Member milestone",
        "template": "{name} has been a member for {months} months!",
        "accent": "youtube",
        "needs": ["months"],
        "defaults": {"months": 6},
        "falls_back": "resub",
    },
    "member_gift": {
        "label": "YouTube gifted memberships",
        "title": "Gifted memberships",
        "template": "{name} gifted {qty} membership(s)!",
        "accent": "youtube",
        "needs": ["qty"],
        "defaults": {"qty": 5},
        "falls_back": "gift",
    },
    # a custom chat flag's alert (core/chat_flags.py): the flag sets the words
    "flag": {
        "label": "Chat flag",
        "title": "Chat flag",
        "template": "{name} said {item}!",
        "accent": "kick",
        "needs": [],
        "defaults": {},
        "falls_back": "follow",
    },
}

# Streamlabs / StreamElements class names applied to #alert-box.
KIND_CLASSES: dict[str, list[str]] = {
    "follow": ["follower-alert", "kind-follow"],
    "subscribe": ["subscriber-alert", "kind-subscribe"],
    "resub": ["subscriber-alert", "resub-alert", "kind-resub"],
    "gift": ["sub-gift-alert", "gift-alert", "kind-gift"],
    "raid": ["raid-alert", "kind-raid"],
    "host": ["host-alert", "kind-host"],
    "bits": ["cheer-alert", "bits-alert", "kind-bits"],
    "superchat": ["superchat-alert", "donation-alert", "kind-superchat"],
    "donation": ["donation-alert", "kind-donation"],
    "supersticker": ["sticker-alert", "superchat-alert", "donation-alert", "kind-supersticker"],
    "jewels": ["jewels-alert", "gift-alert", "donation-alert", "kind-jewels"],
    "kicks": ["kicks-alert", "donation-alert", "kind-kicks"],
    "powerup": ["powerup-alert", "cheer-alert", "bits-alert", "kind-powerup"],
    "celebration": ["celebration-alert", "powerup-alert", "cheer-alert", "bits-alert", "kind-celebration"],
    "charity": ["charity-alert", "donation-alert", "kind-charity"],
    "hypetrain": ["hypetrain-alert", "hype-train-alert", "kind-hypetrain"],
    "member": ["member-alert", "subscriber-alert", "kind-member"],
    "member_milestone": ["member-alert", "subscriber-alert", "resub-alert", "kind-member_milestone"],
    "member_gift": ["member-alert", "sub-gift-alert", "gift-alert", "kind-member_gift"],
    "flag": ["flag-alert", "kind-flag"],
}

PLATFORMS = ("kick", "twitch", "youtube")
SKINS = ("classic", "card", "custom")

OVERLAY_DIR = Path(__file__).resolve().parent.parent / "overlay"
CUSTOM_CSS_PATH = OVERLAY_DIR / "alerts-custom.css"
SETTINGS_PATH = OVERLAY_DIR / "alerts-settings.json"


def kind_catalog() -> list[dict[str, Any]]:
    """Public list for the admin UI."""
    out = []
    for key, meta in KINDS.items():
        out.append(
            {
                "kind": key,
                "label": meta["label"],
                "title": meta["title"],
                "template": meta["template"],
                "needs": list(meta["needs"]),
                "defaults": dict(meta["defaults"]),
                "accent": meta.get("accent") or "kick",
                "falls_back": meta.get("falls_back") or "",
                "css_classes": list(KIND_CLASSES.get(key, ["kind-" + key])),
            }
        )
    return out


def css_classes_for(kind: str) -> list[str]:
    return list(KIND_CLASSES.get((kind or "").strip().lower(), ["kind-follow"]))


def _fmt_amount(amount: Optional[float], currency: str) -> str:
    if amount is None:
        return ""
    cur = (currency or "").strip()
    if cur.lower() in ("bits", "bit", "kicks", "kick"):
        # platform tokens are whole numbers: "500 bits", "100 KICKs"
        label = "bits" if cur.lower().startswith("bit") else "KICKs"
        try:
            return f"{int(amount)} {label}"
        except (TypeError, ValueError):
            return f"{amount} {label}"
    if cur:
        try:
            return f"{float(amount):.2f} {cur}"
        except (TypeError, ValueError):
            return f"{amount} {cur}"
    return str(amount)


def build_alert(
    *,
    kind: str = "follow",
    username: str = "TestViewer",
    display_name: str = "",
    platform: str = "kick",
    amount: Optional[float] = None,
    currency: str = "",
    months: Optional[int] = None,
    qty: Optional[int] = None,
    viewers: Optional[int] = None,
    message: str = "",
    duration_ms: Optional[int] = None,
    is_test: bool = False,
    alert_id: Optional[str] = None,
    item: str = "",
    image: str = "",
    amount_text: str = "",
    level: Optional[int] = None,
) -> dict[str, Any]:
    """Normalize an alert payload for WS + overlay."""
    kind_key = (kind or "follow").strip().lower()
    if kind_key not in KINDS:
        raise ValueError(f"Unknown alert kind '{kind}'. Valid: {', '.join(KINDS)}")

    meta = KINDS[kind_key]
    defaults = meta["defaults"]
    plat = (platform or "kick").strip().lower()
    if plat not in PLATFORMS:
        plat = "kick"

    name = (display_name or username or "Someone").strip() or "Someone"
    user = (username or name).strip().lstrip("@") or "someone"

    if amount is None and "amount" in defaults and not amount_text:
        amount = defaults["amount"]
    if not currency and defaults.get("currency"):
        currency = str(defaults["currency"])
    if not currency and (amount is not None or "amount" in meta["needs"]):
        currency = "USD"
    if months is None and "months" in defaults:
        months = int(defaults["months"])
    if qty is None and "qty" in defaults:
        qty = int(defaults["qty"])
    if viewers is None and "viewers" in defaults:
        viewers = int(defaults["viewers"])
    if level is None and "level" in defaults:
        level = int(defaults["level"])
    if not item and defaults.get("item"):
        item = str(defaults["item"])

    # the platform's own text ("CA$10.00") when the amount couldn't be read as a number
    amount_fmt = _fmt_amount(amount, currency) if amount is not None else (amount_text or "")
    headline = meta["template"].format(
        name=name,
        months=months if months is not None else "",
        qty=qty if qty is not None else "",
        viewers=viewers if viewers is not None else "",
        # 500.0 bits reads "500 bits" (and matches amount_fmt so the overlay can wrap it)
        amount=(int(amount) if isinstance(amount, float) and amount.is_integer() else amount) if amount is not None else "",
        amount_fmt=amount_fmt or (str(amount) if amount is not None else ""),
        item=item or "a gift",
        level=level if level is not None else "",
    )

    dur = duration_ms if duration_ms is not None else 6000
    try:
        dur = max(1500, min(30000, int(dur)))
    except (TypeError, ValueError):
        dur = 6000

    return {
        "id": alert_id or uuid.uuid4().hex[:12],
        "kind": kind_key,
        "title": meta["title"],
        "headline": headline,
        "username": user.lower(),
        "display_name": name,
        "platform": plat,
        "amount": amount,
        "currency": currency or "",
        "amount_fmt": amount_fmt,
        "months": months,
        "qty": qty,
        "viewers": viewers,
        "level": level,
        "message": (message or "").strip(),
        # the sticker / gift's name and picture (shown when no picture is uploaded for the kind)
        "item": item or "",
        "image": image or "",
        "falls_back": meta.get("falls_back") or "",
        "duration_ms": dur,
        "is_test": bool(is_test),
        "css_classes": css_classes_for(kind_key),
        "timestamp": time.time(),
    }


ALERT_STYLE = OverlayStyle(
    "alerts", SKINS, image_slots=tuple(KINDS), sound_slots=tuple(KINDS),
    # tiers: the amounts where tier-2 / tier-3 / tier-4 start (bits and KICKs count 100 to the dollar)
    options={"sound_volume": 0.8, "tiers": "5,20,100"}, ranges={"sound_volume": (0.0, 1.0)},
)


def read_alert_settings(overlay_dir: Optional[Path] = None) -> dict[str, Any]:
    """skin, css_version, options (sound_volume), media {kind: url}, sounds {kind: url}."""
    return ALERT_STYLE.read_settings(overlay_dir)


def write_alert_settings(
    skin: Optional[str] = None,
    bump_css: bool = False,
    overlay_dir: Optional[Path] = None,
    options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return ALERT_STYLE.write_settings(skin=skin, bump_css=bump_css, options=options, overlay_dir=overlay_dir)


def read_custom_css(overlay_dir: Optional[Path] = None, slot: Optional[str] = None) -> str:
    return ALERT_STYLE.read_css(overlay_dir, slot=slot)


def write_custom_css(css: str, overlay_dir: Optional[Path] = None, slot: Optional[str] = None) -> dict[str, Any]:
    return ALERT_STYLE.write_css(css, overlay_dir, slot=slot)
