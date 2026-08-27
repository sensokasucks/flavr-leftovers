"""Movie-style credits casting.

Styles live in config/cast/*.json. Pins live in data/cast_overrides.json
and survive session reset. Job titles cap at 50 characters.
"""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("core.cast")

JOB_MAX = 50
STYLE_NAMES = {"names", "movie"}

DEFAULT_MOVIE: dict[str, Any] = {
    "id": "movie",
    "label": "Movie",
    "style": "movie",
    "overflow": "Additional Voices",
    "top_talkers": 5,
    "departments": [
        {
            "id": "production",
            "title": "Production",
            "jobs": [
                "Showrunner",
                "Director",
                "Producer",
                "1st AD",
                "Script Supervisor",
            ],
        },
        {
            "id": "camera",
            "title": "Camera",
            "jobs": [
                "Director of Photography",
                "Camera Operator",
                "Key Grip",
                "Best Boy Grip",
                "Gaffer",
            ],
        },
        {
            "id": "sound",
            "title": "Sound",
            "jobs": [
                "Sound Mixer",
                "Boom Operator",
                "Foley Artist",
                "Chat Whisperer",
            ],
        },
        {
            "id": "chaos",
            "title": "Department of Chaos",
            "jobs": [
                "Emotional Support Chat",
                "Official First-er",
                "Lurker Liaison",
                "Raid Hype Captain",
                "Bit Accountant",
                "Craft Services",
            ],
        },
    ],
    "groups": [
        {"id": "mods", "title": "Moderation Unit", "source": "mods"},
        {"id": "subs", "title": "Season Regulars", "source": "subs"},
        {"id": "top", "title": "Starring", "source": "top"},
    ],
}


def clamp_job(title: str) -> str:
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    if len(text) > JOB_MAX:
        text = text[:JOB_MAX].rstrip()
    return text


def parse_quoted_args(text: str) -> list[str]:
    """Pull double-quoted strings, then leftover tokens (e.g. clear)."""
    raw = text or ""
    quoted = [q.strip() for q in re.findall(r'"([^"]*)"', raw)]
    rest = [p for p in re.sub(r'"[^"]*"', " ", raw).split() if p]
    return quoted + rest


def parse_identity(raw: str, default_platform: str = "") -> tuple[str, str]:
    """'kick:bob' or 'bob' → (platform, username)."""
    s = (raw or "").strip().lstrip("@")
    if ":" in s:
        plat, name = s.split(":", 1)
        plat = plat.lower().strip()
        name = name.lower().strip()
        if plat in ("kick", "twitch", "youtube", "manual") and name:
            return plat, name
    return (default_platform or "").lower(), s.lower().strip()


