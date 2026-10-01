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


def _person_key(c: dict) -> str:
    return (c.get("display_name") or c.get("username") or "").strip().lower()


def _unique_people(chatters: list[dict]) -> list[dict]:
    """One row per on-screen name (merge Kick/Twitch/YouTube twins)."""
    best: dict[str, dict] = {}
    order: list[str] = []
    for c in chatters:
        key = _person_key(c)
        if not key:
            continue
        if key not in best:
            best[key] = dict(c)
            order.append(key)
            continue
        cur = best[key]
        cur["messages"] = int(cur.get("messages") or 0) + int(c.get("messages") or 0)
        cur["is_mod"] = bool(cur.get("is_mod") or c.get("is_mod"))
        cur["is_vip"] = bool(cur.get("is_vip") or c.get("is_vip"))
        cur["is_subscriber"] = bool(cur.get("is_subscriber") or c.get("is_subscriber"))
        cur["is_paid"] = bool(cur.get("is_paid") or c.get("is_paid"))
        if (c.get("last_seen") or 0) > (cur.get("last_seen") or 0):
            cur["last_seen"] = c.get("last_seen")
            if c.get("color"):
                cur["color"] = c.get("color")
    return [best[k] for k in order]


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


def _card(item: Any, count: int) -> Optional[dict]:
    """Style JSON card: a string or {kicker, line, type, hold_sec}. {count} = unique chatters."""
    if isinstance(item, str):
        item = {"line": item}
    if not isinstance(item, dict):
        return None
    out = {
        "kicker": str(item.get("kicker") or "")[:120],
        "line": str(item.get("line") or "")[:160],
        "type": str(item.get("type") or "")[:24],
    }
    for key in ("kicker", "line"):
        out[key] = out[key].replace("{count}", str(count))
    try:
        out["hold_sec"] = max(0.3, min(30.0, float(item.get("hold_sec", 2.8))))
    except (TypeError, ValueError):
        out["hold_sec"] = 2.8
    return out if (out["line"] or out["kicker"]) else None


