"""
The overlay pages Core serves and every switch each one takes on its URL.

This is the one list behind the dashboard's **Sources & overlays** page: its rows, the
**Customise** panel (one control per switch, which writes the address for OBS), and the
help text. A page that gains a switch gets one more entry here and the dashboard shows it.
Plugins add their own pages the same way (``params`` on an overlay entry in ``plugin.json``).

Switch types: ``bool`` (a tick box; ``on`` / ``off`` are the values the page reads and
``default`` is what the page does without the key, so only a change is written into the
address), ``tri`` (dashboard setting / on / off), ``number``, ``text``, ``select``
(``options`` = [[value, label], ...]) and ``multi`` (tick boxes joined with commas).
"""

from __future__ import annotations

from typing import Any

PLATFORMS = [["kick", "Kick"], ["twitch", "Twitch"], ["youtube", "YouTube"]]
# Every alert kind with a short label; keep in sync with KINDS in core/alerts.py.
ALERT_KINDS = [["follow", "Follow"], ["subscribe", "Sub / member"], ["resub", "Resub"], ["gift", "Gifted subs"],
               ["raid", "Raid"], ["host", "Host"], ["bits", "Bits"], ["superchat", "Super Chat"],
               ["supersticker", "Super Sticker"], ["jewels", "YouTube gift"], ["kicks", "KICKs"],
               ["donation", "Donation"], ["member", "YouTube member"], ["member_milestone", "Member milestone"],
               ["member_gift", "Gifted memberships"],
               ["powerup", "Bits power-up"], ["celebration", "Celebration"], ["charity", "Charity"],
               ["hypetrain", "Hype Train"], ["flag", "Chat flag"]]
# Metrics overlay modules; same names as overlay.modules in core/config.py DEFAULTS.
METRIC_MODULES = ["health", "food", "xp", "deaths", "armor", "viewers", "cpm", "power", "effects", "inventory"]


# Builders for one switch entry (the dict shape the dashboard's Customise panel reads).
def _bool(key: str, label: str, default: bool, help_text: str = "", on: str = "1", off: str = "0") -> dict[str, Any]:
    return {"key": key, "label": label, "type": "bool", "default": default, "on": on, "off": off, "help": help_text}


def _tri(key: str, label: str, help_text: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "type": "tri", "default": "", "help": help_text,
            "options": [["", "Dashboard setting"], ["1", "On"], ["0", "Off"]]}


def _num(key: str, label: str, default: Any = "", help_text: str = "", lo: float | None = None,
         hi: float | None = None, step: float | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"key": key, "label": label, "type": "number", "default": default, "help": help_text}
    if lo is not None:
        d["min"] = lo
    if hi is not None:
        d["max"] = hi
    if step is not None:
        d["step"] = step
    return d


def _text(key: str, label: str, default: str = "", help_text: str = "", placeholder: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "type": "text", "default": default, "help": help_text, "placeholder": placeholder}


def _select(key: str, label: str, options: list, default: str = "", help_text: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "type": "select", "default": default, "options": options, "help": help_text}


def _multi(key: str, label: str, options: list, help_text: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "type": "multi", "default": [], "options": options, "help": help_text}


