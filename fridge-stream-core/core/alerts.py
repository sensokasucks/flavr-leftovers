"""
Stream alert catalog, payload builder, and overlay style helpers.

Overlays and the admin test tab share this so kinds stay consistent.
Adapters (or paid chat) can call `build_alert(...)` and publish on the bus.

The overlay DOM uses Streamlabs + StreamElements class/id names so existing
alert-box CSS (Nerd Or Die, OWN3D, SE packs, OBS Custom CSS) can drop in.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

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
MAX_CUSTOM_CSS_BYTES = 256_000
_CSS_BLOCK = re.compile(
    r"<\s*/?\s*script|<\s*/?\s*style|javascript:|expression\s*\(",
    re.IGNORECASE,
)


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
    if cur.lower() in ("bits", "bit"):
        try:
            return f"{int(amount)} bits"
        except (TypeError, ValueError):
            return f"{amount} bits"
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


def _overlay_files(overlay_dir: Optional[Path] = None) -> tuple[Path, Path]:
    root = overlay_dir or OVERLAY_DIR
    return root / "alerts-custom.css", root / "alerts-settings.json"


def list_alert_media(overlay_dir: Optional[Path] = None) -> dict[str, str]:
    """Existing per-kind GIF/WebM files so the overlay never 404-probes."""
    root = overlay_dir or OVERLAY_DIR
    folder = root / "assets" / "alerts"
    out: dict[str, str] = {}
    if not folder.is_dir():
        return out
    for kind in KINDS:
        for ext in ("webm", "gif", "webp", "png", "svg"):
            path = folder / f"{kind}.{ext}"
            if path.is_file():
                out[kind] = f"assets/alerts/{kind}.{ext}"
                break
    return out


def read_alert_settings(overlay_dir: Optional[Path] = None) -> dict[str, Any]:
    _, settings_path = _overlay_files(overlay_dir)
    skin = "classic"
    css_version = 0
    if settings_path.is_file():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
            if isinstance(data, dict):
                if data.get("skin") in SKINS:
                    skin = data["skin"]
                css_version = int(data.get("css_version") or 0)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    return {
        "skin": skin,
        "css_version": css_version,
        "media": list_alert_media(overlay_dir),
    }


def write_alert_settings(
    skin: Optional[str] = None,
    bump_css: bool = False,
    overlay_dir: Optional[Path] = None,
) -> dict[str, Any]:
    _, settings_path = _overlay_files(overlay_dir)
    current = read_alert_settings(overlay_dir)
    if skin in SKINS:
        current["skin"] = skin
    if bump_css:
        current["css_version"] = int(time.time())
    payload = {
        "skin": current["skin"],
        "css_version": current["css_version"],
    }
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return read_alert_settings(overlay_dir)


def read_custom_css(overlay_dir: Optional[Path] = None) -> str:
    css_path, _ = _overlay_files(overlay_dir)
    if css_path.is_file():
        return css_path.read_text(encoding="utf-8")
    return ""


def write_custom_css(css: str, overlay_dir: Optional[Path] = None) -> dict[str, Any]:
    if not isinstance(css, str):
        raise ValueError("css must be a string")
    raw = css.replace("\r\n", "\n")
    if len(raw.encode("utf-8")) > MAX_CUSTOM_CSS_BYTES:
        raise ValueError("Custom CSS is too large (max 256 KB)")
    if _CSS_BLOCK.search(raw):
        raise ValueError("Custom CSS cannot contain script/style tags or expressions")
    css_path, _ = _overlay_files(overlay_dir)
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(raw, encoding="utf-8")
    return write_alert_settings(bump_css=True, overlay_dir=overlay_dir)