class CastBoard:
    def __init__(self, root: Path, *, allow_alert_groups: bool = False):
        self.root = root
        self.allow_alert_groups = allow_alert_groups
        self.styles_dir = root / "config" / "cast"
        self.overrides_path = root / "data" / "cast_overrides.json"
        self.style_id = "names"
        self.styles: dict[str, dict] = {}
        self.overrides: dict[str, dict] = {}
        self.tags: dict[str, set[str]] = {
            "raiders": set(),
            "followers": set(),
            "gifted": set(),
        }
        self.reload()

    def reload(self) -> None:
        self.styles_dir.mkdir(parents=True, exist_ok=True)
        movie_path = self.styles_dir / "movie.json"
        if not movie_path.exists():
            movie_path.write_text(json.dumps(DEFAULT_MOVIE, indent=2), encoding="utf-8")
        found: dict[str, dict] = {"names": {"id": "names", "label": "Names", "style": "names"}}
        for path in sorted(self.styles_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                log.exception("cast style unreadable: %s", path)
                continue
            if not isinstance(data, dict):
                continue
            sid = str(data.get("id") or path.stem).lower().strip()
            data["id"] = sid
            data["style"] = "movie" if (data.get("style") or "movie") != "names" else "names"
            data["label"] = data.get("label") or sid
            found[sid] = data
        self.styles = found
        self.overrides = self._load_overrides()

    def _load_overrides(self) -> dict[str, dict]:
        if not self.overrides_path.exists():
            return {}
        try:
            data = json.loads(self.overrides_path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("cast overrides unreadable")
            return {}
        out = {}
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, dict) and key:
                    out[str(key).lower()] = val
        return out

    def save_overrides(self) -> None:
        self.overrides_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.overrides_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.overrides, indent=2), encoding="utf-8")
        tmp.replace(self.overrides_path)

    def list_styles(self) -> list[dict]:
        rows = []
        for sid, data in sorted(self.styles.items()):
            rows.append({
                "id": sid,
                "label": data.get("label") or sid,
                "style": data.get("style") or "movie",
            })
        return rows

    def get_style(self, style_id: Optional[str] = None) -> dict:
        sid = (style_id or self.style_id or "names").lower()
        return self.styles.get(sid) or self.styles.get("movie") or DEFAULT_MOVIE

    def set_style(self, style_id: str) -> str:
        sid = (style_id or "names").lower().strip()
        if sid not in self.styles:
            sid = "names"
        self.style_id = sid
        return sid

    def save_style(self, data: dict) -> dict:
        sid = str(data.get("id") or "custom").lower().strip()
        sid = re.sub(r"[^a-z0-9_-]+", "-", sid) or "custom"
        if sid == "names":
            raise ValueError("cannot overwrite the built-in names style")
        payload = dict(data)
        payload["id"] = sid
        payload["style"] = "movie"
        payload["label"] = payload.get("label") or sid
        depts = []
        for d in payload.get("departments") or []:
            if not isinstance(d, dict):
                continue
            jobs = []
            for j in d.get("jobs") or []:
                title = clamp_job(j)
                if title:
                    jobs.append(title)
            depts.append({
                "id": str(d.get("id") or d.get("title") or "dept").lower(),
                "title": str(d.get("title") or "Crew"),
                "jobs": jobs,
            })
        payload["departments"] = depts
        groups = []
        for g in payload.get("groups") or []:
            if not isinstance(g, dict):
                continue
            src = str(g.get("source") or "").lower()
            if src in ("raiders", "followers", "gifted") and not self.allow_alert_groups:
                continue
            groups.append({
                "id": str(g.get("id") or src or "group").lower(),
                "title": str(g.get("title") or src),
                "source": src,
            })
        payload["groups"] = groups
        payload["overflow"] = str(payload.get("overflow") or "Additional Voices")[:80]
        path = self.styles_dir / f"{sid}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.reload()
        return self.styles.get(sid) or payload

    def pin(self, platform: str, username: str, job: str, *, set_by: str = "") -> dict:
        title = clamp_job(job)
        if not title:
            raise ValueError("job title required")
        key = f"{platform}:{username}".lower()
        self.overrides[key] = {
            "job": title,
            "platform": platform,
            "username": username,
            "set_by": set_by,
        }
        self.save_overrides()
        return self.overrides[key]

    def unpin(self, platform: str, username: str) -> bool:
        key = f"{platform}:{username}".lower()
        if key in self.overrides:
            del self.overrides[key]
            self.save_overrides()
            return True
        # username-only match
        dropped = False
        for k in list(self.overrides):
            if k.endswith(":" + username.lower()) and (not platform or k.startswith(platform + ":")):
                del self.overrides[k]
                dropped = True
        if dropped:
            self.save_overrides()
        return dropped

    def find_override(self, platform: str, username: str) -> Optional[dict]:
        key = f"{platform}:{username}".lower()
        if key in self.overrides:
            return self.overrides[key]
        for k, val in self.overrides.items():
            if k.endswith(":" + username.lower()):
                return val
        return None

    def tag_alert(self, kind: str, platform: str, username: str) -> None:
        if not self.allow_alert_groups or not username:
            return
        key = f"{(platform or '').lower()}:{username.lower()}"
        bucket = {
            "raid": "raiders",
            "follow": "followers",
            "gift": "gifted",
            "subscribe": "gifted",
        }.get((kind or "").lower())
        if bucket:
            self.tags[bucket].add(key)

    def decorate(self, snapshot: dict, started_at: float) -> dict:
        style = self.get_style()
        mode = style.get("style") or "names"
        chatters = list(snapshot.get("chatters") or [])
        snapshot["style"] = mode
        snapshot["style_id"] = style.get("id") or self.style_id
        snapshot["overrides"] = list(self.overrides.values())
        if mode != "movie" or not chatters:
            snapshot["cast"] = None
            return snapshot

        jobs: list[tuple[str, str, str]] = []  # dept_id, dept_title, job
        for d in style.get("departments") or []:
            did = str(d.get("id") or d.get("title") or "crew")
            title = str(d.get("title") or "Crew")
            for job in d.get("jobs") or []:
                job = clamp_job(job)
                if job:
                    jobs.append((did, title, job))

        rng = random.Random(int(started_at) if started_at else 1)
        order = list(jobs)
        rng.shuffle(order)
        used = set()
        assigned: list[dict] = []
        overflow: list[dict] = []

        def row_for(c: dict, job: str, dept_id: str, dept_title: str, pinned: bool) -> dict:
            item = dict(c)
            item["job"] = job
            item["department"] = dept_title
            item["department_id"] = dept_id
            item["pinned"] = pinned
            return item

        for c in chatters:
            plat = str(c.get("platform") or "")
            user = str(c.get("username") or "")
            ov = self.find_override(plat, user)
            if ov and ov.get("job"):
                assigned.append(row_for(c, clamp_job(ov["job"]), "pinned", "Special Thanks", True))
                continue
            picked = None
            for item in order:
                sig = item[0] + ":" + item[2]
                if sig in used:
                    continue
                used.add(sig)
                picked = item
                break
            if picked:
                assigned.append(row_for(c, picked[2], picked[0], picked[1], False))
            else:
                overflow.append(dict(c))

        by_dept: dict[str, dict] = {}
        dept_order = []
        for row in assigned:
            did = row.get("department_id") or "crew"
            if did not in by_dept:
                by_dept[did] = {"id": did, "title": row.get("department") or "Crew", "rows": []}
                dept_order.append(did)
            by_dept[did]["rows"].append(row)

        groups_out = []
        top_n = int(style.get("top_talkers") or 5)
        ranked = sorted(chatters, key=lambda c: int(c.get("messages") or 0), reverse=True)
        top_keys = {f"{c.get('platform')}:{c.get('username')}" for c in ranked[: max(0, top_n)]}

        def in_source(src: str, c: dict) -> bool:
            key = f"{c.get('platform')}:{c.get('username')}"
            if src == "mods":
                return bool(c.get("is_mod"))
            if src == "subs":
                return bool(c.get("is_subscriber"))
            if src == "vips":
                return bool(c.get("is_vip"))
            if src == "top":
                return key in top_keys
            if src in self.tags:
                return key in self.tags[src] or key.lower() in self.tags[src]
            return False

        for g in style.get("groups") or []:
            src = str(g.get("source") or "").lower()
            if src in ("raiders", "followers", "gifted") and not self.allow_alert_groups:
                continue
            members = [c for c in chatters if in_source(src, c)]
            if members:
                groups_out.append({
                    "id": g.get("id") or src,
                    "title": g.get("title") or src,
                    "source": src,
                    "chatters": members,
                })

        snapshot["cast"] = {
            "departments": [by_dept[k] for k in dept_order],
            "groups": groups_out,
            "overflow": {
                "title": style.get("overflow") or "Additional Voices",
                "chatters": overflow,
            },
        }
        # also stamp job onto chatters for the name list / admin
        job_map = {f"{r.get('platform')}:{r.get('username')}": r.get("job") for r in assigned}
        for c in snapshot["chatters"]:
            c["job"] = job_map.get(f"{c.get('platform')}:{c.get('username')}")
        return snapshot
