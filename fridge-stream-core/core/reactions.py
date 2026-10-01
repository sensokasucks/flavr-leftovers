"""
Chat reactions — emoji / emotes / commands that play effects in a game
(Stream Rooms) or, when no game is connected, on the fallback overlay.

Core owns every rule: triggers, permissions, sub/VIP limits, cooldowns,
point costs (the Core points ledger, source="reaction"), opt-in/opt-out
and chat replies. The game only draws what Core sends and reports back.

Config lives in config.yaml under `reactions:` and is edited in
Admin → Config → Reactions (PUT /api/admin/reactions, hot-applied).

WebSocket protocol (same socket overlays use, ws://127.0.0.1:3850/ws)

  Core → clients
    {"type":"reaction","data":{id, reaction, effect, params, count,
                               from:{platform,id,username,display_name,color,profile_image_url},
                               target:{type:"stage"|"user"|"guest", name} | null,
                               route:"game"|"overlay", message, ts}}
    {"type":"hello_ok","data":{protocol, effects_known}}     (to the game only)
    {"type":"game_overlay","data":{...}}                        (game → overlays)

  Game → Core (JSON text frames; anything else is ignored, "ping" still works)
    {"type":"hello","data":{client, protocol, effects:[{id,label,targeted,params:[...]}]}}
    {"type":"room_state","data":{room, targets:[{id,label,aliases}],
                                  guests:[{id,name,aliases}], seated:[username,...]}}
    {"type":"reaction_result","data":{id, outcome:"hit"|"fallback"|"dropped", target?}}
    {"type":"say","data":{text}}                                (rate limited)
    {"type":"stage_state","data":{curtain:"open"|"closed"}}    (relayed to overlays / admin)

  Core → game: {"type":"stage","data":{action:"curtain", value:"open"|"close"|"reveal"|"toggle"}}
    {"type":"overlay","data":{...}}                             (relayed as game_overlay)

Only a socket that has sent `hello` may use room_state / reaction_result /
say / overlay.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from core.market import CooldownGate
from core.models import ChatEvent, ChatUser, PermissionLevel

log = logging.getLogger("core.reactions")

PROTOCOL = 1

# ----------------------------------------------------------------------
# Effect catalog. Stream Rooms reports its own list in `hello`; this is
# the built-in list the admin editor shows until a game has connected.
# overlay=True → the fallback overlay can play it too.
# ----------------------------------------------------------------------

def _p(name, type_, default, label="", **extra):
    d = {"name": name, "type": type_, "default": default, "label": label or name.replace("_", " ").capitalize()}
    d.update(extra)
    return d


EFFECT_CATALOG: List[Dict[str, Any]] = [
    {"id": "throw", "label": "Throw at target", "targeted": True, "overlay": True,
     "description": "Arcs from the sender's seat to the target and hits it.",
     "params": [
         _p("object", "text", "🍅", "Object (emoji, emote name, or img:name for an uploaded picture)"),
         _p("impact", "select", "splat", options=["splat", "bounce", "stick", "shatter"]),
         _p("stick_sec", "number", 6, "Splat stays (s)", min=0, max=60),
         _p("arc_height", "number", 1.0, "Arc height", min=0.2, max=4),
     ]},
    {"id": "pile_up", "label": "Pile up on stage", "targeted": True, "overlay": False,
     "description": "Thrown items collect at the front of the stage.",
     "params": [
         _p("object", "text", "🍅", "Object (emoji, emote or img:name)"),
         _p("max_pile", "number", 30, "Max items in pile", min=1, max=200),
         _p("clear_after_sec", "number", 90, "Clear after (s)", min=5, max=3600),
     ]},
    {"id": "float_up", "label": "Float up from seat", "targeted": False, "overlay": True,
     "description": "Hearts / balloons rise from the sender's seat.",
     "params": [
         _p("object", "text", "❤️", "Object (emoji, emote or img:name)"),
         _p("count", "number", 5, min=1, max=40),
         _p("duration_sec", "number", 3, "Duration (s)", min=0.5, max=20),
     ]},
    {"id": "fall_down", "label": "Drift down on target", "targeted": True, "overlay": True,
     "description": "Petals / snow drift down onto the target or the whole stage.",
     "params": [
         _p("object", "text", "🌹", "Object (emoji, emote or img:name)"),
         _p("count", "number", 12, min=1, max=80),
         _p("duration_sec", "number", 4, "Duration (s)", min=0.5, max=20),
     ]},
    {"id": "rain", "label": "Rain across the room", "targeted": False, "overlay": True,
     "description": "Lots of items fall across the whole room.",
     "params": [
         _p("object", "text", "🎉", "Object (emoji, emote or img:name)"),
         _p("count", "number", 40, min=1, max=300),
         _p("duration_sec", "number", 6, "Duration (s)", min=1, max=30),
     ]},
    {"id": "confetti", "label": "Confetti burst", "targeted": True, "overlay": True,
     "description": "Particle burst at the target point.",
     "params": [
         _p("colors", "text", "", "Colours (comma list, blank = rainbow)"),
         _p("count", "number", 80, min=5, max=400),
     ]},
    {"id": "wiggle", "label": "Sender's silhouette moves", "targeted": False, "overlay": False,
     "description": "The sender's audience silhouette wiggles, jumps, waves or spins.",
     "params": [
         _p("style", "select", "wiggle", options=["wiggle", "jump", "wave", "spin"]),
         _p("duration_sec", "number", 2, "Duration (s)", min=0.3, max=10),
     ]},
    {"id": "stand_cheer", "label": "Stand and cheer", "targeted": False, "overlay": False,
     "description": "The sender's silhouette stands up for a few seconds.",
     "params": [_p("duration_sec", "number", 4, "Duration (s)", min=1, max=20)]},
    {"id": "big_shout", "label": "Big shout bubble", "targeted": False, "overlay": True,
     "description": "An oversized, styled speech bubble.",
     "params": [
         _p("text", "text", "{message}", "Text ({message}, {user})"),
         _p("color", "color", "#ffd400"),
         _p("duration_sec", "number", 5, "Duration (s)", min=1, max=20),
     ]},
    {"id": "stadium_wave", "label": "Stadium wave", "targeted": False, "overlay": False,
     "description": "A wave rolls across every seated silhouette.",
     "params": [_p("speed", "number", 1.0, min=0.2, max=4)]},
    {"id": "spotlight", "label": "Spotlight", "targeted": True, "overlay": False,
     "description": "A spotlight follows the target (or the sender) for a while.",
     "params": [
         _p("color", "color", "#fff6d0"),
         _p("duration_sec", "number", 6, "Duration (s)", min=1, max=30),
     ]},
    {"id": "lights", "label": "Room lights", "targeted": False, "overlay": False,
     "description": "Flicker, dim or tint the room lights.",
     "params": [
         _p("mode", "select", "flicker", options=["flicker", "dim", "tint", "flash", "police"]),
         _p("color", "color", "#ff3b6b"),
         _p("duration_sec", "number", 3, "Duration (s)", min=0.5, max=20),
     ]},
    {"id": "camera_shake", "label": "Camera shake", "targeted": False, "overlay": True,
     "description": "A short camera nudge for big moments.",
     "params": [
         _p("strength", "number", 0.5, min=0.05, max=2),
         _p("duration_sec", "number", 0.6, "Duration (s)", min=0.1, max=3),
     ]},
    {"id": "crowd_motion", "label": "Crowd moves", "targeted": False, "overlay": False,
     "description": "Everyone in the crowd (or the people in a combo) wiggles, jumps, cheers or dances.",
     "params": [
         _p("style", "select", "dance", options=["wiggle", "jump", "cheer", "wave", "spin", "dance"]),
         _p("who", "select", "all", "Who", options=["all", "crowd"]),
         _p("duration_sec", "number", 3, "Duration (s)", min=0.5, max=20),
     ]},
    {"id": "sign", "label": "Hold up a sign", "targeted": False, "overlay": False,
     "description": "A sign over the sender's head with what they typed after the command.",
     "params": [
         _p("text", "text", "{args}", "Text ({args} = what they typed)"),
         _p("color", "color", "#ffd400", "Border colour"),
         _p("duration_sec", "number", 20, "Duration (s)", min=2, max=60),
     ]},
    {"id": "seat_prop", "label": "Seat prop", "targeted": False, "overlay": False,
     "description": "The sender dozes off, grabs popcorn or lights up their phone.",
     "params": [
         _p("prop", "select", "sleep", options=["sleep", "snack", "phone"]),
         _p("duration_sec", "number", 12, "Duration (s)", min=2, max=60),
     ]},
    {"id": "highfive", "label": "High five", "targeted": True, "overlay": False,
     "description": "The sender and the target both jump and high-five across the room.",
     "params": []},
    {"id": "seat_move", "label": "Move seat", "targeted": False, "overlay": False,
     "description": "The sender moves to a free seat at the front or the back.",
     "params": [_p("where", "select", "front", options=["front", "back"])]},
    {"id": "seat_swap", "label": "Swap seats", "targeted": True, "overlay": False,
     "description": "The sender and the target trade seats.",
     "params": []},
    {"id": "stage_fire", "label": "Stage fire (cartoon)", "targeted": False, "overlay": False,
     "description": "Harmless cartoon flames along the front of the stage.",
     "params": [_p("duration_sec", "number", 6, "Duration (s)", min=1, max=30)]},
    {"id": "fireworks", "label": "Fireworks", "targeted": False, "overlay": True,
     "description": "Bursts of colour over the stage.",
     "params": [
         _p("count", "number", 6, "Bursts", min=1, max=30),
         _p("duration_sec", "number", 4, "Duration (s)", min=1, max=20),
     ]},
    {"id": "meter", "label": "Applause / boo meter", "targeted": False, "overlay": False,
     "description": "Fills as chat sends it; plays a payoff effect when full.",
     "params": [
         _p("meter_id", "text", "applause", "Meter name"),
         _p("goal", "number", 20, min=2, max=500),
         _p("decay_sec", "number", 20, "Empties after (s)", min=2, max=600),
         _p("payoff_effect", "text", "confetti", "Payoff effect id"),
     ]},
]

TARGET_TYPES = ("stage", "user", "guest")

DEFAULT_MESSAGES: Dict[str, str] = {
    "cooldown": "@{user} {reaction} is cooling down ({seconds}s).",
    "no_points": "@{user} {reaction} costs {cost} points — you have {balance}.",
    "no_permission": "@{user} {reaction} is for {who} only.",
    "opted_out": "@{user} {target} isn't taking reactions right now.",
    "bad_target": "@{user} there's no {target} here. Try {prefix}{targets_cmd}",
    "target_not_allowed": "@{user} {reaction} can't be aimed at {target_kind}s.",
    "stage_closed": "@{user} the stage isn't open right now.",
    "opt_out_ok": "@{user} you won't be targeted by reactions. {prefix}{opt_in_cmd} to opt back in.",
    "opt_in_ok": "@{user} you can be targeted by reactions again.",
    "targets": "Targets here: {targets}. Or @someone in the audience.",
    "targets_none": "No room is open right now.",
    "need_target": "@{user} who with? Try {prefix}{command} @name",
    "need_text": "@{user} what should it say? Try {prefix}{command} GO TEAM",
}

DEFAULT_ENTRIES: List[Dict[str, Any]] = [
    {"id": "tomato", "enabled": True, "label": "Tomato",
     "emoji": ["🍅"], "emotes": [], "commands": ["tomato"],
     "effect": "throw", "params": {"object": "🍅", "impact": "splat", "stick_sec": 6},
     "targets": ["stage", "user", "guest"], "default_target": "stage",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 5, "cooldown_global_sec": 0, "cooldown_target_sec": 8,
     "max_per_message": 3, "command_count": 1, "reply_ok": ""},
    {"id": "rose", "enabled": True, "label": "Roses",
     "emoji": ["🌹", "💐"], "emotes": [], "commands": ["rose", "roses"],
     "effect": "fall_down", "params": {"object": "🌹", "count": 12},
     "targets": ["stage", "user", "guest"], "default_target": "stage",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 10, "cooldown_global_sec": 0, "cooldown_target_sec": 0,
     "max_per_message": 1, "reply_ok": ""},
    {"id": "confetti", "enabled": True, "label": "Confetti",
     "emoji": ["🎉"], "emotes": [], "commands": ["confetti"],
     "effect": "confetti", "params": {"count": 80},
     "targets": ["stage"], "default_target": "stage",
     "permission": "public", "require": [], "cost": 25,
     "cooldown_user_sec": 30, "cooldown_global_sec": 10, "cooldown_target_sec": 0,
     "max_per_message": 1, "reply_ok": "@{user} 🎉 ({cost} pts)"},
    {"id": "wiggle", "enabled": True, "label": "Wiggle",
     "emoji": [], "emotes": [], "commands": ["wiggle", "dance"],
     "effect": "wiggle", "params": {"style": "wiggle"},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 8, "cooldown_global_sec": 0, "cooldown_target_sec": 0,
     "max_per_message": 1, "reply_ok": ""},
    {"id": "boot", "enabled": True, "label": "Boot",
     "emoji": ["🥾"], "emotes": [], "commands": ["boot"],
     "effect": "throw", "params": {"object": "img:boot", "impact": "bounce", "stick_sec": 3},
     "targets": ["stage", "user", "guest"], "default_target": "stage",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 20, "cooldown_global_sec": 2, "cooldown_target_sec": 15,
     "max_per_message": 3, "reply_ok": ""},
    {"id": "flashbang", "enabled": True, "label": "Flashbang",
     "emoji": [], "emotes": ["FLASHBANG"], "commands": [],
     "effect": "lights", "params": {"mode": "flash", "duration_sec": 1.2},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 30, "cooldown_global_sec": 20, "cooldown_target_sec": 0, "max_per_message": 1, "reply_ok": ""},
    {"id": "police", "enabled": True, "label": "Police lights",
     "emoji": ["🚨"], "emotes": ["POLICE"], "commands": [],
     "effect": "lights", "params": {"mode": "police", "duration_sec": 4},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 30, "cooldown_global_sec": 20, "cooldown_target_sec": 0, "max_per_message": 1, "reply_ok": ""},
    {"id": "this_is_fine", "enabled": True, "label": "This is fine",
     "emoji": [], "emotes": ["ThisIsFine"], "commands": [],
     "effect": "stage_fire", "params": {"duration_sec": 6},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 60, "cooldown_global_sec": 30, "cooldown_target_sec": 0, "max_per_message": 1, "reply_ok": ""},
    {"id": "dono_wall", "enabled": True, "label": "Dono wall",
     "emoji": [], "emotes": ["DonoWall"], "commands": [],
     "effect": "big_shout", "params": {"text": "🧱 DONO WALL 🧱", "color": "#c8643c", "duration_sec": 4},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 30, "cooldown_global_sec": 0, "cooldown_target_sec": 0, "max_per_message": 1, "reply_ok": ""},
    {"id": "sign", "enabled": True, "label": "Sign",
     "emoji": [], "emotes": [], "commands": ["sign"],
     "effect": "sign", "params": {"text": "{args}", "duration_sec": 20},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 30, "cooldown_global_sec": 0, "cooldown_target_sec": 0, "max_per_message": 1, "reply_ok": ""},
    {"id": "sleep", "enabled": True, "label": "Sleep",
     "emoji": [], "emotes": [], "commands": ["sleep", "nap"],
     "effect": "seat_prop", "params": {"prop": "sleep", "duration_sec": 15},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 20, "cooldown_global_sec": 0, "cooldown_target_sec": 0, "max_per_message": 1, "reply_ok": ""},
    {"id": "snack", "enabled": True, "label": "Snack",
     "emoji": [], "emotes": [], "commands": ["snack", "popcorn"],
     "effect": "seat_prop", "params": {"prop": "snack", "duration_sec": 12},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 20, "cooldown_global_sec": 0, "cooldown_target_sec": 0, "max_per_message": 1, "reply_ok": ""},
    {"id": "phone", "enabled": True, "label": "Phone",
     "emoji": [], "emotes": [], "commands": ["phone"],
     "effect": "seat_prop", "params": {"prop": "phone", "duration_sec": 12},
     "targets": [], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 20, "cooldown_global_sec": 0, "cooldown_target_sec": 0, "max_per_message": 1, "reply_ok": ""},
    {"id": "highfive", "enabled": True, "label": "High five",
     "emoji": [], "emotes": [], "commands": ["highfive", "hi5"],
     "effect": "highfive", "params": {},
     "targets": ["user"], "default_target": "",
     "permission": "public", "require": [], "cost": 0,
     "cooldown_user_sec": 20, "cooldown_global_sec": 0, "cooldown_target_sec": 10, "max_per_message": 1, "reply_ok": ""},
]

# Defaults added after the first release. normalize_config() adds each one once to an
# existing config (remembered in `seeded_defaults`), so deleting it later sticks.
LATER_DEFAULTS = ("boot", "flashbang", "police", "this_is_fine", "dono_wall", "sign", "sleep", "snack", "phone", "highfive")

DEFAULT_REACTIONS: Dict[str, Any] = {
    "enabled": False,
    # auto → game when Stream Rooms is connected, else fallback overlay
    "send_to": "auto",
    # opt_out → anyone can be targeted until they type !nothrow
    # opt_in  → only people who typed !throwok can be targeted
    "targeting": "opt_out",
    "opt_out_command": "nothrow",
    "opt_in_command": "throwok",
    "targets_command": "targets",
    "admins_free": True,
    "refund_if_dropped": True,
    "chat_replies": True,
    "say_per_minute": 6,
    "say_max_chars": 300,
    "messages": dict(DEFAULT_MESSAGES),
    "entries": [dict(e) for e in DEFAULT_ENTRIES],
}

_KICK_EMOTE = re.compile(r"\[emote:(\d+):([^\]]+)\]")
_MENTION = re.compile(r"@([A-Za-z0-9_][A-Za-z0-9_.\-]{0,39})")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_SLUG = re.compile(r"[^a-z0-9_\-]+")


def _norm_emoji(s: str) -> str:
    # ❤️ vs ❤ — ignore variation selector 16 when matching
    return (s or "").replace("️", "")


_KEY_STRIP = re.compile(r"[\s_\-.@]+")


def target_key(s: Any) -> str:
    """Target names compare without case, spaces, _ - . or @: "Presenter 2" == "presenter2",
    and a YouTube handle "@MaloneCara" == "malonecara"."""
    return _KEY_STRIP.sub("", str(s or "").strip().lower())


def _speaker(user: ChatUser) -> str:
    """Name for "@{user}" in replies. YouTube names already start with "@"."""
    return (user.display_name or user.username or "").lstrip("@")


_COUNT_TOKEN = re.compile(r"^(?:x(\d{1,3})|(\d{1,3})x)$", re.IGNORECASE)
_BARE_NUMBER = re.compile(r"^\d{1,3}$")


def split_count(words: List[str]) -> Tuple[Optional[int], List[str]]:
    """A "how many" at the end of a command's words -> (count, the other words).

    ``x5`` / ``5x`` always count. A bare ``5`` only counts when it's the only word
    (``!tomato 5``) or follows an ``@mention`` (``!tomato @bob 5``), so ``!tomato presenter 2``
    still means presenter 2.
    """
    words = [w for w in (str(x).strip() for x in words) if w]
    if not words:
        return None, words
    last = words[-1]
    m = _COUNT_TOKEN.match(last)
    if m:
        return int(m.group(1) or m.group(2)), words[:-1]
    if _BARE_NUMBER.match(last) and (len(words) == 1 or words[-2].startswith("@")):
        return int(last), words[:-1]
    return None, words


def command_count(entry: Dict[str, Any], typed: Optional[int]) -> int:
    """How many a command fires: the typed number, else the entry's ``command_count``;
    never more than ``max_per_message`` (or ``command_count`` if that's set higher)."""
    cap = max(int(entry.get("max_per_message", 1)), int(entry.get("command_count", 1)))
    n = typed if typed is not None else int(entry.get("command_count", 1))
    return max(1, min(int(n), cap))


def _slug(s: Any) -> str:
    return _SLUG.sub("", str(s or "").strip().lower())


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [p for p in re.split(r"[,\n]", v)]
    out = []
    for item in v:
        s = str(item or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _num(v: Any, default: float, lo: float | None = None, hi: float | None = None) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        n = float(default)
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def effect_by_id(effects: Iterable[Dict[str, Any]], eid: str) -> Optional[Dict[str, Any]]:
    for e in effects:
        if e.get("id") == eid:
            return e
    return None


def normalize_entry(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Fill defaults and clean types. Used on load and on admin save."""
    raw = dict(raw or {})
    rid = _slug(raw.get("id") or raw.get("label") or "")
    perm = str(raw.get("permission") or "public").lower()
    if perm not in ("public", "mod", "admin"):
        perm = "public"
    targets = [t for t in (str(x).lower() for x in _as_list(raw.get("targets"))) if t in TARGET_TYPES]
    default_target = str(raw.get("default_target") or "").lower()
    if default_target not in ("", "stage", "sender"):
        default_target = "stage" if "stage" in targets else ""
    require = [r for r in (str(x).lower() for x in _as_list(raw.get("require"))) if r in ("sub", "vip")]
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    return {
        "id": rid,
        "enabled": bool(raw.get("enabled", True)),
        "label": str(raw.get("label") or rid),
        "emoji": _as_list(raw.get("emoji")),
        "emotes": _as_list(raw.get("emotes")),
        "commands": [_slug(c.lstrip("!")) for c in _as_list(raw.get("commands")) if _slug(c.lstrip("!"))],
        "effect": str(raw.get("effect") or "throw").strip(),
        "params": dict(params),
        "targets": targets,
        "default_target": default_target,
        "permission": perm,
        "require": require,
        "cost": int(_num(raw.get("cost"), 0, 0, 1_000_000)),
        "cooldown_user_sec": _num(raw.get("cooldown_user_sec"), 0, 0, 86400),
        "cooldown_global_sec": _num(raw.get("cooldown_global_sec"), 0, 0, 86400),
        "cooldown_target_sec": _num(raw.get("cooldown_target_sec"), 0, 0, 86400),
        "max_per_message": int(_num(raw.get("max_per_message"), 1, 1, 50)),
        "command_count": int(_num(raw.get("command_count"), 1, 1, 50)),
        "reply_ok": str(raw.get("reply_ok") or ""),
    }


def normalize_config(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    """Whole `reactions:` block with defaults. Entries keep their order; blank / duplicate ids dropped."""
    raw = dict(raw or {})
    cfg = {k: v for k, v in DEFAULT_REACTIONS.items() if k not in ("messages", "entries")}
    for k in cfg:
        if k in raw:
            cfg[k] = raw[k]
    cfg["enabled"] = bool(cfg["enabled"])
    cfg["send_to"] = str(cfg["send_to"] or "auto").lower()
    if cfg["send_to"] not in ("auto", "game", "overlay"):
        cfg["send_to"] = "auto"
    cfg["targeting"] = "opt_in" if str(cfg["targeting"]).lower() == "opt_in" else "opt_out"
    for key in ("opt_out_command", "opt_in_command", "targets_command"):
        cfg[key] = _slug(str(cfg[key] or "").lstrip("!")) or DEFAULT_REACTIONS[key]
    for key in ("admins_free", "refund_if_dropped", "chat_replies"):
        cfg[key] = bool(cfg[key])
    cfg["say_per_minute"] = int(_num(cfg["say_per_minute"], 6, 0, 60))
    cfg["say_max_chars"] = int(_num(cfg["say_max_chars"], 300, 20, 500))
    msgs = dict(DEFAULT_MESSAGES)
    if isinstance(raw.get("messages"), dict):
        msgs.update({k: str(v) for k, v in raw["messages"].items() if v is not None})
    cfg["messages"] = msgs
    entries_raw = raw.get("entries")
    seeded = [str(x) for x in _as_list(raw.get("seeded_defaults"))]
    if entries_raw is None:
        entries_raw = DEFAULT_ENTRIES
        seeded = [e["id"] for e in DEFAULT_ENTRIES]
    else:
        entries_raw = list(entries_raw or [])
        have = {_slug((e or {}).get("id") or "") for e in entries_raw if isinstance(e, dict)}
        for rid in LATER_DEFAULTS:
            if rid in seeded:
                continue
            seeded.append(rid)
            if rid not in have:
                entries_raw.append(next(e for e in DEFAULT_ENTRIES if e["id"] == rid))
    cfg["seeded_defaults"] = seeded
    entries, seen = [], set()
    for e in entries_raw or []:
        if not isinstance(e, dict):
            continue
        ne = normalize_entry(e)
        if not ne["id"] or ne["id"] in seen:
            continue
        seen.add(ne["id"])
        entries.append(ne)
    cfg["entries"] = entries
    return cfg


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fmt(template: str, **ctx) -> str:
    try:
        return str(template or "").format_map(_SafeDict(ctx))
    except (ValueError, IndexError):
        return str(template or "")


# ----------------------------------------------------------------------
# Opt-in / opt-out book (data/reactions_optout.json)
# ----------------------------------------------------------------------

class OptBook:
    def __init__(self, path: Optional[Path]):
        self.path = path
        self.opted_out: set[str] = set()
        self.opted_in: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.opted_out = {str(x).lstrip("@").lower() for x in data.get("opted_out", [])}
            self.opted_in = {str(x).lstrip("@").lower() for x in data.get("opted_in", [])}
        except Exception:
            log.warning("Could not read %s — starting empty", self.path)

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "opted_out": sorted(self.opted_out),
                "opted_in": sorted(self.opted_in),
            }, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            log.exception("Could not save %s", self.path)

    def opt_out(self, name: str) -> None:
        n = name.lstrip("@").lower()
        self.opted_out.add(n)
        self.opted_in.discard(n)
        self._save()

    def opt_in(self, name: str) -> None:
        n = name.lstrip("@").lower()
        self.opted_in.add(n)
        self.opted_out.discard(n)
        self._save()

    def targetable(self, name: str, mode: str) -> bool:
        n = name.lstrip("@").lower()
        if n in self.opted_out:
            return False
        if mode == "opt_in":
            return n in self.opted_in
        return True


# ----------------------------------------------------------------------
# Engine
class EmoteBook:
    """Emote name → picture, learned from chat (Twitch native / BTTV / FFZ / 7TV ranges,
    YouTube custom emoji, Kick [emote:id:name] tokens). Lets a thrown / floated emote name
    ("KEKW") show as the emote's picture instead of its text."""

    KICK_URL = "https://files.kick.com/emotes/{id}/fullsize"
    MAX = 600

    def __init__(self):
        self._by_name: Dict[str, Dict[str, Any]] = {}

    def learn(self, event: ChatEvent) -> None:
        for em in event.emotes or []:
            if not isinstance(em, dict):
                continue
            name = str(em.get("name") or "").strip()
            url = str(em.get("url") or "")
            # animated WebP (7TV) can't be decoded by the game: use the still one
            if str(em.get("provider")) == "7tv" and em.get("animated") and em.get("static_url"):
                url = str(em.get("static_url"))
            if name and url.startswith("https://"):
                self._put(name, url, bool(em.get("animated")) and url.endswith(".gif"))
        for m in _KICK_EMOTE.finditer(event.message or ""):
            self._put(m.group(2), self.KICK_URL.format(id=m.group(1)), False)

    def _put(self, name: str, url: str, animated: bool) -> None:
        key = name.strip(":").lower()
        if not key:
            return
        self._by_name.pop(key, None)
        self._by_name[key] = {"name": name.strip(":"), "url": url, "animated": animated}
        while len(self._by_name) > self.MAX:
            self._by_name.pop(next(iter(self._by_name)))

    def get(self, name: Any) -> Optional[Dict[str, Any]]:
        return self._by_name.get(str(name or "").strip().strip(":").lower())

    def picture(self, name: Any) -> Optional[Dict[str, Any]]:
        """{name, url, animated} like a reaction picture, or None."""
        hit = self.get(name)
        return dict(hit) if hit else None


def user_ref(user: ChatUser) -> Dict[str, Any]:
    """The `from` block Core sends with a reaction."""
    return {
        "platform": user.platform.value,
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "color": user.color,
        "profile_image_url": user.profile_image_url,
    }


_ARGS_TOKEN = "{args}"


def args_text(words: Iterable[str], limit: int = 60) -> str:
    """What someone typed after a command, tidied for a sign / shout: Kick emote tokens
    become their names, spaces collapse, capped at `limit` characters."""
    text = " ".join(str(w) for w in words)
    text = _KICK_EMOTE.sub(lambda m: m.group(2), text)
    text = " ".join(text.split())
    return text[:limit].strip()


def _uses_args(entry: Dict[str, Any]) -> bool:
    return any(isinstance(v, str) and _ARGS_TOKEN in v for v in (entry.get("params") or {}).values())


# Effects that make no sense without someone to do them with.
TARGET_REQUIRED = {"highfive", "seat_swap"}


# ----------------------------------------------------------------------

ReplyFn = Callable[[ChatEvent, str], Awaitable[None]]
SayFn = Callable[[str, Optional[str]], Awaitable[None]]
BroadcastFn = Callable[[dict], Awaitable[None]]


class ReactionEngine:
    def __init__(
        self,
        get_config: Callable[[], dict],
        store=None,
        perms=None,
        data_dir: Optional[Path] = None,
        reply: Optional[ReplyFn] = None,
        say: Optional[SayFn] = None,
        broadcast: Optional[BroadcastFn] = None,
        groups_active: Optional[Callable[[], Iterable[str]]] = None,
        command_prefix: Callable[[], str] | str = "!",
        images=None,
    ):
        self._get_config = get_config
        self.images = images      # core.reaction_images.ReactionImages (pictures for "img:name" objects)
        self.emotes = EmoteBook()  # emote name -> picture, learned from chat
        self.store = store
        self.perms = perms
        self.data_dir = Path(data_dir) if data_dir else None
        self._reply = reply
        self._say = say
        self._broadcast = broadcast
        self._groups_active = groups_active
        self._prefix = command_prefix
        self.gate = CooldownGate()
        self.opt = OptBook(self.data_dir / "reactions_optout.json" if self.data_dir else None)
        # websocket-like objects (async send_json) that said hello
        self.game_clients: Dict[Any, Dict[str, Any]] = {}
        self.room_state: Optional[Dict[str, Any]] = None
        self.game_effects: List[Dict[str, Any]] = self._load_caps()
        self.pending: Dict[str, Dict[str, Any]] = {}
        self._say_times: deque = deque()
        self.recent: deque = deque(maxlen=30)   # admin "last reactions" list
        self.stage_state: Dict[str, Any] = {}    # game's stage (curtain open / closed)
        self.stats = {"fired": 0, "rejected": 0, "refunded": 0, "points_spent": 0}

    # ---------------- config helpers ----------------

    @property
    def cfg(self) -> Dict[str, Any]:
        full = self._get_config() or {}
        return normalize_config(full.get("reactions"))

    def prefix(self) -> str:
        p = self._prefix() if callable(self._prefix) else self._prefix
        return p or "!"

    def points_enabled(self) -> bool:
        full = self._get_config() or {}
        return bool((full.get("points") or {}).get("enabled"))

    def active(self) -> bool:
        if not self.cfg["enabled"]:
            return False
        if self._groups_active is not None:
            try:
                return "reactions" in set(self._groups_active())
            except Exception:
                return True
        return True

    def entry_usable(self, entry: Dict[str, Any]) -> Tuple[bool, str]:
        if not entry["enabled"]:
            return False, "disabled"
        if entry["cost"] > 0 and not self.points_enabled():
            return False, "costs points but points are off"
        return True, ""

    def known_effects(self) -> List[Dict[str, Any]]:
        """Game-reported effects first, then built-ins the game didn't list."""
        out, seen = [], set()
        builtin = {e["id"]: e for e in EFFECT_CATALOG}
        for e in self.game_effects:
            eid = str(e.get("id") or "")
            if not eid or eid in seen:
                continue
            seen.add(eid)
            base = builtin.get(eid, {})
            merged = {**base, **e, "in_game": True, "overlay": bool(base.get("overlay"))}
            # a game that lists an effect without settings keeps the built-in ones
            if not e.get("params"):
                merged["params"] = list(base.get("params") or [])
            if not e.get("description") and base.get("description"):
                merged["description"] = base["description"]
            out.append(merged)
        for e in EFFECT_CATALOG:
            if e["id"] in seen:
                continue
            out.append({**e, "in_game": not self.game_effects})
        return out

    def command_tokens(self) -> Dict[str, str]:
        """token → entry id (plus the built-in opt/targets commands)."""
        cfg = self.cfg
        out: Dict[str, str] = {}
        for tok in (cfg["opt_out_command"], cfg["opt_in_command"], cfg["targets_command"]):
            out[tok] = "@" + tok
        for e in cfg["entries"]:
            for c in e["commands"]:
                out.setdefault(c, e["id"])
        return out

    # ---------------- caps persistence ----------------

    def _caps_path(self) -> Optional[Path]:
        return self.data_dir / "reactions_caps.json" if self.data_dir else None

    def _load_caps(self) -> List[Dict[str, Any]]:
        p = self._caps_path()
        if not p or not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return [e for e in data.get("effects", []) if isinstance(e, dict)]
        except Exception:
            return []

    def _save_caps(self) -> None:
        p = self._caps_path()
        if not p:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"effects": self.game_effects, "saved": time.time()}, indent=1), encoding="utf-8")
        except Exception:
            log.exception("could not save %s", p)

    # ---------------- chat entry point ----------------

    async def handle_chat(self, event: ChatEvent, router_owns_command: bool = False) -> bool:
        """
        Look at one chat message. Returns True when it was a reaction
        command (so the caller should not treat it as unknown).
        """
        if "system" in (event.user.badges or []):
            return False
        self.emotes.learn(event)
        if not self.active():
            return False
        cfg = self.cfg
        if event.is_command:
            if router_owns_command:
                return False
            name = (event.command_name or "").lower()
            if name == cfg["opt_out_command"]:
                self.opt.opt_out(event.user.username)
                await self._send_reply(event, cfg["messages"]["opt_out_ok"], {})
                return True
            if name == cfg["opt_in_command"]:
                self.opt.opt_in(event.user.username)
                await self._send_reply(event, cfg["messages"]["opt_in_ok"], {})
                return True
            if name == cfg["targets_command"]:
                await self._send_reply(event, self._targets_text(), {})
                return True
            for entry in cfg["entries"]:
                if name in entry["commands"]:
                    words = list(event.args or [])
                    if _uses_args(entry) and not entry["targets"]:
                        # the words are the text ("!sign GO TEAM 2"), not a target or a count
                        await self.fire(entry, event, target_words=[], count=1, via="command",
                                        text=args_text(words))
                        return True
                    typed, target_words = split_count(words)
                    count = command_count(entry, typed)
                    await self.fire(entry, event, target_words=target_words, count=count, via="command")
                    return True
            return False

        # plain chat: emoji / emote triggers (silent on failure)
        for entry, count in self.match_triggers(event, cfg["entries"]):
            mention = _MENTION.search(event.message or "")
            words = ["@" + mention.group(1)] if mention else []
            await self.fire(entry, event, target_words=words, count=count, via="emoji")
        return False

    def match_triggers(self, event: ChatEvent, entries: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], int]]:
        text = event.message or ""
        emote_names: List[str] = []
        for em in event.emotes or []:
            n = str((em or {}).get("name") or "")
            if n:
                emote_names.append(n.strip(":").lower())     # YouTube emoji names are ":like-this:"
        for m in _KICK_EMOTE.finditer(text):
            emote_names.append(m.group(2).lower())
        plain = _KICK_EMOTE.sub(" ", text)
        plain_norm = _norm_emoji(plain)
        words = [w.lower() for w in _WORD.findall(plain)]
        hits = []
        for entry in entries:
            count = 0
            for emo in entry["emoji"]:
                e = _norm_emoji(emo)
                if e:
                    count += plain_norm.count(e)
            for name in entry["emotes"]:
                n = name.strip(":").lower()
                count += emote_names.count(n)
                # third-party / YouTube text names that weren't in the emote list
                if n not in emote_names:
                    count += words.count(n)
            if count > 0:
                hits.append((entry, min(count, entry["max_per_message"])))
        return hits

    # ---------------- firing ----------------

    def _user_key(self, user: ChatUser) -> str:
        return f"{user.platform.value}:{(user.id or user.username or '').lower()}"

    def _is_admin(self, user: ChatUser) -> bool:
        return bool(self.perms and self.perms.has_permission(user, PermissionLevel.ADMIN))

    def _permission_ok(self, entry: Dict[str, Any], user: ChatUser) -> Tuple[bool, str]:
        perm = entry["permission"]
        admin = self._is_admin(user)
        if perm == "admin" and not admin:
            return False, "admins"
        if perm == "mod" and not (admin or user.is_mod or (self.perms and self.perms.has_permission(user, PermissionLevel.MOD))):
            return False, "mods"
        req = entry["require"]
        if req and not (admin or user.is_mod):
            ok = ("sub" in req and user.is_subscriber) or ("vip" in req and user.is_vip)
            if not ok:
                return False, " / ".join({"sub": "subs", "vip": "VIPs"}[r] for r in req)
        return True, ""

    def resolve_target(self, entry: Dict[str, Any], words: List[str], sender: ChatUser) -> Tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
        """
        Returns (target, error_key, ctx). target None + no error = untargeted effect.
        """
        allowed = entry["targets"]
        words = [w.strip() for w in words if w and w.strip()]
        word = words[0] if words else ""
        if not allowed:
            return None, None, {}
        if not word:
            if entry["default_target"] == "stage" and "stage" in allowed:
                return {"type": "stage", "name": ""}, None, {}
            if entry["default_target"] == "sender" and "user" in allowed:
                return {"type": "user", "name": sender.username}, None, {}
            if "stage" in allowed:
                return {"type": "stage", "name": ""}, None, {}
            return None, None, {}
        room = self.room_state
        if word.startswith("@"):
            name = word[1:].strip()
            return self._user_target(name, allowed, sender, room)
        # Names may be typed with spaces ("presenter 2", "big piano"): try the longest
        # run of words first, compared without case / spaces / _ - .
        spoken = self._spoken_target(words)
        if room:
            for n in range(min(3, len(words)), 0, -1):
                key = target_key(" ".join(words[:n]))
                typed = " ".join(words[:n])
                for t in room.get("targets") or []:
                    ids = [t.get("id"), t.get("label")] + list(t.get("aliases") or [])
                    if key in {target_key(i) for i in ids if i}:
                        if "stage" not in allowed:
                            return None, "target_not_allowed", {"target_kind": "stage spot", "target": typed}
                        return {"type": "stage", "name": str(t.get("id"))}, None, {}
                for g in room.get("guests") or []:
                    ids = [g.get("id"), g.get("name")] + list(g.get("aliases") or [])
                    if key in {target_key(i) for i in ids if i}:
                        if "guest" not in allowed:
                            return None, "target_not_allowed", {"target_kind": "guest", "target": typed}
                        return {"type": "guest", "name": str(g.get("id") or g.get("name"))}, None, {}
                for seat in room.get("seated") or []:
                    if target_key(seat) == key:
                        return self._user_target(str(seat), allowed, sender, room)
            return None, "bad_target", {"target": spoken}
        # no room info yet: pass the name through (spaces removed), the game falls back
        if "stage" in allowed:
            return {"type": "stage", "name": target_key(spoken)}, None, {}
        return None, "bad_target", {"target": spoken}

    @staticmethod
    def _spoken_target(words: List[str]) -> str:
        """What the chatter most likely meant as the name: a word, plus a number after it."""
        if len(words) >= 2 and words[1].isdigit():
            return words[0] + " " + words[1]
        return words[0] if words else ""

    def _user_target(self, name: str, allowed, sender: ChatUser, room) -> Tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
        if not name:
            return None, "bad_target", {"target": "@"}
        if "user" not in allowed:
            return None, "target_not_allowed", {"target_kind": "audience member", "target": "@" + name}
        if target_key(name) != target_key(sender.username):
            if not self.opt.targetable(name, self.cfg["targeting"]):
                return None, "opted_out", {"target": name}
        if room and room.get("seated") is not None:
            seated = {target_key(s) for s in room.get("seated") or []}
            if target_key(name) not in seated:
                return None, "bad_target", {"target": "@" + name}
        return {"type": "user", "name": name}, None, {}

    def _route(self, effect_id: str) -> Optional[str]:
        mode = self.cfg["send_to"]
        game = bool(self.game_clients)
        overlay_ok = any(e["id"] == effect_id and e.get("overlay") for e in EFFECT_CATALOG)
        if mode == "game":
            return "game" if game else None
        if mode == "overlay":
            return "overlay" if overlay_ok else None
        if game:
            return "game"
        return "overlay" if overlay_ok else None

    async def fire(
        self,
        entry: Dict[str, Any],
        event: ChatEvent,
        target_words: Optional[List[str]] = None,
        count: int = 1,
        via: str = "command",
        free: bool = False,
        text: str = "",
    ) -> Dict[str, Any]:
        """Run every rule; on success charge points and send the reaction.
        `text`: what the chatter typed after the command, for {args} in the settings."""
        cfg = self.cfg
        msgs = cfg["messages"]
        user = event.user
        loud = via != "emoji"   # emoji spam never gets chat replies
        base = {"user": _speaker(user), "reaction": entry["label"] or entry["id"],
                "cost": entry["cost"], "prefix": self.prefix(), "targets_cmd": cfg["targets_command"],
                "command": (entry["commands"] or [entry["id"]])[0]}

        async def reject(key: str, **extra) -> Dict[str, Any]:
            self.stats["rejected"] += 1
            if loud and key in msgs:
                await self._send_reply(event, msgs[key], {**base, **extra})
            return {"ok": False, "reason": key, **extra}

        usable, why = self.entry_usable(entry)
        if not usable:
            return {"ok": False, "reason": why}
        ok, who = self._permission_ok(entry, user)
        if not ok:
            return await reject("no_permission", who=who)

        if _uses_args(entry) and not text:
            return await reject("need_text")
        target, err, ctx = self.resolve_target(entry, target_words or [], user)
        if err:
            return await reject(err, **ctx)
        if entry["effect"] in TARGET_REQUIRED and (
                not target or (target.get("type") == "user" and target_key(target.get("name")) == target_key(user.username))):
            return await reject("need_target")

        route = self._route(entry["effect"])
        if route is None:
            return await reject("stage_closed")

        ukey = f"u|{entry['id']}|{self._user_key(user)}"
        gkey = f"g|{entry['id']}"
        tkey = f"t|{entry['id']}|{(target or {}).get('type', '')}:{(target or {}).get('name', '').lower()}"
        waits = [self.gate.remaining(ukey, entry["cooldown_user_sec"]),
                 self.gate.remaining(gkey, entry["cooldown_global_sec"])]
        if target and target.get("type") in ("user", "guest"):
            waits.append(self.gate.remaining(tkey, entry["cooldown_target_sec"]))
        wait = max(waits)
        if wait > 0:
            return await reject("cooldown", seconds=int(wait + 0.999))

        # points
        count = max(1, int(count))
        charged, uid, balance = 0, None, None
        free = free or (cfg["admins_free"] and self._is_admin(user))
        if entry["cost"] > 0 and not free:
            if not self.store:
                return {"ok": False, "reason": "no store"}
            uid = await self.store.get_or_create_user(
                user.platform.value, user.id, user.username, user.display_name
            )
            ok, balance = await self.store.spend_points(uid, entry["cost"], count, f"reaction {entry['id']}", "reaction")
            if not ok:
                return await reject("no_points", balance=balance)
            count = ok  # spend_points returns how many it could afford (≥1)
            charged = entry["cost"] * count
            self.stats["points_spent"] += charged

        self.gate.touch(ukey)
        self.gate.touch(gkey)
        if target and target.get("type") in ("user", "guest"):
            self.gate.touch(tkey)

        rid = "r-" + uuid.uuid4().hex[:12]
        payload = {
            "type": "reaction",
            "data": {
                "id": rid,
                "reaction": entry["id"],
                "label": entry["label"],
                "effect": entry["effect"],
                "params": self._params_for(entry, text=text, user=user),
                "count": count,
                "from": user_ref(user),
                "target": target,
                "route": route,
                "message": event.message or "",
                "cost": charged,
                "ts": time.time(),
            },
        }
        if charged:
            self.pending[rid] = {"uid": uid, "amount": charged, "ts": time.time(), "reaction": entry["id"]}
        delivered = await self._deliver(payload, route)
        if not delivered and charged:
            await self._refund(rid, "not delivered")
            return {"ok": False, "reason": "not delivered"}
        self.stats["fired"] += 1
        self.recent.appendleft({
            "id": rid, "ts": payload["data"]["ts"], "reaction": entry["id"], "effect": entry["effect"],
            "from": user.username, "platform": user.platform.value, "target": target, "count": count,
            "route": route, "cost": charged, "outcome": "sent",
        })
        self._expire_pending()
        if entry["reply_ok"] and loud or (entry["reply_ok"] and charged):
            await self._send_reply(event, entry["reply_ok"], {**base, "cost": charged, "count": count,
                                                               "target": (target or {}).get("name", "")})
        return {"ok": True, "id": rid, "route": route, "target": target, "count": count, "charged": charged}

    def _params_for(self, entry: Dict[str, Any], text: str = "", user: Optional[ChatUser] = None) -> Dict[str, Any]:
        return self.effect_params(entry["effect"], entry["params"] or {}, text=text, user=user)

    def effect_params(self, effect: str, given: Optional[Dict[str, Any]] = None, text: str = "",
                      user: Optional[ChatUser] = None) -> Dict[str, Any]:
        """Effect defaults + the given settings, with {args} / {user} filled in and a picture
        (`object_image`) for an "img:name" object or an emote name Core has seen in chat."""
        eff = effect_by_id(self.known_effects(), effect) or {}
        params: Dict[str, Any] = {}
        for p in eff.get("params") or []:
            if isinstance(p, dict) and p.get("name"):
                params[p["name"]] = p.get("default")
        params.update(given or {})
        for k, v in list(params.items()):
            if isinstance(v, str) and _ARGS_TOKEN in v:
                params[k] = v.replace(_ARGS_TOKEN, text).strip()
        pic = None
        if self.images is not None:
            pic = self.images.resolve_object(params.get("object"))
        if pic is None and params.get("object"):
            pic = self.emotes.picture(params.get("object"))
        if pic:
            params["object_image"] = pic
        return params

    async def play(
        self,
        effect: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        label: str = "",
        reaction: str = "",
        from_user: Optional[Dict[str, Any]] = None,
        target: Optional[Dict[str, Any]] = None,
        crowd: Optional[List[Dict[str, Any]]] = None,
        count: int = 1,
        charge: Optional[Dict[str, Any]] = None,
        message: str = "",
    ) -> Optional[str]:
        """Plays an effect for Core itself (chat games, combos, the hype meter), without the
        reaction rules. `crowd`: the people it's about (a combo's chatters), as `from` blocks.
        `charge` {uid, amount}: points already taken, refunded if the game drops it.
        Returns the reaction id, or None when nothing can play it right now."""
        route = self._route(effect)
        if route is None:
            return None
        rid = "r-" + uuid.uuid4().hex[:12]
        data = {
            "id": rid,
            "reaction": reaction or effect,
            "label": label or reaction or effect,
            "effect": effect,
            "params": self.effect_params(effect, params),
            "count": max(1, int(count)),
            "from": from_user or {"platform": "core", "id": "stream-core", "username": "stream_core",
                                  "display_name": "Stream Core"},
            "target": target,
            "route": route,
            "message": message,
            "cost": int((charge or {}).get("amount") or 0),
            "ts": time.time(),
            "system": True,
        }
        if crowd:
            data["crowd"] = crowd[:60]
        if charge and charge.get("uid") and charge.get("amount"):
            self.pending[rid] = {"uid": charge["uid"], "amount": int(charge["amount"]), "ts": time.time(),
                                 "reaction": reaction or effect}
        ok = await self._deliver({"type": "reaction", "data": data}, route)
        if not ok:
            if charge:
                await self._refund(rid, "not delivered")
            return None
        self.recent.appendleft({
            "id": rid, "ts": data["ts"], "reaction": data["reaction"], "effect": effect,
            "from": data["from"].get("username", ""), "platform": data["from"].get("platform", ""),
            "target": target, "count": data["count"], "route": route, "cost": data["cost"], "outcome": "sent",
        })
        return rid

    async def _deliver(self, payload: dict, route: str) -> bool:
        if route == "game":
            sent = False
            for ws in list(self.game_clients):
                try:
                    await ws.send_json(payload)
                    sent = True
                except Exception:
                    self.detach(ws)
            return sent
        if self._broadcast:
            try:
                await self._broadcast(payload)
                return True
            except Exception:
                log.exception("reaction broadcast failed")
                return False
        return False

    async def _refund(self, rid: str, why: str) -> bool:
        p = self.pending.pop(rid, None)
        if not p or not self.store or not p.get("uid"):
            return False
        await self.store.adjust_points(p["uid"], int(p["amount"]), f"refund {p['reaction']} ({why})", "reaction")
        self.stats["refunded"] += 1
        for r in self.recent:
            if r["id"] == rid:
                r["outcome"] = "refunded"
        return True

    def _expire_pending(self, max_age: float = 120.0) -> None:
        now = time.time()
        for rid in [k for k, v in self.pending.items() if now - v["ts"] > max_age]:
            self.pending.pop(rid, None)

    def _targets_text(self) -> str:
        msgs = self.cfg["messages"]
        room = self.room_state
        if not room:
            return msgs["targets_none"] if self.game_clients or self.cfg["send_to"] == "game" else fmt(msgs["targets"], targets="stage")
        names = [str(t.get("id")) for t in room.get("targets") or [] if t.get("id")]
        names += [str(g.get("name") or g.get("id")) for g in room.get("guests") or []]
        return fmt(msgs["targets"], targets=", ".join(names) or "stage")

    async def _send_reply(self, event: ChatEvent, template: str, ctx: Dict[str, Any]) -> None:
        if not self.cfg["chat_replies"] or not template or not self._reply:
            return
        full = {"user": _speaker(event.user), "prefix": self.prefix(),
                "opt_in_cmd": self.cfg["opt_in_command"], "opt_out_cmd": self.cfg["opt_out_command"],
                "targets_cmd": self.cfg["targets_command"], **ctx}
        try:
            await self._reply(event, fmt(template, **full))
        except Exception:
            log.exception("reaction reply failed")

    # ---------------- game link (WebSocket messages) ----------------

    def detach(self, ws) -> None:
        if ws in self.game_clients:
            info = self.game_clients.pop(ws)
            log.info("Game client left: %s", info.get("client"))
            if not self.game_clients:
                self.room_state = None

    async def on_client_message(self, ws, msg: Dict[str, Any]) -> None:
        mtype = str(msg.get("type") or "")
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        if mtype == "hello":
            effects = [e for e in (data.get("effects") or []) if isinstance(e, dict) and e.get("id")]
            self.game_clients[ws] = {
                "client": str(data.get("client") or "game")[:40],
                "protocol": data.get("protocol"),
                "since": time.time(),
            }
            if effects:
                self.game_effects = effects
                self._save_caps()
            log.info("Game client hello: %s (%d effects)", self.game_clients[ws]["client"], len(effects))
            await ws.send_json({"type": "hello_ok", "data": {
                "protocol": PROTOCOL,
                "reactions_enabled": self.active(),
                "effects_known": [e["id"] for e in self.known_effects()],
            }})
            return
        if ws not in self.game_clients:
            return  # only a hello'd game may use the rest
        if mtype == "room_state":
            self.room_state = {
                "room": str(data.get("room") or ""),
                "targets": [t for t in (data.get("targets") or []) if isinstance(t, dict)],
                "guests": [g for g in (data.get("guests") or []) if isinstance(g, dict)],
                "seated": [str(s) for s in (data.get("seated") or [])] if data.get("seated") is not None else None,
                "ts": time.time(),
            }
        elif mtype == "reaction_result":
            rid = str(data.get("id") or "")
            outcome = str(data.get("outcome") or "")
            for r in self.recent:
                if r["id"] == rid:
                    r["outcome"] = outcome or r["outcome"]
            if outcome == "dropped" and self.cfg["refund_if_dropped"]:
                await self._refund(rid, "dropped by game")
            else:
                self.pending.pop(rid, None)
        elif mtype == "say":
            await self.game_say(str(data.get("text") or ""))
        elif mtype == "stage_state":
            self.stage_state = {k: str(v)[:20] for k, v in data.items() if k in ("curtain",)}
            if self._broadcast:
                await self._broadcast({"type": "stage_state", "data": dict(self.stage_state)})
        elif mtype == "overlay":
            if self._broadcast:
                await self._broadcast({"type": "game_overlay", "data": data})

    async def send_stage(self, action: str, value: str) -> bool:
        """Stage commands for the game (Stream Rooms): {"type":"stage","data":{action, value}},
        e.g. action "curtain", value open / close / reveal / toggle. False when no game is connected."""
        sent = False
        for ws in list(self.game_clients):
            try:
                await ws.send_json({"type": "stage", "data": {"action": action, "value": value}})
                sent = True
            except Exception:
                self.detach(ws)
        return sent

    async def game_say(self, text: str) -> bool:
        cfg = self.cfg
        text = " ".join(text.split())[: cfg["say_max_chars"]]
        if not text or not self._say or cfg["say_per_minute"] <= 0:
            return False
        now = time.time()
        while self._say_times and now - self._say_times[0] > 60:
            self._say_times.popleft()
        if len(self._say_times) >= cfg["say_per_minute"]:
            log.info("game say rate-limited: %s", text)
            return False
        self._say_times.append(now)
        await self._say(text, None)
        return True

    # ---------------- admin ----------------

    def status(self) -> Dict[str, Any]:
        cfg = self.cfg
        entries = []
        for e in cfg["entries"]:
            usable, why = self.entry_usable(e)
            entries.append({"id": e["id"], "usable": usable, "why": why})
        return {
            "enabled": cfg["enabled"],
            "active": self.active(),
            "points_enabled": self.points_enabled(),
            "game_connected": bool(self.game_clients),
            "game_clients": [dict(v) for v in self.game_clients.values()],
            "stage": dict(self.stage_state),
            "room_state": self.room_state,
            "stats": dict(self.stats),
            "recent": list(self.recent),
            "entries": entries,
        }