# ``file`` is under /overlay/. ``settings`` are dashboard pages for the same overlay.
# ``config`` fields are config.yaml values the overlay reads (saved from the same panel).
OVERLAYS: list[dict[str, Any]] = [
    {
        "id": "chat",
        "file": "chat.html",
        "name": "Chat overlay",
        "notes": "Transparent Webpage source — chat with emotes, badges and replies from every platform",
        "params": [
            _select("platform", "Platform", [["", "All platforms"], ["kick", "Kick only"], ["twitch", "Twitch only"],
                                             ["youtube", "YouTube only"]]),
            _multi("platforms", "Or a set of platforms", PLATFORMS, "Tick two for a pair; leave empty with the choice above"),
            _bool("badges", "Platform letters (K / T / Y)", True),
            _select("skin", "Skin", [["", "Dashboard setting"], ["classic", "Classic"], ["plain", "Plain"],
                                     ["custom", "Custom CSS only"]]),
            _num("hide", "Hide messages after (seconds)", "", "Empty = dashboard setting, 0 = keep them", 0, 600, 1),
            _tri("top", "Newest message on top"),
            _tri("avatars", "Chatter profile pictures"),
            _tri("sound", "Sounds"),
            _select("template", "Free chat template", [["", "None"], ["streamlabs", "Streamlabs Chat Box CSS"],
                                                       ["streamelements", "StreamElements chat CSS"],
                                                       ["jchat", "jChat / Chat Is This CSS"]],
                    help_text="Starts from Custom CSS only and leaves out the K / T / Y letters and pictures"),
            _text("in", "Line entrance (StreamElements template)", "", "An animate.css name, e.g. bounceIn", "fadeInUp"),
            _text("css", "Saved stylesheet", "", "Name of a stylesheet saved on the Chat overlay page; empty = the main one",
                  "twitch"),
            _bool("preview", "Preview with made-up chatters", False, "For testing the look while chat is quiet"),
        ],
        "settings": [{"label": "Skin, custom CSS, pictures and sounds", "hash": "#chatlook"}],
    },
    {
        "id": "alerts",
        "file": "alerts.html",
        "name": "Stream alerts overlay",
        "notes": "Transparent Webpage source — follow / sub / raid / Super Chat. Test from the Alerts tab.",
        "params": [
            _select("skin", "Skin", [["", "Dashboard setting"], ["classic", "Classic"], ["card", "Card"],
                                     ["custom", "Custom CSS only"]]),
            _multi("platforms", "Only these platforms", PLATFORMS, "Empty = every platform"),
            _select("group", "Only a group", [["", "Every alert"], ["money", "Money and tips"],
                                              ["subs", "Subs and memberships"], ["community", "Follows, raids, hosts"]]),
            _multi("kinds", "Only these alerts", ALERT_KINDS, "Empty = the group above, or every alert"),
            _multi("hide", "Never these alerts", ALERT_KINDS),
            _num("min", "Smallest money alert", "", "Super Chats, stickers and tips below this are skipped", 0, None, 0.5),
            _num("min_bits", "Smallest cheer (bits)", "", "", 0, None, 1),
            _num("min_kicks", "Smallest KICKs", "", "", 0, None, 1),
            _bool("tests", "Show test alerts", True, "Untick so Fire test only shows on other sources"),
            _num("duration", "Seconds on screen", "", "Empty = dashboard setting", 1.5, 60, 0.5),
            _bool("sound", "Sounds", True),
            _num("volume", "Volume (%)", "", "Empty = dashboard setting", 0, 100, 5),
            _bool("image", "Picture", True),
            _bool("message", "Viewer's message", True),
            _select("layout", "Layout", [["", "Picture above text"], ["side", "Picture beside text"],
                                         ["banner", "Text over the picture"]]),
            _select("align", "Position", [["", "Centre"], ["left", "Left"], ["right", "Right"]]),
            _text("in", "Entrance animation", "", "An animate.css name, e.g. bounceIn, slideInLeft", "fadeIn"),
            _select("letters", "Letter animation", [["", "None"], ["wiggle", "Wiggle"], ["rubberBand", "Rubber band"],
                                                       ["tada", "Tada"], ["pulse", "Pulse"]],
                    help_text="Every letter of the name and amount moves; packs can use their own names"),
            _text("out", "Exit animation", "", "e.g. fadeOut, slideOutRight", "fadeOut"),
            _text("tiers", "Tier amounts", "", "Where tier-2, tier-3 and tier-4 start; empty = dashboard setting",
                  "5,20,100"),
            _num("queue", "Most alerts waiting", "", "Extra ones are dropped; empty = 50", 1, 200, 1),
            _text("css", "Saved stylesheet", "", "Name of a stylesheet saved on the Alerts page; empty = the main one",
                  "money"),
            _bool("preview", "Preview mode", False, "Shows \"waiting for an alert\" so you can place the source"),
        ],
        "settings": [{"label": "Test alerts, skin, custom CSS, pictures and sounds", "hash": "#alerts"}],
        "config": [
            {"key": "overlay.alert_duration_ms", "label": "How long an alert stays (ms)", "type": "number",
             "min": 1500, "max": 30000, "step": 500},
        ],
    },
    {
        "id": "widget",
        "file": "widget.html",
        "name": "Chat widget (StreamElements / Streamlabs)",
        "notes": "A StreamElements or Streamlabs code widget you imported, fed with chat from every platform. Transparent.",
        "params": [
            _text("name", "Widget", "", "Its name on the Chat widgets page (Copy OBS address fills this in)", "vamp-red"),
            _multi("platforms", "Only these platforms", PLATFORMS, "Empty = every platform"),
            _bool("alerts", "Follows, subs, tips, cheers and raids", True, "Untick to pass chat only"),
            _num("hide", "Hide messages after (seconds)", "", "Streamlabs chat boxes only; empty or 0 = keep them", 0, 600, 1),
            _bool("history", "Start with the last few messages", False),
            _bool("preview", "Preview with made-up chatters", False, "For testing the look while chat is quiet"),
        ],
        "settings": [{"label": "Import widgets, their settings and test buttons", "hash": "#widgets"}],
    },
    {
        "id": "replies",
        "file": "replies.html",
        "name": "Replies + boards overlay",
        "notes": "Core's answers to commands and the chat-game boards (polls, predictions, trivia). Transparent.",
        "params": [
            _bool("replies", "Reply lines", True),
            _bool("boards", "Chat-game boards", True),
            _bool("force", "Show even when replies are off in config", False),
        ],
        "config": [
            {"key": "overlay.replies_enabled", "label": "Replies overlay on", "type": "bool"},
        ],
    },
    {
        "id": "metrics",
        "file": "overlay.html",
        "name": "Metrics overlay",
        "notes": "Viewers, CPM, power level (+ Minecraft HP / inventory with the Minecraft plugin)",
        "params": [
            _multi("show", "Only these modules", [[m, m] for m in METRIC_MODULES], "Empty = the config's module list"),
            _multi("hide", "Hide these modules", [[m, m] for m in METRIC_MODULES]),
        ],
        "config": [
            {"key": "overlay.show_inventory_seconds", "label": "Inventory flash (seconds)", "type": "number",
             "min": 1, "max": 120, "step": 1},
        ],
    },
    {
        "id": "credits",
        "file": "credits.html",
        "name": "End credits overlay",
        "notes": "Built-in unique-chatter end credits (Admin → Credits). Transparent Webpage source.",
        "params": [],
        "settings": [{"label": "Credits look, motion and roll controls", "hash": "#credits"}],
    },
    {
        "id": "reactions",
        "file": "reactions.html",
        "name": "Chat reactions (fallback)",
        "notes": "Plays reactions when Stream Rooms isn't connected. Full-screen, transparent.",
        "params": [
            _bool("any", "Play even while Stream Rooms is connected", False),
            _num("scale", "Size", 1, "0.3 to 4", 0.3, 4, 0.1),
            _bool("debug", "Show a log on the page", False),
        ],
        "settings": [{"label": "Reactions settings and pictures", "hash": "#config/reactions"}],
    },
]

