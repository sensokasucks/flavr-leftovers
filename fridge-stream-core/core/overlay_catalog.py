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
METRIC_MODULES = ["health", "food", "xp", "deaths", "armor", "viewers", "cpm", "power", "effects", "inventory"]


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


_MARKET_BOOK = _select("book", "Game book", [["", "All books"], ["factorio", "Factorio"], ["minecraft", "Minecraft"],
                                            ["openttd", "OpenTTD"]], help_text="Only tickers from one game")
_MARKET_SYMBOLS = _text("symbols", "Tickers", "", "Comma-separated, empty = all", "FRG,FACT")
_SOLID = _bool("solid", "Solid background", False, "Opaque panel instead of transparent")
_BARE = _bool("bare", "Bare (no frame or title)", False)

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
            _bool("preview", "Preview mode", False, "Shows \"waiting for an alert\" so you can place the source"),
        ],
        "settings": [{"label": "Test alerts, skin, custom CSS, pictures and sounds", "hash": "#alerts"}],
        "config": [
            {"key": "overlay.alert_duration_ms", "label": "How long an alert stays (ms)", "type": "number",
             "min": 1500, "max": 30000, "step": 500},
        ],
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
        "name": "Chat Credits overlay",
        "notes": "Built-in unique-chatter end credits (Admin → Credits). Transparent Webpage source.",
        "params": [],
        "settings": [{"label": "Credits look, motion and roll controls", "hash": "#credits"}],
    },
    {
        "id": "market",
        "file": "market.html",
        "name": "Fridge Market ticker",
        "notes": "Scrolling live tape",
        "params": [_MARKET_SYMBOLS, _MARKET_BOOK, _num("speed", "Scroll speed", 80, "Pixels per second", 10, 400, 10)],
        "settings": [{"label": "Market settings", "hash": "#market"}],
    },
    {
        "id": "market-board",
        "file": "market-board.html",
        "name": "Fridge Market board",
        "notes": "Quote cards + sparklines. Transparent Webpage source.",
        "params": [_MARKET_SYMBOLS, _MARKET_BOOK, _BARE, _SOLID],
        "settings": [{"label": "Market settings", "hash": "#market"}],
    },
    {
        "id": "market-chart",
        "file": "market-chart.html",
        "name": "Fridge Market chart",
        "notes": "TV-style line graph of one ticker",
        "params": [
            _text("symbol", "Ticker", "FACT", "", "FACT"),
            _select("layout", "Layout", [["hero", "Hero (big)"], ["grid", "Grid"]], "hero"),
            _num("points", "History points", 120, "", 20, 600, 10),
            _BARE, _SOLID,
        ],
        "settings": [{"label": "Market settings", "hash": "#market"}],
    },
    {
        "id": "market-cycle",
        "file": "market-cycle.html",
        "name": "Fridge Market cycle",
        "notes": "Plays a chosen set of charts in turn",
        "params": [
            _text("symbols", "Tickers", "FRG,FACT,STEVE", "Comma-separated", "FRG,FACT,STEVE"),
            _num("dwell", "Seconds per chart", 8, "", 2, 120, 1),
            _num("points", "History points", 180, "", 20, 600, 10),
            _SOLID,
        ],
        "settings": [{"label": "Market settings", "hash": "#market"}],
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
    for o in OVERLAYS:
        if o["id"] == overlay_id:
            return o
    return None
