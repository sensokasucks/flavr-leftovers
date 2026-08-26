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
        "template": "{name} Super Chatted {amount}!",
        "accent": "youtube",
        "needs": ["amount"],
        "defaults": {"amount": "$5.00", "currency": "USD"},
    },
    "donation": {
        "label": "Donation",
        "title": "Donation",
        "template": "{name} donated {amount}!",
        "accent": "generic",
        "needs": ["amount"],
        "defaults": {"amount": "$10.00"},
    },
}

# Alias map for adapter / test inputs
KIND_ALIASES = {
    "sub": "subscribe",
    "subscriber": "subscribe",
    "cheer": "bits",
    "super_chat": "superchat",
    "super-chat": "superchat",
    "donate": "donation",
}


def normalize_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    return KIND_ALIASES.get(k, k)


def build_alert(
    kind: str,
    *,
    name: str = "Viewer",
    message: str = "",
    amount: Any = None,
    months: Any = None,
    qty: Any = None,
    viewers: Any = None,
    currency: str = "",
    test: bool = False,
    platform: str = "",
    extra: Optional[dict] = None,
) -> dict[str, Any]:
    """Build a normalized alert payload for the overlay WebSocket / bus."""
    kind = normalize_kind(kind)
    meta = KINDS.get(kind) or {
        "label": kind.title(),
        "title": kind.title(),
        "template": "{name}",
        "accent": "generic",
        "needs": [],
        "defaults": {},
    }
    defaults = dict(meta.get("defaults") or {})
    if amount is None and "amount" in defaults:
        amount = defaults["amount"]
    if months is None and "months" in defaults:
        months = defaults["months"]
    if qty is None and "qty" in defaults:
        qty = defaults["qty"]
    if viewers is None and "viewers" in defaults:
        viewers = defaults["viewers"]
    if not currency and defaults.get("currency"):
        currency = str(defaults["currency"])

    fmt = {
        "name": name or "Viewer",
        "amount": amount if amount is not None else "",
        "months": months if months is not None else "",
        "qty": qty if qty is not None else "",
        "viewers": viewers if viewers is not None else "",
        "currency": currency or "",
    }
    try:
        title_text = str(meta["template"]).format(**fmt)
    except Exception:
        title_text = f"{fmt['name']}"

    payload = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "label": meta.get("label", kind),
        "title": meta.get("title", kind),
        "text": title_text,
        "user_message": message or "",
        "name": fmt["name"],
        "amount": fmt["amount"],
        "months": fmt["months"],
        "qty": fmt["qty"],
        "viewers": fmt["viewers"],
        "currency": fmt["currency"],
        "accent": meta.get("accent", "generic"),
        "test": bool(test),
        "platform": platform or "",
        "ts": time.time(),
    }
    if extra:
        payload["extra"] = extra
    return payload


def list_kinds() -> list[dict[str, Any]]:
    out = []
    for key, meta in KINDS.items():
        out.append({
            "id": key,
            "label": meta.get("label", key),
            "title": meta.get("title", key),
            "needs": list(meta.get("needs") or []),
            "defaults": dict(meta.get("defaults") or {}),
        })
    return out


def overlay_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "overlay"


def load_alert_settings() -> dict[str, Any]:
    path = overlay_dir() / "alerts-settings.json"
    defaults = {"skin": "classic", "duration_ms": 6000}
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass
    return defaults


def save_alert_settings(data: dict[str, Any]) -> None:
    path = overlay_dir() / "alerts-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_custom_css() -> str:
    path = overlay_dir() / "alerts-custom.css"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def save_custom_css(css: str) -> None:
    path = overlay_dir() / "alerts-custom.css"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(css or "", encoding="utf-8")