# The first entry is Core's own page (``url_path``, put first on the list); the rest are
# other Fridge apps on their fixed ports (CLAUDE.md), listed last.
# Pages that aren't overlays but belong on the same list
EXTRA_SOURCES: list[dict[str, Any]] = [
    {"name": "Admin hub (this page)", "url_path": "/admin/", "notes": "Main control panel"},
    {"name": "Chat Credits (standalone app)", "url": "http://127.0.0.1:3854/",
     "notes": "Optional separate process if you don't want credits inside Core"},
    {"name": "Reactive Image HTTP", "url": "http://127.0.0.1:3851/status", "notes": "Audio-reactive avatar control API"},
]


def default_query(overlay: dict[str, Any]) -> str:
    """The query string the row shows by default: text switches whose default isn't empty (a chart needs a ticker)."""
    parts = []
    for p in overlay.get("params") or []:
        if p["type"] == "text" and p.get("default"):
            parts.append(f'{p["key"]}={p["default"]}')
    return "&".join(parts)


def sources(base: str) -> list[dict[str, Any]]:
    """Rows for the Sources & overlays page: {id?, name, url, notes, params?, settings?, config?}."""
    rows: list[dict[str, Any]] = []
    for extra in EXTRA_SOURCES[:1]:
        rows.append({"name": extra["name"], "url": base + extra["url_path"], "notes": extra["notes"]})
    for o in OVERLAYS:
        q = default_query(o)
        rows.append({
            "id": o["id"],
            "name": o["name"],
            "url": f'{base}/overlay/{o["file"]}' + (f"?{q}" if q else ""),
            "page": f'{base}/overlay/{o["file"]}',
            "notes": o["notes"],
            "params": o.get("params") or [],
            "settings": o.get("settings") or [],
            "config": o.get("config") or [],
        })
    for extra in EXTRA_SOURCES[1:]:
        rows.append({"name": extra["name"], "url": extra["url"], "notes": extra["notes"]})
    return rows


def by_id(overlay_id: str) -> dict[str, Any] | None:
    """The OVERLAYS entry with this id, or None."""
    for o in OVERLAYS:
        if o["id"] == overlay_id:
            return o
    return None
