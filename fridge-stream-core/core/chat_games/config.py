"""`chat_games:` settings — defaults, cleaning, and the field list the admin page draws.

Everything is off until `chat_games.enabled` is true (and the `chat_games` command group is
on). Each feature then has its own `enabled` switch, command names and numbers.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

_SLUG = re.compile(r"[^a-z0-9_\-]+")


def slug(v: Any) -> str:
    return _SLUG.sub("", str(v or "").strip().lstrip("!").lower())


# Emote combo moods. Emote names come from each platform's global set (they can change);
# channel / BTTV / FFZ / 7TV emotes can be added in the admin page. "{emote}" as an object
# means "the emote the crowd used most".
DEFAULT_MOODS: List[Dict[str, Any]] = [
    {"id": "laugh", "label": "Laugh", "enabled": True,
     "emotes": ["KEKW", "LULW", "HaHaa", "KEKLEO", "LUL", "OMEGALUL",
                "face-purple-smiling-tears", "face-fuchsia-tongue-out"],
     "emoji": ["😂", "🤣"],
     "effects": [{"effect": "float_up", "params": {"object": "{emote}", "count": 3, "duration_sec": 3}},
                 {"effect": "crowd_motion", "params": {"style": "wiggle", "who": "crowd", "duration_sec": 2.5}}]},
    {"id": "hype", "label": "Hype", "enabled": True,
     "emotes": ["PogU", "OOOO", "GIGACHAD", "AURAPULSE", "PogChamp", "Kreygasm",
                "face-blue-star-eyes", "rocket-red-countdown-liftoff", "trophy-yellow-smiling"],
     "emoji": ["🔥", "😮", "🚀"],
     "effects": [{"effect": "confetti", "params": {"count": 120}},
                 {"effect": "crowd_motion", "params": {"style": "cheer", "who": "all", "duration_sec": 4}}]},
    {"id": "clap", "label": "Clap", "enabled": True,
     "emotes": ["Clap", "HYPERCLAP", "PeepoClap", "hands-yellow-heart-red"],
     "emoji": ["👏", "🙌"],
     "effects": [{"effect": "meter", "params": {"meter_id": "applause", "goal": 20, "decay_sec": 20,
                                                "payoff_effect": "confetti"}}]},
    {"id": "love", "label": "Love", "enabled": True,
     "emotes": ["catKISS", "<3", "bleedPurple", "face-red-heart-shape", "eyes-pink-heart-shape",
                "face-blue-heart-eyes", "virtualhug"],
     "emoji": ["❤️", "💜", "😍"],
     "effects": [{"effect": "float_up", "params": {"object": "❤️", "count": 4, "duration_sec": 3}}]},
    {"id": "sad", "label": "Sad", "enabled": True,
     "emotes": ["Sadge", "Prayge", "BibleThump", "NotLikeThis", "face-purple-crying", "face-pink-tears",
                "eyes-purple-crying"],
     "emoji": ["😢", "😭"],
     "effects": [{"effect": "fall_down", "params": {"object": "😢", "count": 18, "duration_sec": 5}}]},
    {"id": "dance", "label": "Dance", "enabled": True,
     "emotes": ["vibePls", "ratJAM", "catblobDance", "duckPls", "DanceDance", "GnomeDisco", "ODAJAM", "peepoDJ",
                "EDMusiC", "catJAM", "person-pink-swaying-hair", "face-turquoise-music-note"],
     "emoji": ["💃", "🕺", "🎶"],
     "effects": [{"effect": "crowd_motion", "params": {"style": "dance", "who": "all", "duration_sec": 5}}]},
    {"id": "shock", "label": "Shock / huh?", "enabled": True,
     "emotes": ["kkHuh", "modCheck", "SUSSY", "WeirdChamp", "WutFace", "monkaS", "face-fuchsia-wide-eyes",
                "face-blue-question-mark", "face-orange-biting-nails"],
     "emoji": ["😱", "🤨", "❓"],
     "effects": [{"effect": "camera_shake", "params": {"strength": 0.25, "duration_sec": 0.5}}]},
    {"id": "sleepy", "label": "Sleepy", "enabled": True,
     "emotes": ["ResidentSleeper", "face-blue-droopy-eyes", "face-turquoise-drinking-coffee"],
     "emoji": ["😴", "💤"],
     "effects": [{"effect": "lights", "params": {"mode": "dim", "duration_sec": 4}}]},
    {"id": "bye", "label": "Bye / GG", "enabled": True,
     "emotes": ["KEKBye", "EZ", "HeyGuys", "GG", "hand-pink-waving", "text-green-game-over"],
     "emoji": ["👋", "🏆"],
     "effects": [{"effect": "stadium_wave", "params": {"speed": 1.0}}]},
]

DEFAULT_TITLES: List[Dict[str, Any]] = [
    {"streams": 5, "title": "Regular"},
    {"streams": 10, "title": "Die-hard"},
    {"streams": 25, "title": "Legend"},
]

DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "replies": True,            # post answers (reply screen / replies overlay)
    "board_hold_sec": 12,       # a finished poll / prediction / heist stays up this long
    "combos": {"enabled": True, "min_people": 3, "window_sec": 10, "cooldown_sec": 20,
               "moods": copy.deepcopy(DEFAULT_MOODS)},
    "hype": {"enabled": True, "window_sec": 60, "levels": [5, 10, 20], "cooldown_sec": 90, "show_meter": True,
             "level_effects": [
                 [{"effect": "crowd_motion", "params": {"style": "cheer", "who": "all", "duration_sec": 4}}],
                 [{"effect": "confetti", "params": {"count": 180}},
                  {"effect": "crowd_motion", "params": {"style": "jump", "who": "all", "duration_sec": 3}}],
                 [{"effect": "stadium_wave", "params": {"speed": 1.2}},
                  {"effect": "fireworks", "params": {"count": 8, "duration_sec": 5}}],
             ]},
    "tug": {"enabled": True, "cheer_command": "cheer", "boo_command": "boo", "round_sec": 30,
            "cooldown_sec": 45, "per_user_gap_sec": 1.0},
    "launch": {"enabled": True, "command": "launch", "people": 5, "window_sec": 60, "cooldown_sec": 600},
    "claim": {"enabled": True, "command": "claim", "points": 50},
    "streak": {"enabled": True, "command": "streak", "gap_hours": 4, "titles": copy.deepcopy(DEFAULT_TITLES),
               "title_from": "best", "show_titles": True},
    "seat": {"enabled": True, "command": "seat", "front_cost": 50, "cooldown_sec": 60,
             "swap_command": "swap", "swap_sec": 60},
    "predict": {"enabled": True, "command": "predict", "min_bet": 1, "max_bet": 10000, "auto_lock_sec": 0},
    "duel": {"enabled": True, "command": "duel", "accept_command": "accept", "decline_command": "decline",
             "min_bet": 10, "max_bet": 1000, "accept_sec": 60, "cooldown_sec": 60, "loser_object": "🍅"},
    "slots": {"enabled": True, "command": "slots", "min_bet": 5, "max_bet": 200, "cooldown_sec": 30},
    "heist": {"enabled": True, "command": "heist", "join_command": "join", "min_bet": 10, "max_bet": 1000,
              "join_sec": 60, "cooldown_sec": 600, "base_success": 0.45, "per_member": 0.04,
              "max_success": 0.8, "caught_chance": 0.2, "payout": 1.8},
    "trivia": {"enabled": True, "command": "trivia", "answer_command": "answer", "points": 100,
               "time_sec": 45, "auto_every_min": 0},
    "poll": {"enabled": True, "command": "poll", "vote_command": "vote", "max_options": 5, "default_sec": 0},
    "rate": {"enabled": True, "command": "rate", "window_sec": 120, "open_on_first": True},
    "request": {"enabled": True, "command": "request", "bump_command": "bump", "queue_command": "queue",
                "bump_cost": 100, "max_per_user": 2, "max_queue": 50},
    "moment": {"enabled": True, "commands": ["clip", "moment"], "cooldown_sec": 30, "merge_sec": 20},
    "stage": {"enabled": True, "command": "curtain"},     # mods: !curtain open | close | reveal
}

# (feature, key) -> (lo, hi) for numbers
_RANGES = {
    ("board_hold_sec",): (2, 120),
    ("combos", "min_people"): (1, 50), ("combos", "window_sec"): (2, 120), ("combos", "cooldown_sec"): (0, 3600),
    ("hype", "window_sec"): (10, 600), ("hype", "cooldown_sec"): (0, 3600),
    ("tug", "round_sec"): (5, 600), ("tug", "cooldown_sec"): (0, 3600), ("tug", "per_user_gap_sec"): (0, 30),
    ("launch", "people"): (2, 200), ("launch", "window_sec"): (10, 600), ("launch", "cooldown_sec"): (0, 86400),
    ("claim", "points"): (0, 1_000_000),
    ("streak", "gap_hours"): (0.5, 72),
    ("seat", "front_cost"): (0, 1_000_000), ("seat", "cooldown_sec"): (0, 3600), ("seat", "swap_sec"): (10, 600),
    ("predict", "min_bet"): (1, 1_000_000), ("predict", "max_bet"): (1, 10_000_000), ("predict", "auto_lock_sec"): (0, 3600),
    ("duel", "min_bet"): (1, 1_000_000), ("duel", "max_bet"): (1, 10_000_000), ("duel", "accept_sec"): (10, 600),
    ("duel", "cooldown_sec"): (0, 3600),
    ("slots", "min_bet"): (1, 1_000_000), ("slots", "max_bet"): (1, 10_000_000), ("slots", "cooldown_sec"): (0, 3600),
    ("heist", "min_bet"): (1, 1_000_000), ("heist", "max_bet"): (1, 10_000_000), ("heist", "join_sec"): (10, 600),
    ("heist", "cooldown_sec"): (0, 86400), ("heist", "base_success"): (0, 1), ("heist", "per_member"): (0, 0.5),
    ("heist", "max_success"): (0, 1), ("heist", "caught_chance"): (0, 1), ("heist", "payout"): (1, 20),
    ("trivia", "points"): (0, 1_000_000), ("trivia", "time_sec"): (10, 600), ("trivia", "auto_every_min"): (0, 240),
    ("poll", "max_options"): (2, 9), ("poll", "default_sec"): (0, 3600),
    ("rate", "window_sec"): (10, 3600),
    ("request", "bump_cost"): (0, 1_000_000), ("request", "max_per_user"): (1, 50), ("request", "max_queue"): (1, 500),
    ("moment", "cooldown_sec"): (0, 3600), ("moment", "merge_sec"): (0, 600),
}

# keys holding one command name each
_COMMAND_KEYS = {"command", "cheer_command", "boo_command", "accept_command", "decline_command", "swap_command",
                 "join_command", "answer_command", "vote_command", "bump_command", "queue_command"}


def _num(v: Any, default: float, lo: float, hi: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


def _effects(raw: Any) -> List[Dict[str, Any]]:
    out = []
    for e in raw if isinstance(raw, list) else []:
        if isinstance(e, dict) and str(e.get("effect") or "").strip():
            out.append({"effect": str(e["effect"]).strip(),
                        "params": dict(e.get("params")) if isinstance(e.get("params"), dict) else {}})
    return out


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = re.split(r"[,\n]", v)
    return [str(x).strip() for x in v if str(x).strip()]


def normalize_moods(raw: Any) -> List[Dict[str, Any]]:
    moods, seen = [], set()
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict):
            continue
        mid = slug(m.get("id") or m.get("label"))
        if not mid or mid in seen:
            continue
        seen.add(mid)
        moods.append({
            "id": mid,
            "label": str(m.get("label") or mid),
            "enabled": bool(m.get("enabled", True)),
            "emotes": _as_list(m.get("emotes")),
            "emoji": _as_list(m.get("emoji")),
            "effects": _effects(m.get("effects")),
        })
    return moods


def normalize_config(raw: Any) -> Dict[str, Any]:
    """The whole block with defaults. Unknown keys are kept (a Config save merges YAML)."""
    raw = raw if isinstance(raw, dict) else {}
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in raw.items():
        if isinstance(cfg.get(k), dict) and isinstance(v, dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    cfg["enabled"] = bool(cfg["enabled"])
    cfg["replies"] = bool(cfg["replies"])
    cfg["board_hold_sec"] = _num(cfg["board_hold_sec"], 12, 2, 120)
    for feat, block in cfg.items():
        if not isinstance(block, dict) or feat not in DEFAULTS:
            continue
        block["enabled"] = bool(block.get("enabled", True))
        for key, val in list(block.items()):
            if key in _COMMAND_KEYS:
                block[key] = slug(val) or DEFAULTS[feat][key]
            rng = _RANGES.get((feat, key))
            if rng:
                block[key] = _num(val, DEFAULTS[feat][key], *rng)
                if isinstance(DEFAULTS[feat][key], int) and not isinstance(DEFAULTS[feat][key], bool):
                    block[key] = int(block[key])
    cfg["moment"]["commands"] = [slug(c) for c in _as_list(cfg["moment"].get("commands")) if slug(c)] or ["clip", "moment"]
    cfg["combos"]["moods"] = normalize_moods(cfg["combos"].get("moods"))
    levels = []
    for x in cfg["hype"].get("levels") or []:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 1000:
            levels.append(n)
    cfg["hype"]["levels"] = sorted(set(levels)) or [5, 10, 20]
    cfg["hype"]["level_effects"] = [_effects(x) for x in (cfg["hype"].get("level_effects") or [])]
    cfg["hype"]["show_meter"] = bool(cfg["hype"].get("show_meter", True))
    titles = []
    for t in cfg["streak"].get("titles") or []:
        if isinstance(t, dict) and str(t.get("title") or "").strip():
            titles.append({"streams": int(_num(t.get("streams"), 5, 1, 10000)), "title": str(t["title"]).strip()[:24]})
    cfg["streak"]["titles"] = sorted(titles, key=lambda t: t["streams"])
    cfg["streak"]["title_from"] = "current" if cfg["streak"].get("title_from") == "current" else "best"
    cfg["streak"]["show_titles"] = bool(cfg["streak"].get("show_titles", True))
    cfg["rate"]["open_on_first"] = bool(cfg["rate"].get("open_on_first", True))
    cfg["duel"]["loser_object"] = str(cfg["duel"].get("loser_object") or "🍅")[:40]
    for feat in ("predict", "duel", "slots", "heist"):
        b = cfg[feat]
        b["max_bet"] = max(b["max_bet"], b["min_bet"])
    return cfg


# ----------------------------------------------------------------------
# Admin form: one section per feature, fields drawn by admin.js.
# kind: bool | number | text | command | list (comma separated)
# ----------------------------------------------------------------------

def _f(key, label, kind="number", hint="", **extra):
    d = {"key": key, "label": label, "kind": kind, "hint": hint}
    d.update(extra)
    return d


FORM: List[Dict[str, Any]] = [
    {"id": "combos", "title": "Emote combos", "sheet": "Emote combos",
     "about": "When enough people use emotes from the same mood within a few seconds, the whole room reacts.",
     "fields": [_f("min_people", "People needed"), _f("window_sec", "Within (s)"),
                _f("cooldown_sec", "Same mood again after (s)")]},
    {"id": "hype", "title": "Hype meter", "sheet": "Crowd moments",
     "about": "Counts different people chatting in the last minute. Each level sets off a crowd moment.",
     "fields": [_f("window_sec", "Counts the last (s)"), _f("levels", "Levels (people)", "list"),
                _f("cooldown_sec", "Same level again after (s)"), _f("show_meter", "Show the meter", "bool")]},
    {"id": "tug", "title": "Cheer vs boo", "sheet": "Crowd moments",
     "about": "A tug of war. The first !cheer or !boo starts a round; the winning side gets a reveal.",
     "fields": [_f("cheer_command", "Cheer command", "command"), _f("boo_command", "Boo command", "command"),
                _f("round_sec", "Round (s)"), _f("cooldown_sec", "Next round after (s)")]},
    {"id": "launch", "title": "Group launch", "sheet": "Crowd moments",
     "about": "Enough people type it within the window and the room goes big.",
     "fields": [_f("command", "Command", "command"), _f("people", "People needed"), _f("window_sec", "Window (s)"),
                _f("cooldown_sec", "Recharge (s)")]},
    {"id": "claim", "title": "Daily claim", "sheet": "Points",
     "about": "Free points once per stream.", "needs_points": True,
     "fields": [_f("command", "Command", "command"), _f("points", "Points")]},
    {"id": "streak", "title": "Streaks + titles", "sheet": "Regulars",
     "about": "Streams in a row. A new stream starts when chat has been quiet for the gap below.",
     "fields": [_f("command", "Command", "command"), _f("gap_hours", "New stream after a quiet gap of (hours)"),
                _f("title_from", "Titles use", "select", options=["best", "current"]),
                _f("show_titles", "Show titles on name tags + credits", "bool")]},
    {"id": "seat", "title": "Seats", "sheet": "Your seat",
     "about": "!seat front|back moves you (front costs points). !swap @name offers a trade.",
     "fields": [_f("command", "Seat command", "command"), _f("front_cost", "Front row costs"),
                _f("cooldown_sec", "Cooldown (s)"), _f("swap_command", "Swap command", "command"),
                _f("swap_sec", "Swap offer lasts (s)")]},
    {"id": "predict", "title": "Predictions", "sheet": "Games", "needs_points": True,
     "about": "Mods open one with !predict open Question? | A | B. Winners split the pot.",
     "fields": [_f("command", "Command", "command"), _f("min_bet", "Smallest bet"), _f("max_bet", "Biggest bet"),
                _f("auto_lock_sec", "Lock after (s, 0 = by hand)")]},
    {"id": "duel", "title": "Duels", "sheet": "Games", "needs_points": True,
     "about": "Coin flip for points. The loser gets something thrown at them.",
     "fields": [_f("command", "Command", "command"), _f("accept_command", "Accept", "command"),
                _f("decline_command", "Decline", "command"), _f("min_bet", "Smallest bet"),
                _f("max_bet", "Biggest bet"), _f("accept_sec", "Answer within (s)"),
                _f("cooldown_sec", "Cooldown (s)"), _f("loser_object", "Thrown at the loser", "text")]},
    {"id": "slots", "title": "Slots", "sheet": "Games", "needs_points": True,
     "about": "Three reels. Capped bets, with a cooldown.",
     "fields": [_f("command", "Command", "command"), _f("min_bet", "Smallest bet"), _f("max_bet", "Biggest bet"),
                _f("cooldown_sec", "Cooldown (s)")]},
    {"id": "heist", "title": "Heist", "sheet": "Games", "needs_points": True,
     "about": "Someone starts it, others join; the crew's fate plays out on the reply screen.",
     "fields": [_f("command", "Start", "command"), _f("join_command", "Join", "command"),
                _f("min_bet", "Smallest stake"), _f("max_bet", "Biggest stake"), _f("join_sec", "Join time (s)"),
                _f("cooldown_sec", "Next heist after (s)"), _f("base_success", "Success chance (0-1)"),
                _f("per_member", "Extra chance per member"), _f("max_success", "Best chance"),
                _f("caught_chance", "Chance each member is caught"), _f("payout", "Payout (x stake)")]},
    {"id": "trivia", "title": "Trivia", "sheet": "Games",
     "about": "Questions from config/trivia.json. First right !answer wins points and a spotlight.",
     "fields": [_f("command", "Mod command to ask", "command"), _f("answer_command", "Answer", "command"),
                _f("points", "Points for a right answer"), _f("time_sec", "Time to answer (s)"),
                _f("auto_every_min", "Ask one every (min, 0 = only by hand)")]},
    {"id": "poll", "title": "Polls", "sheet": "What's on",
     "about": "Mods: !poll Question? | A | B | C, then !poll end. Chat votes !1 !2 !3.",
     "fields": [_f("command", "Mod command", "command"), _f("vote_command", "Vote command", "command"),
                _f("max_options", "Most options"), _f("default_sec", "Ends after (s, 0 = by hand)")]},
    {"id": "rate", "title": "Ratings", "sheet": "What's on",
     "about": "!rate 1-10. The average goes on screen and into the end credits.",
     "fields": [_f("command", "Command", "command"), _f("window_sec", "Voting stays open (s)"),
                _f("open_on_first", "The first !rate opens voting", "bool")]},
    {"id": "request", "title": "Requests", "sheet": "What's on",
     "about": "!request adds to the queue. !bump spends points to move yours up.",
     "fields": [_f("command", "Request", "command"), _f("bump_command", "Bump", "command"),
                _f("queue_command", "Show the queue", "command"), _f("bump_cost", "Bump costs"),
                _f("max_per_user", "Requests each"), _f("max_queue", "Queue size")]},
    {"id": "stage", "title": "Stage curtain", "sheet": "For mods",
     "about": "Mods: !curtain open | close | reveal (Stream Rooms' curtain in front of the main screen).",
     "fields": [_f("command", "Command", "command")]},
    {"id": "moment", "title": "Moments", "sheet": "What's on",
     "about": "!clip marks this moment with the stream time, so it's easy to find later.",
     "fields": [_f("commands", "Commands", "list"), _f("cooldown_sec", "Cooldown (s)"),
                _f("merge_sec", "Marks this close together count as one (s)")]},
]
