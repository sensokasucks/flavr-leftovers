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

    if amount is None and "amount" in defaults:
        amount = defaults["amount"]
    if not currency and defaults.get("currency"):
        currency = str(defaults["currency"])
    if not currency:
        currency = "USD"
    if months is None and "months" in defaults:
        months = int(defaults["months"])
    if qty is None and "qty" in defaults:
        qty = int(defaults["qty"])
    if viewers is None and "viewers" in defaults:
        viewers = int(defaults["viewers"])

    amount_fmt = _fmt_amount(amount, currency)
    headline = meta["template"].format(
        name=name,
        months=months if months is not None else "",
        qty=qty if qty is not None else "",
        viewers=viewers if viewers is not None else "",
        amount=amount if amount is not None else "",
        amount_fmt=amount_fmt or (str(amount) if amount is not None else ""),
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
        "message": (message or "").strip(),
        "duration_ms": dur,
        "is_test": bool(is_test),
        "css_classes": css_classes_for(kind_key),
        "timestamp": time.time(),
    }


ALERT_STYLE = OverlayStyle(
    "alerts", SKINS, image_slots=tuple(KINDS), sound_slots=tuple(KINDS),
    options={"sound_volume": 0.8}, ranges={"sound_volume": (0.0, 1.0)},
)


def list_alert_media(overlay_dir: Optional[Path] = None) -> dict[str, str]:
    """Existing per-kind GIF/WebM files so the overlay never 404-probes."""
    return ALERT_STYLE.list_assets(overlay_dir)[0]


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


def read_custom_css(overlay_dir: Optional[Path] = None) -> str:
    return ALERT_STYLE.read_css(overlay_dir)


def write_custom_css(css: str, overlay_dir: Optional[Path] = None) -> dict[str, Any]:
    return ALERT_STYLE.write_css(css, overlay_dir)
