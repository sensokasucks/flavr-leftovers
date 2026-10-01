"""Canonical look + motion defaults for the credits overlay.

Admin → Credits (Stream Core) and the Chat Credits control desk both edit
these keys live. The overlay (`overlay/credits.js`) reads the same shape.
Keep this module import-light — config.py and credits.py both load it.

`sanitize_look()` cleans a look patch before it is applied: old / standalone
key names become Core names, enums fall back to a safe value and numbers are
clamped so a bad editor value can't freeze the overlay. Keys it doesn't know
pass through untouched (new overlay features shouldn't need a Python change).
Keep MOTION_IDS in lockstep with overlay/credits-editor.js MOTIONS.
"""

from __future__ import annotations

from typing import Any

LOOK_DEFAULTS: dict[str, Any] = {
    # Copy
    "title": "Thanks for watching",
    "subtitle": "",
    "footer": "See you next stream",
    "section_label": "Chatters",
    # List
    "group_by_platform": False,
    "sort": "first_seen",
    "columns": 2,
    "show_platform": True,
    "show_message_count": False,
    "highlight_mods": True,
    "highlight_vips": False,
    # Playback
    "speed_px_per_sec": 42,
    "duration_sec": 0,
    "gap_after_loop_sec": 2.5,
    "mode": "loop",
    # Motion
    "motion": "crawl",
    "easing": "linear",
    "mask_fade_px": 72,
    "vignette": False,
    "title_intro": "none",
    "title_hold_sec": 0,
    "name_enter": "none",
    "name_stagger_ms": 40,
    "loop_transition": "cut",
    "perspective_px": 420,
    "tilt_deg": 52,
    "page_duration_sec": 4.5,
    "page_transition_ms": 700,
    "type_ms": 55,
    "typewriter_unit": "line",
    "typewriter_cps": 28,
    "matrix_density": 1.0,
    "title_own_page": True,
    "clear_when_done": False,
    # Film look
    "letterbox": False,
    "grain": False,
    # Type
    "font_family": '"Palatino Linotype", Palatino, "Times New Roman", Georgia, serif',
    "font_preset": "palatino",
    "custom_font_url": "",
    "title_size_px": 54,
    "name_size_px": 22,
    "subtitle_size_px": 26,
    "footer_size_px": 28,
    "letter_spacing_em": 0.04,
    "uppercase_title": True,
    "uppercase_names": False,
    "title_weight": 600,
    "name_weight": 500,
    # Color
    "title_color": "#f3e2b0",
    "name_color": "#f4f0e6",
    "muted_color": "#9a8f78",
    "mod_color": "#e8c36a",
    "vip_color": "#c9a0ff",
    "background": "transparent",
    "text_shadow": "0 2px 8px rgba(0,0,0,0.85)",
    "shadow_strength": 8,
    "glow": False,
    "glow_color": "#e8c36a",
    "glow_px": 16,
    "opacity": 1,
    # Layout
    "column_gap_px": 48,
    "row_gap_px": 10,
    "max_width_px": 920,
    "rule_style": "gradient",
    "align": "center",
    "job_layout": "dots",
    # Cast
    "style_id": "names",
    "command_permission": "mod",
}

# Motions the overlay actually implements. Editor uses the same ids.
MOTION_IDS = (
    "crawl",
    "crawl-down",
    "starwars",
    "cards",
    "fade",
    "slides",
    "ticker",
    "typewriter",
    "matrix",
)

MOTION_ALIASES = {
    "teletype": "typewriter",
    "tty": "typewriter",
    "nametape": "ticker",
    "name-tape": "ticker",
}

PLAY_MODES = ("loop", "once", "hold", "clear")

# key -> allowed values (first is the fallback)
ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "name_enter": ("none", "rise", "fade", "slide", "blur"),
    "typewriter_unit": ("line", "card", "page", "name"),
    "sort": ("first_seen", "name", "messages", "last_seen"),
    "easing": ("linear", "ease-in", "ease-out", "ease-in-out", "smooth"),
    "loop_transition": ("cut", "fade", "wipe"),
    "title_intro": ("none", "fade", "scale", "wipe", "letters"),
    "align": ("center", "left"),
    "job_layout": ("dots", "stacked", "inline"),
    "rule_style": ("gradient", "solid", "double", "none"),
    "mode": PLAY_MODES,
}

