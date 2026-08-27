"""End-credits unique-chatter roll.

Listens to Core's ChatEvent bus (same adapters as chat overlay). Opt-in via
credits.enabled. Overlay: /overlay/credits.html
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core.models import ChatEvent
from core.cast import CastBoard, JOB_MAX, clamp_job, parse_identity, parse_quoted_args

log = logging.getLogger("core.credits")

DEFAULT_IGNORE = [
    "nightbot",
    "streamelements",
    "streamlabs",
    "moobot",
    "fossabot",
    "wizebot",
    "sery_bot",
    "commanderroot",
    "soundalerts",
    "kofistreambot",
    "own3d",
]

LOOK_DEFAULTS: dict[str, Any] = {
    "title": "Thanks for watching",
    "subtitle": "",
    "footer": "See you next stream",
    "section_label": "Chatters",
    "group_by_platform": False,
    "sort": "first_seen",
    "columns": 2,
    "speed_px_per_sec": 42,
    "gap_after_loop_sec": 2.5,
    "mode": "loop",
    "show_platform": True,
    "show_message_count": False,
    "highlight_mods": True,
    "font_family": '"Palatino Linotype", Palatino, "Times New Roman", Georgia, serif',
    "title_size_px": 54,
    "name_size_px": 22,
    "title_color": "#f3e2b0",
    "name_color": "#f4f0e6",
    "muted_color": "#9a8f78",
    "mod_color": "#e8c36a",
    "background": "transparent",
    "text_shadow": "0 2px 8px rgba(0,0,0,0.85)",
    "letter_spacing_em": 0.04,
    "column_gap_px": 48,
    "row_gap_px": 10,
    "max_width_px": 920,
    "custom_font_url": "",
    "style_id": "names",
    "command_permission": "mod",
}


@dataclass
class Chatter:
    platform: str
    username: str
    display_name: str
    first_seen: float
    last_seen: float
    messages: int = 1
    color: Optional[str] = None
    is_mod: bool = False
    is_vip: bool = False
    is_subscriber: bool = False

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.username}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chatter":
        return cls(
            platform=str(data.get("platform") or ""),
            username=str(data.get("username") or ""),
            display_name=str(data.get("display_name") or data.get("username") or ""),
            first_seen=float(data.get("first_seen") or 0),
            last_seen=float(data.get("last_seen") or 0),
            messages=int(data.get("messages") or 1),
            color=data.get("color"),
            is_mod=bool(data.get("is_mod")),
            is_vip=bool(data.get("is_vip")),
            is_subscriber=bool(data.get("is_subscriber")),
        )


class CreditsEngine:
    def __init__(self, config: dict, root: Path):
        self.root = root
        self.enabled = False
        self.ignore: set[str] = set()
        self.min_len = 1
        self.chatters: dict[str, Chatter] = {}
        self.started_at = time.time()
        self._dirty = False
        self.theme: dict[str, Any] = dict(LOOK_DEFAULTS)
        self.play: dict[str, Any] = {
            "playing": True,
            "mode": "loop",
            "freeze": False,
            "frozen_roster": None,
            "generation": 0,
        }
        self.session_path = root / "data" / "credits_session.json"
        self.cast = CastBoard(root, allow_alert_groups=True)
        self.command_permission = "mod"
        self.configure(config)
        self.load()

    def configure(self, config: dict) -> None:
        cfg = config.get("credits") or {}
        self.enabled = bool(cfg.get("enabled"))
        ignore = list(cfg.get("ignore_usernames") or DEFAULT_IGNORE)
        if cfg.get("ignore_own_channel", True):
            for key, field in (("kick", "channel_slug"), ("twitch", "channel")):
                val = (config.get(key) or {}).get(field) or ""
                if val and not str(val).upper().startswith("YOUR_"):
                    ignore.append(val)
        self.ignore = {n.lower().strip() for n in ignore if n}
        self.min_len = max(0, int(cfg.get("min_message_length") or 1))
        session = cfg.get("session_file") or "data/credits_session.json"
        path = Path(session)
        self.session_path = path if path.is_absolute() else self.root / path
        look = {k: cfg[k] for k in LOOK_DEFAULTS if k in cfg}
        self.theme = {**LOOK_DEFAULTS, **look}
        perm = str(cfg.get("command_permission") or "mod").lower()
        self.command_permission = perm if perm in ("public", "mod", "admin") else "mod"
        sid = str(self.theme.get("style_id") or cfg.get("style_id") or "names")
        self.cast.set_style(sid)
        self.theme["style_id"] = self.cast.style_id
        self.theme["style"] = self.cast.get_style().get("style") or "names"
        if self.theme.get("mode") in ("loop", "once", "hold"):
            self.play["mode"] = self.theme["mode"]
        log.info("Credits %s — %s unique", "on" if self.enabled else "off", len(self.chatters))

    def load(self) -> None:
        if not self.session_path.exists():
            return
        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("credits session unreadable")
            return
        self.started_at = float(data.get("started_at") or self.started_at)
        for item in data.get("chatters") or []:
            try:
                c = Chatter.from_dict(item)
                if c.username:
                    self.chatters[c.key] = c
            except Exception:
                continue

    def save(self) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "started_at": self.started_at,
            "saved_at": time.time(),
            "chatters": [c.to_dict() for c in self.chatters.values()],
        }
        tmp = self.session_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.session_path)
        self._dirty = False

    def save_if_dirty(self) -> None:
        if self._dirty:
            self.save()

    def ingest(self, event: ChatEvent, *, force: bool = False) -> Optional[Chatter]:
        if not self.enabled and not force:
            return None
        user = event.user
        if not user.username or user.username in self.ignore:
            return None
        msg = (event.message or "").strip()
        if len(msg) < self.min_len:
            return None
        plat = event.platform.value if hasattr(event.platform, "value") else str(event.platform)
        key = f"{plat}:{user.username}"
        now = event.timestamp or time.time()
        existing = self.chatters.get(key)
        if existing:
            existing.last_seen = now
            existing.messages += 1
            if user.display_name:
                existing.display_name = user.display_name
            if user.color:
                existing.color = user.color
            existing.is_mod = existing.is_mod or user.is_mod
            existing.is_vip = existing.is_vip or user.is_vip
            existing.is_subscriber = existing.is_subscriber or user.is_subscriber
            self._dirty = True
            return None
        chatter = Chatter(
            platform=plat,
            username=user.username,
            display_name=user.display_name or user.username,
            first_seen=now,
            last_seen=now,
            messages=1,
            color=user.color,
            is_mod=user.is_mod,
            is_vip=user.is_vip,
            is_subscriber=user.is_subscriber,
        )
        self.chatters[key] = chatter
        self._dirty = True
        log.info("Credits new chatter [%s] %s", plat, chatter.display_name)
        return chatter

    def reset(self) -> None:
        self.chatters.clear()
        self.started_at = time.time()
        self.play["frozen_roster"] = None
        self.play["freeze"] = False
        self._dirty = True
        self.save()

    def list_chatters(self, sort: str = "first_seen") -> list[Chatter]:
        items = list(self.chatters.values())
        if sort == "name":
            items.sort(key=lambda c: c.display_name.lower())
        elif sort == "last_seen":
            items.sort(key=lambda c: c.last_seen)
        elif sort == "messages":
            items.sort(key=lambda c: (-c.messages, c.first_seen))
        else:
            items.sort(key=lambda c: c.first_seen)
        return items

    def snapshot(self) -> dict:
        sort = self.theme.get("sort") or "first_seen"
        if self.play.get("freeze") and self.play.get("frozen_roster"):
            return self.play["frozen_roster"]
        items = self.list_chatters(sort)
        by: dict[str, int] = {}
        for c in items:
            by[c.platform] = by.get(c.platform, 0) + 1
        snap = {
            "started_at": self.started_at,
            "count": len(items),
            "by_platform": by,
            "enabled": self.enabled,
            "chatters": [c.to_dict() for c in items],
        }
        return self.cast.decorate(snap, self.started_at)

    def public_play(self) -> dict:
        return {k: v for k, v in self.play.items() if k != "frozen_roster"}

    def set_play(self, body: dict[str, Any]) -> dict:
        if "playing" in body:
            self.play["playing"] = bool(body["playing"])
        if body.get("mode") in ("loop", "once", "hold"):
            self.play["mode"] = body["mode"]
            self.theme["mode"] = body["mode"]
        if "freeze" in body:
            freeze = bool(body["freeze"])
            self.play["freeze"] = freeze
            if freeze:
                self.play["frozen_roster"] = None
                self.play["frozen_roster"] = self.snapshot()
            else:
                self.play["frozen_roster"] = None
        if body.get("restart"):
            self.play["generation"] = int(self.play.get("generation") or 0) + 1
        return self.public_play()

    def apply_theme(self, body: dict[str, Any]) -> dict:
        persist = bool(body.pop("persist", True)) if "persist" in body else True
        body.pop("persist", None)
        for k, v in body.items():
            self.theme[k] = v
        return self.theme

    def note_alert(self, kind: str, platform: str, username: str) -> None:
        self.cast.tag_alert(kind, platform, username)

    def apply_credit_command(self, raw_message: str, default_platform: str, set_by: str) -> str:
        # strip command token
        text = raw_message or ""
        text = text.split(None, 1)[1] if text.split() else ""
        parts = parse_quoted_args(text)
        if not parts or not parts[0]:
            return 'Usage: !credit "name" "job title"   or   !credit "name" clear'
        plat, user = parse_identity(parts[0], default_platform)
        if not user:
            return "Need a name in quotes."
        if len(parts) == 1:
            ov = self.cast.find_override(plat, user)
            if ov:
                return f"{user} is pinned as {ov.get('job')}"
            return f"{user} has no pinned job"
        second = parts[1].strip()
        if second.lower() == "clear":
            self.cast.unpin(plat, user)
            return f"Cleared credit pin for {user}"
        job = clamp_job(second)
        if not job:
            return "Job title is empty."
        if len(second) > JOB_MAX:
            return f"Job title max is {JOB_MAX} characters."
        self.cast.pin(plat or default_platform, user, job, set_by=set_by)
        where = plat or default_platform
        return f"Pinned {where}:{user} as {job}"

    def look_for_config(self) -> dict:
        """Subset to write back into config.yaml credits:."""
        out = {"enabled": self.enabled, "ignore_usernames": sorted(self.ignore)}
        out.update(self.theme)
        return out
