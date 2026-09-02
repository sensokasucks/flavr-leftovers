"""Movie-style credits casting.

Styles live in config/cast/*.json. Pins live in data/cast_overrides.json
and survive session reset. Job titles cap at 50 characters.

Movie sequence (overlay):
  hold cards → crawl (starring / crew / groups / thanks / legal) → end hold → stinger
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import time

log = logging.getLogger("core.cast")

JOB_MAX = 50
STYLE_NAMES = {"names", "movie"}

DEFAULT_MOVIE: dict[str, Any] = {
    "id": "movie",
    "label": "Studio",
    "style": "movie",
    "studio": "Fridge Pictures",
    "mpaa": "Rated T for Toxic Chat",
    "overflow": "Additional Voices",
    "top_talkers": 5,
    "card_hold_sec": 2.8,
    "end_hold_sec": 4.0,
    "letterbox": True,
    "grain": True,
    "vignette": True,
    "in_association": True,
    "location": "Filmed entirely on location",
    "opening": [
        {"type": "mpaa"},
        {"type": "studio"},
        {"type": "title"},
        {"type": "association"},
        {"type": "job", "match": "Director", "label": "Directed by"},
        {"type": "job", "match": "Showrunner", "label": "Written by"},
        {"type": "starring"},
    ],
    "legal": [
        "© {year} {studio}",
        "No chatters were banned in the making of this stream",
        "Catering by the fridge",
        "Runtime {duration} · {count} speaking roles",
        "Soundtrack: whatever was already playing",
        "Stunts performed by the raiding party",
    ],
    "stinger": {
        "enabled": True,
        "kicker": "And also\u2026",
        "line": "the lurkers",
        "hold_sec": 4.0,
    },
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
        {"id": "vips", "title": "VIP Lounge", "source": "vips"},
        {"id": "subs", "title": "Season Regulars", "source": "subs"},
        {"id": "top", "title": "Starring", "source": "top"},
    ],
}

CORE_EXTRA_GROUPS = [
    {"id": "raiders", "title": "The Raiding Party", "source": "raiders"},
    {"id": "followers", "title": "New in Town", "source": "followers"},
    {"id": "gifted", "title": "Gifted Subs", "source": "gifted"},
    {"id": "hosts", "title": "Hosted By", "source": "hosts"},
    {"id": "cheers", "title": "Paid Extra", "source": "cheers"},
    {"id": "resubs", "title": "Returning Cast", "source": "resubs"},
]

ALERT_TAG = {
    "raid": "raiders",
    "follow": "followers",
    "gift": "gifted",
    "subscribe": "new_subs",
    "resub": "resubs",
    "host": "hosts",
    "bits": "cheers",
    "superchat": "cheers",
    "donation": "cheers",
}

ALERT_GROUP_SOURCES = {
    "raiders", "followers", "gifted", "hosts", "cheers", "resubs", "new_subs",
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


def duration_label(started_at: float, now: Optional[float] = None) -> str:
    secs = max(0, int((now if now is not None else time.time()) - (started_at or 0)))
    hours, rem = divmod(secs, 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
    if hours:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if minutes:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return "a few minutes"


def alert_note(kind: str, extra: Optional[dict] = None) -> str:
    extra = extra or {}
    kind = (kind or "").lower()
    viewers = extra.get("viewers")
    qty = extra.get("qty")
    months = extra.get("months")
    amount = extra.get("amount")
    currency = str(extra.get("currency") or extra.get("paid_currency") or "")
    try:
        viewers_n = int(viewers) if viewers not in (None, "") else 0
    except (TypeError, ValueError):
        viewers_n = 0
    try:
        qty_n = int(qty) if qty not in (None, "") else 0
    except (TypeError, ValueError):
        qty_n = 0
    try:
        months_n = int(months) if months not in (None, "") else 0
    except (TypeError, ValueError):
        months_n = 0
    if kind == "raid" and viewers_n:
        return f"with {viewers_n}"
    if kind == "gift" and qty_n:
        return f"gifted {qty_n}"
    if kind == "resub" and months_n:
        return f"{months_n} months"
    if kind in ("bits", "superchat", "donation") and amount not in (None, ""):
        if str(currency).lower() in ("bits", "bit") or kind == "bits":
            try:
                return f"{int(float(amount))} bits"
            except (TypeError, ValueError):
                return f"{amount} bits"
        try:
            return f"{float(amount):.2f} {currency or 'USD'}"
        except (TypeError, ValueError):
            return f"{amount} {currency}".strip()
    return ""


def _fill(text: str, studio: str, year: str, **extra: str) -> str:
    out = str(text or "").replace("{studio}", studio).replace("{year}", year)
    for key, val in extra.items():
        out = out.replace("{" + key + "}", str(val))
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
        self.tags: dict[str, set[str]] = {src: set() for src in ALERT_GROUP_SOURCES}
        self.alert_notes: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self.styles_dir.mkdir(parents=True, exist_ok=True)
        movie_path = self.styles_dir / "movie.json"
        if not movie_path.exists():
            payload = dict(DEFAULT_MOVIE)
            if self.allow_alert_groups:
                payload["groups"] = list(DEFAULT_MOVIE["groups"]) + list(CORE_EXTRA_GROUPS)
            movie_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
            if src in ALERT_GROUP_SOURCES and not self.allow_alert_groups:
                continue
            groups.append({
                "id": str(g.get("id") or src or "group").lower(),
                "title": str(g.get("title") or src),
                "source": src,
            })
        payload["groups"] = groups
        payload["overflow"] = str(payload.get("overflow") or "Additional Voices")[:80]
        payload["studio"] = str(payload.get("studio") or "Fridge Pictures")[:80]
        payload["mpaa"] = str(payload.get("mpaa") or "")[:80]
        payload["location"] = str(payload.get("location") or "")[:120]
        payload["in_association"] = bool(payload.get("in_association", True))
        payload["letterbox"] = bool(payload.get("letterbox", True))
        payload["grain"] = bool(payload.get("grain", True))
        payload["vignette"] = bool(payload.get("vignette", True))
        try:
            payload["top_talkers"] = max(0, min(30, int(payload.get("top_talkers") or 5)))
        except (TypeError, ValueError):
            payload["top_talkers"] = 5
        try:
            payload["card_hold_sec"] = max(0.5, min(12.0, float(payload.get("card_hold_sec") or 2.8)))
        except (TypeError, ValueError):
            payload["card_hold_sec"] = 2.8
        try:
            payload["end_hold_sec"] = max(0.0, min(20.0, float(payload.get("end_hold_sec") or 4)))
        except (TypeError, ValueError):
            payload["end_hold_sec"] = 4.0
        legal = []
        for line in payload.get("legal") or []:
            text = str(line or "").strip()
            if text:
                legal.append(text[:160])
        payload["legal"] = legal
        opening = []
        for spec in payload.get("opening") or []:
            if not isinstance(spec, dict):
                continue
            kind = str(spec.get("type") or "").lower()
            if kind not in ("mpaa", "studio", "title", "association", "job", "starring", "runtime"):
                continue
            item = {"type": kind}
            if kind == "job":
                item["match"] = clamp_job(spec.get("match") or "")
                item["label"] = str(spec.get("label") or "")[:50]
            opening.append(item)
        payload["opening"] = opening
        st = payload.get("stinger") if isinstance(payload.get("stinger"), dict) else {}
        try:
            shold = max(0.5, min(12.0, float(st.get("hold_sec") or 4)))
        except (TypeError, ValueError):
            shold = 4.0
        payload["stinger"] = {
            "enabled": bool(st.get("enabled", True)),
            "kicker": str(st.get("kicker") or "And also\u2026")[:80],
            "line": str(st.get("line") or "the lurkers")[:80],
            "hold_sec": shold,
        }
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

    def dump_tags(self) -> dict:
        return {
            "tags": {k: sorted(v) for k, v in self.tags.items() if v},
            "alert_notes": dict(self.alert_notes),
        }

    def load_tags(self, data: Optional[dict]) -> None:
        payload = data or {}
        tags = payload.get("tags") if isinstance(payload, dict) else None
        if isinstance(tags, dict):
            for src, names in tags.items():
                bucket = str(src).lower()
                if bucket not in self.tags:
                    self.tags[bucket] = set()
                if isinstance(names, list):
                    self.tags[bucket] = {str(n).lower() for n in names if n}
        notes = payload.get("alert_notes") if isinstance(payload, dict) else None
        if isinstance(notes, dict):
            self.alert_notes = {str(k).lower(): str(v) for k, v in notes.items() if v}

    def tag_alert(self, kind: str, platform: str, username: str, extra: Optional[dict] = None) -> None:
        if not self.allow_alert_groups or not username:
            return
        key = f"{(platform or '').lower()}:{username.lower()}"
        bucket = ALERT_TAG.get((kind or "").lower())
        if bucket:
            if bucket not in self.tags:
                self.tags[bucket] = set()
            self.tags[bucket].add(key)
        note = alert_note(kind, extra)
        if note:
            self.alert_notes[key] = note

    def _job_person(self, assigned: list[dict], match: str) -> Optional[dict]:
        needle = (match or "").lower()
        for row in assigned:
            if (row.get("job") or "").lower() == needle:
                return row
        return None

    def _build_cards(
        self,
        style: dict,
        assigned: list[dict],
        starring: list[dict],
        by_platform: dict,
        title: str,
        started_at: float = 0,
    ) -> list[dict]:
        studio = str(style.get("studio") or "Fridge Pictures")
        hold = float(style.get("card_hold_sec") or 2.8)
        plats = [p for p in ("twitch", "kick", "youtube") if by_platform.get(p)]
        labels = {"twitch": "Twitch", "kick": "Kick", "youtube": "YouTube"}
        names = [labels[p] for p in plats]
        if not names:
            assoc = ""
        elif len(names) == 1:
            assoc = "In association with " + names[0]
        elif len(names) == 2:
            assoc = "In association with " + names[0] + " and " + names[1]
        else:
            assoc = "In association with " + ", ".join(names[:-1]) + " and " + names[-1]
        opening = style.get("opening") or DEFAULT_MOVIE["opening"]
        cards: list[dict] = []
        for spec in opening:
            if not isinstance(spec, dict):
                continue
            kind = str(spec.get("type") or "").lower()
            if kind == "mpaa":
                line = str(style.get("mpaa") or spec.get("line") or "")
                if line:
                    cards.append({"type": "mpaa", "kicker": "", "line": line, "hold_sec": min(hold, 2.2)})
            elif kind == "studio":
                cards.append({
                    "type": "studio",
                    "kicker": "",
                    "line": f"A {studio} Production",
                    "hold_sec": hold,
                })
            elif kind == "title":
                cards.append({
                    "type": "title",
                    "kicker": "",
                    "line": title or "Thanks for watching",
                    "hold_sec": hold + 0.4,
                })
            elif kind == "association":
                if style.get("in_association", True) and assoc:
                    cards.append({"type": "association", "kicker": "", "line": assoc, "hold_sec": hold})
                loc = str(style.get("location") or "")
                if loc:
                    cards.append({"type": "location", "kicker": "", "line": loc, "hold_sec": hold * 0.85})
            elif kind == "job":
                person = self._job_person(assigned, str(spec.get("match") or ""))
                if person:
                    cards.append({
                        "type": "credit",
                        "kicker": str(spec.get("label") or person.get("job") or ""),
                        "line": person.get("display_name") or person.get("username"),
                        "hold_sec": hold,
                    })
            elif kind == "starring" and starring:
                lead = starring[0]
                cards.append({
                    "type": "credit",
                    "kicker": "Starring",
                    "line": lead.get("display_name") or lead.get("username"),
                    "hold_sec": hold + 0.2,
                })
            elif kind == "runtime":
                runtime = duration_label(started_at)
                cards.append({
                    "type": "runtime",
                    "kicker": "",
                    "line": f"A {runtime} production",
                    "hold_sec": hold,
                })
        return cards

    def decorate(self, snapshot: dict, started_at: float, *, title: str = "") -> dict:
        style = self.get_style()
        mode = style.get("style") or "names"
        chatters = list(snapshot.get("chatters") or [])
        for c in chatters:
            key = f"{c.get('platform')}:{c.get('username')}"
            note = self.alert_notes.get(key) or self.alert_notes.get(key.lower())
            if note and not c.get("alert_note"):
                c["alert_note"] = note
        snapshot["style"] = mode
        snapshot["style_id"] = style.get("id") or self.style_id
        snapshot["overrides"] = list(self.overrides.values())
        if mode != "movie" or not chatters:
            snapshot["cast"] = None
            return snapshot

        jobs: list[tuple[str, str, str]] = []
        for d in style.get("departments") or []:
            did = str(d.get("id") or d.get("title") or "crew")
            dtitle = str(d.get("title") or "Crew")
            for job in d.get("jobs") or []:
                job = clamp_job(job)
                if job:
                    jobs.append((did, dtitle, job))

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
        thanks: list[dict] = []
        for row in assigned:
            did = row.get("department_id") or "crew"
            if did == "pinned":
                thanks.append(row)
                continue
            if did not in by_dept:
                by_dept[did] = {"id": did, "title": row.get("department") or "Crew", "rows": []}
                dept_order.append(did)
            by_dept[did]["rows"].append(row)

        groups_out = []
        top_n = int(style.get("top_talkers") or 5)
        ranked = sorted(chatters, key=lambda c: int(c.get("messages") or 0), reverse=True)
        top_list = ranked[: max(0, top_n)]
        top_keys = {f"{c.get('platform')}:{c.get('username')}" for c in top_list}

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
            if src == "new_subs":
                return key in self.tags.get("new_subs", set()) or key.lower() in self.tags.get("new_subs", set())
            if src in self.tags:
                return key in self.tags[src] or key.lower() in self.tags[src]
            return False

        starring: list[dict] = []
        billing = ["Starring", "with", "featuring"]
        for i, c in enumerate(top_list):
            item = dict(c)
            if i == 0:
                item["billing"] = "Starring"
            elif i == len(top_list) - 1 and len(top_list) > 1:
                item["billing"] = "and"
            elif i < len(billing):
                item["billing"] = billing[i]
            else:
                item["billing"] = ""
            starring.append(item)

        for g in style.get("groups") or []:
            src = str(g.get("source") or "").lower()
            if src == "top":
                continue
            if src in ALERT_GROUP_SOURCES and not self.allow_alert_groups:
                continue
            members = [c for c in chatters if in_source(src, c)]
            if members:
                groups_out.append({
                    "id": g.get("id") or src,
                    "title": g.get("title") or src,
                    "source": src,
                    "chatters": members,
                })

        by_plat = snapshot.get("by_platform") or {}
        studio = str(style.get("studio") or "Fridge Pictures")
        year = str(datetime.now().year)
        runtime = duration_label(started_at)
        count = str(len(chatters))
        legal = [
            _fill(line, studio, year, duration=runtime, count=count, chatters=count)
            for line in (style.get("legal") or DEFAULT_MOVIE["legal"])
        ]
        stinger = dict(style.get("stinger") or DEFAULT_MOVIE["stinger"])
        cards = self._build_cards(style, assigned, starring, by_plat, title, started_at)

        snapshot["cast"] = {
            "departments": [by_dept[k] for k in dept_order],
            "groups": groups_out,
            "starring": starring,
            "thanks": thanks,
            "overflow": {
                "title": style.get("overflow") or "Additional Voices",
                "chatters": overflow,
            },
            "cards": cards,
            "legal": [ln for ln in legal if ln],
            "stinger": stinger if stinger.get("enabled", True) else None,
            "studio": studio,
            "end_hold_sec": float(style.get("end_hold_sec") or 4),
            "look": {
                "letterbox": bool(style.get("letterbox", True)),
                "grain": bool(style.get("grain", True)),
                "vignette": bool(style.get("vignette", True)),
            },
        }
        job_map = {f"{r.get('platform')}:{r.get('username')}": r.get("job") for r in assigned}
        for c in snapshot["chatters"]:
            c["job"] = job_map.get(f"{c.get('platform')}:{c.get('username')}")
        return snapshot
