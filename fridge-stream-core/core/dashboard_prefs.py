"""
Dashboard layout and shortcuts, kept by Core so every browser (the PC, an OBS dock, the phone)
sees the same: data/dashboard_prefs.json (local, git-ignored like the rest of data/).

What it holds (work list items 14 and 17; admin/live-extras.js reads and writes it through
GET / PUT /api/admin/dashboard-prefs in api/admin_routes.py):

  live_layout  {"pc": LAYOUT, "phone": LAYOUT}  the Live page's card arrangement (Arrange mode).
               LAYOUT = {"order": [card ids], "wide": [card ids], "hidden": [card ids]}.
               The phone (a narrow screen) has its own, so a tidy phone page doesn't change the PC's.
  pins         [{"key", "label"}]  Stream Rooms settings pinned to the Live page (Pinned card).
  scenes       [{"id", "name", "steps": [STEP]}]  one button that does several things in a row.
               STEP = {"kind": "set", "key", "value"}   a Stream Rooms setting
                    | {"kind": "cmd", "action", "value"} a Stream Rooms card action (ROOMS_ACTIONS)
                    | {"kind": "curtain", "value"}       open / close / reveal / toggle

clean_prefs() is the only way data comes in: unknown keys are dropped and lists are capped, so a
bad PUT can't grow the file without end. Scenes run in Core (api/admin_routes.py rooms_scene), so a
phone button does the same as the PC's.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("core.dashboard_prefs")

FILE_NAME = "dashboard_prefs.json"
MAX_CARDS = 60        # card ids kept per layout list
MAX_PINS = 30
MAX_SCENES = 20
MAX_STEPS = 12
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,60}$")


def _ids(v: Any) -> List[str]:
    """A list of short ids (card ids, setting keys), duplicates and odd entries dropped."""
    out: List[str] = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, str) and _ID.match(x) and x not in out:
            out.append(x)
    return out[:MAX_CARDS]


def _layout(v: Any) -> Dict[str, List[str]]:
    v = v if isinstance(v, dict) else {}
    return {"order": _ids(v.get("order")), "wide": _ids(v.get("wide")), "hidden": _ids(v.get("hidden"))}


def _value(v: Any) -> Any:
    """A step's value: a bool, a number or a short string (what Stream Rooms settings take)."""
    if isinstance(v, (bool, int, float)):
        return v
    return str(v)[:500] if v is not None else ""


def _step(v: Any) -> Dict[str, Any] | None:
    if not isinstance(v, dict):
        return None
    kind = v.get("kind")
    if kind == "set" and isinstance(v.get("key"), str) and _ID.match(v["key"]):
        return {"kind": "set", "key": v["key"], "value": _value(v.get("value"))}
    if kind == "cmd" and isinstance(v.get("action"), str) and _ID.match(v["action"]):
        return {"kind": "cmd", "action": v["action"], "value": _value(v.get("value"))}
    if kind == "curtain" and v.get("value") in ("open", "close", "reveal", "toggle"):
        return {"kind": "curtain", "value": v["value"]}
    return None


def clean_prefs(data: Any) -> Dict[str, Any]:
    """The prefs with only known keys, each in shape and capped (see the module docstring)."""
    data = data if isinstance(data, dict) else {}
    lay = data.get("live_layout") if isinstance(data.get("live_layout"), dict) else {}
    pins = []
    for p in data.get("pins") if isinstance(data.get("pins"), list) else []:
        if isinstance(p, dict) and isinstance(p.get("key"), str) and _ID.match(p["key"]) \
                and all(q["key"] != p["key"] for q in pins):
            pins.append({"key": p["key"], "label": str(p.get("label") or p["key"])[:80]})
    scenes = []
    for sc in data.get("scenes") if isinstance(data.get("scenes"), list) else []:
        if not isinstance(sc, dict) or not isinstance(sc.get("id"), str) or not _ID.match(sc["id"]):
            continue
        steps = [s for s in (_step(x) for x in (sc.get("steps") or [])[:MAX_STEPS]) if s]
        scenes.append({"id": sc["id"], "name": str(sc.get("name") or "Scene")[:60], "steps": steps})
    return {"live_layout": {"pc": _layout(lay.get("pc")), "phone": _layout(lay.get("phone"))},
            "pins": pins[:MAX_PINS], "scenes": scenes[:MAX_SCENES]}


class DashboardPrefs:
    """Reads and writes data/dashboard_prefs.json. ``folder`` is Core's data folder."""

    def __init__(self, folder: Path):
        self.path = Path(folder) / FILE_NAME

    def load(self) -> Dict[str, Any]:
        try:
            return clean_prefs(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return clean_prefs({})
        except Exception:
            log.warning("dashboard prefs unreadable, starting fresh: %s", self.path)
            return clean_prefs({})

    def update(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Merge: only the top-level keys sent are replaced (a layout save keeps the pins)."""
        cur = self.load()
        body = body if isinstance(body, dict) else {}
        for key in ("pins", "scenes"):
            if key in body:
                cur[key] = body[key]
        if isinstance(body.get("live_layout"), dict):
            # one device's layout at a time: the other one is kept
            cur["live_layout"] = {**cur["live_layout"], **body["live_layout"]}
        cur = clean_prefs(cur)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        return cur