# key -> (min, max, fallback, whole number?)
NUM_FIELDS: dict[str, tuple[float, float, float, bool]] = {
    "columns": (1, 4, 2, True),
    "speed_px_per_sec": (4, 400, 42, False),
    "duration_sec": (0, 900, 0, False),
    "gap_after_loop_sec": (0, 60, 2.5, False),
    "mask_fade_px": (0, 400, 72, True),
    "title_hold_sec": (0, 30, 0, False),
    "name_stagger_ms": (0, 1000, 40, True),
    "perspective_px": (100, 1600, 420, True),
    "tilt_deg": (5, 85, 52, False),
    "page_duration_sec": (0.8, 60, 4.5, False),
    "page_transition_ms": (80, 3000, 700, True),
    "type_ms": (10, 1000, 55, True),
    "typewriter_cps": (4, 120, 28, True),
    "matrix_density": (0.4, 2.2, 1.0, False),
    "title_size_px": (10, 160, 54, True),
    "name_size_px": (8, 96, 22, True),
    "subtitle_size_px": (8, 120, 26, True),
    "footer_size_px": (8, 120, 28, True),
    "letter_spacing_em": (0, 0.6, 0.04, False),
    "title_weight": (100, 900, 600, True),
    "name_weight": (100, 900, 500, True),
    "shadow_strength": (0, 40, 8, False),
    "glow_px": (0, 80, 16, False),
    "opacity": (0.05, 1, 1, False),
    "column_gap_px": (0, 240, 48, True),
    "row_gap_px": (0, 80, 10, True),
    "max_width_px": (240, 2400, 920, True),
}

BOOL_FIELDS = (
    "group_by_platform",
    "show_platform",
    "show_message_count",
    "highlight_mods",
    "highlight_vips",
    "vignette",
    "letterbox",
    "grain",
    "glow",
    "uppercase_title",
    "uppercase_names",
    "clear_when_done",
    "title_own_page",
)


def _num(raw: Any, lo: float, hi: float, default: float, whole: bool) -> float | int:
    try:
        n = float(raw)
    except (TypeError, ValueError):
        n = default
    if n != n or n in (float("inf"), float("-inf")):  # NaN / inf
        n = default
    n = max(lo, min(hi, n))
    return int(round(n)) if whole else n


def _bool(raw: Any) -> bool:
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return bool(raw)


def sanitize_look(raw: Any) -> dict[str, Any]:
    """Clean a look patch. Only keys present in `raw` come back (it's a patch)."""
    src = dict(raw) if isinstance(raw, dict) else {}

    # Standalone Chat Credits names -> Core names. A Core key in the same
    # patch wins; the old key is dropped either way.
    if "sw_tilt_deg" in src:
        val = src.pop("sw_tilt_deg")
        src.setdefault("tilt_deg", val)
    if "sw_perspective_px" in src:
        val = src.pop("sw_perspective_px")
        src.setdefault("perspective_px", val)
    if "page_hold_sec" in src:
        val = src.pop("page_hold_sec")
        src.setdefault("page_duration_sec", val)
    if "page_fade_sec" in src:
        val = src.pop("page_fade_sec")
        if "page_transition_ms" not in src:
            try:
                src["page_transition_ms"] = float(val) * 1000.0
            except (TypeError, ValueError):
                pass

    out: dict[str, Any] = dict(src)

    if "motion" in src:
        motion = str(src.get("motion") or "crawl").strip().lower()
        motion = MOTION_ALIASES.get(motion, motion)
        out["motion"] = motion if motion in MOTION_IDS else "crawl"

    for key, allowed in ENUM_FIELDS.items():
        if key in src:
            val = str(src.get(key) or "").strip().lower()
            out[key] = val if val in allowed else allowed[0]

    for key, (lo, hi, default, whole) in NUM_FIELDS.items():
        if key in src:
            out[key] = _num(src.get(key), lo, hi, default, whole)

    for key in BOOL_FIELDS:
        if key in src:
            out[key] = _bool(src[key])

    return out


def merge_look(base: Any, patch: Any) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(sanitize_look(patch))
    return merged