def _movie_extras(style: dict, ranked: list[dict], count: int) -> dict:
    """Optional movie-style extras (opening cards, starring, thanks, legal, stinger, look).

    Only what the style JSON defines is sent; the overlay skips anything missing.
    """
    out: dict[str, Any] = {}
    cards = [c for c in (_card(x, count) for x in (style.get("cards") or [])) if c]
    if cards:
        out["cards"] = cards
    stinger = _card(style.get("stinger"), count) if style.get("stinger") else None
    if stinger:
        stinger["hold_sec"] = max(stinger["hold_sec"], 1.0)
        out["stinger"] = stinger
    billing = [str(b)[:60] for b in (style.get("starring") or []) if str(b).strip()]
    if billing:
        out["starring"] = [dict(c, billing=label) for label, c in zip(billing, ranked)]
    thanks = []
    for row in style.get("thanks") or []:
        if isinstance(row, str):
            job, _, who = row.partition(":")
            row = {"job": job.strip(), "display_name": who.strip()} if who else {"job": "", "display_name": job.strip()}
        if isinstance(row, dict) and (row.get("display_name") or row.get("username")):
            thanks.append({
                "job": clamp_job(row.get("job") or ""),
                "display_name": str(row.get("display_name") or row.get("username"))[:80],
            })
    if thanks:
        out["thanks"] = thanks
    legal = [str(x)[:200].replace("{count}", str(count)) for x in (style.get("legal") or []) if str(x).strip()]
    if legal:
        out["legal"] = legal
    try:
        end_hold = float(style.get("end_hold_sec") or 0)
    except (TypeError, ValueError):
        end_hold = 0.0
    if end_hold > 0:
        out["end_hold_sec"] = min(60.0, end_hold)
    look = style.get("look")
    if isinstance(look, dict):
        out["look"] = {k: bool(look.get(k)) for k in ("letterbox", "grain", "vignette") if k in look}
    return out


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
            "donors": set(),
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
            "paid": "donors",
            "cheer": "donors",
            "donation": "donors",
            "superchat": "donors",
        }.get((kind or "").lower())
        if bucket:
            self.tags[bucket].add(key)

    def decorate(self, snapshot: dict, started_at: float) -> dict:
        style = self.get_style()
        mode = style.get("style") or "names"
        chatters = _unique_people(list(snapshot.get("chatters") or []))
        snapshot["style"] = mode
        snapshot["style_id"] = style.get("id") or self.style_id
        snapshot["overrides"] = list(self.overrides.values())
        if mode != "movie" or not chatters:
            snapshot["cast"] = None
            return snapshot

        jobs: list[tuple[str, str, str, str]] = []  # dept_id, title, job, pool
        for d in style.get("departments") or []:
            did = str(d.get("id") or d.get("title") or "crew")
            title = str(d.get("title") or "Crew")
            pool = str(d.get("pool") or "any").lower()
            for job in d.get("jobs") or []:
                job = clamp_job(job)
                if job:
                    jobs.append((did, title, job, pool))

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

        def matches_pool(c: dict, pool: str) -> bool:
            pool = (pool or "any").lower()
            if pool in ("", "any", "all"):
                return True
            key = f"{c.get('platform')}:{c.get('username')}".lower()
            if pool in ("paid", "donor", "donors", "bits", "cheers", "superchat"):
                return bool(c.get("is_paid")) or key in self.tags.get("donors", set())
            if pool in ("subs", "sub", "subscriber", "subscribers"):
                return bool(c.get("is_subscriber"))
            if pool in ("mods", "mod", "moderator"):
                return bool(c.get("is_mod"))
            if pool in ("vips", "vip"):
                return bool(c.get("is_vip"))
            if pool in self.tags:
                return key in {x.lower() for x in self.tags[pool]}
            return False

        shown: set[str] = set()
        for c in chatters:
            pk = _person_key(c)
            if not pk or pk in shown:
                continue
            plat = str(c.get("platform") or "")
            user = str(c.get("username") or "")
            ov = self.find_override(plat, user)
            if ov and ov.get("job"):
                assigned.append(row_for(c, clamp_job(ov["job"]), "pinned", "Special Thanks", True))
                shown.add(pk)

        pool_pass = (
            "paid", "donors", "mods", "subs", "gifted", "followers", "raiders", "vips", "any",
        )
        remaining = [c for c in chatters if _person_key(c) not in shown]
        for want in pool_pass:
            still = []
            for c in remaining:
                pk = _person_key(c)
                if not pk or pk in shown:
                    continue
                picked = None
                for item in order:
                    did, title, job, pool = item
                    sig = did + ":" + job
                    if sig in used:
                        continue
                    if want == "any":
                        if pool not in ("", "any", "all"):
                            continue
                    else:
                        if pool != want and not (want == "paid" and pool in ("donors", "paid")):
                            continue
                        if not matches_pool(c, pool):
                            continue
                    used.add(sig)
                    picked = item
                    break
                if picked:
                    assigned.append(row_for(c, picked[2], picked[0], picked[1], False))
                    shown.add(pk)
                else:
                    still.append(c)
            remaining = still
        overflow = [dict(c) for c in remaining]

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
            if src in ("paid", "donors"):
                key_l = key.lower()
                return bool(c.get("is_paid")) or key_l in self.tags.get("donors", set())
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
            members = []
            for c in chatters:
                pk = _person_key(c)
                if pk in shown or not in_source(src, c):
                    continue
                members.append(c)
                shown.add(pk)
            if members:
                groups_out.append({
                    "id": g.get("id") or src,
                    "title": g.get("title") or src,
                    "source": src,
                    "chatters": members,
                })

        overflow = [c for c in overflow if _person_key(c) not in shown]
        snapshot["cast"] = {
            "departments": [by_dept[k] for k in dept_order],
            "groups": groups_out,
            "overflow": {
                "title": style.get("overflow") or "Additional Voices",
                "chatters": overflow,
            },
        }
        snapshot["cast"].update(_movie_extras(style, ranked, len(chatters)))
        # also stamp job onto chatters for the name list / admin
        job_map = {f"{r.get('platform')}:{r.get('username')}": r.get("job") for r in assigned}
        for c in snapshot["chatters"]:
            c["job"] = job_map.get(f"{c.get('platform')}:{c.get('username')}")
        return snapshot
