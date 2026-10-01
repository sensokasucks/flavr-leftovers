"""Shared credits look sanitizer.

Keep this list in lockstep with overlay/credits-editor.js MOTIONS / FIELDS.
If a motion id is missing here, the overlay falls back to a crawl and
Matrix / Teletype look like "Classic with different colors."
"""

from __future__ import annotations

from typing import Any

ALLOWED_MOTIONS = (
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

ALLOWED_ENTERS = ("none", "rise", "fade", "blur")
ALLOWED_TYPE_UNITS = ("line", "card", "page")
ALLOWED_SORTS = ("first_seen", "name", "messages", "last_seen")

# Floor / ceiling so a bad editor value cannot freeze the overlay.
NUM_FIELDS = {
    "columns": (1, 4, 2),
    "speed_px_per_sec": (8, 240, 42),
    "duration_sec": (0, 600, 0),
    "gap_after_loop_sec": (0, 30, 2.5),
    "title_size_px": (18, 96, 54),
    "name_size_px": (12, 48, 22),
    "letter_spacing_em": (0, 0.5, 0.04),
    "column_gap_px": (8, 120, 48),
    "row_gap_px": (0, 40, 10),
    "max_width_px": (320, 1600, 920),
    "page_hold_sec": (0.8, 20, 4.2),
    "page_fade_sec": (0.1, 3, 0.65),
    "typewriter_cps": (8, 80, 28),
    "sw_tilt_deg": (20, 70, 52),
    "sw_perspective_px": (180, 900, 420),
    "matrix_density": (0.4, 2.2, 1.0),
}

BOOL_FIELDS = (
    "group_by_platform",
    "show_platform",
    "show_message_count",
    "highlight_mods",
    "highlight_vips",
    "letterbox",
    "grain",
    "vignette",
    "announce_roll",
    "clear_when_done",
)

TEXT_FIELDS = (
    "title",
    "subtitle",
    "footer",
    "section_label",
    "font_family",
    "custom_font_url",
    "title_color",
    "name_color",
    "muted_color",
    "mod_color",
    "background",
    "text_shadow",
)


def _num(raw: Any, lo: float, hi: float, default: float) -> float:
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return default
    if n != n:  # NaN
        return default
    return max(lo, min(hi, n))


def sanitize_look(raw: Any) -> dict[str, Any]:
    """Return a theme dict the overlay engine can actually play."""
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}

    motion = str(src.get("motion") or "crawl").strip().lower()
    # Older chips / docs used these aliases.
    if motion in ("teletype", "tty"):
        motion = "typewriter"
    if motion in ("name-tape", "nametape"):
        motion = "ticker"
    if motion not in ALLOWED_MOTIONS:
        motion = "crawl"
    out["motion"] = motion

    enter = str(src.get("name_enter") or "none").strip().lower()
    out["name_enter"] = enter if enter in ALLOWED_ENTERS else "none"

    unit = str(src.get("typewriter_unit") or "line").strip().lower()
    out["typewriter_unit"] = unit if unit in ALLOWED_TYPE_UNITS else "line"

    sort = str(src.get("sort") or "first_seen").strip().lower()
    out["sort"] = sort if sort in ALLOWED_SORTS else "first_seen"

    for key in TEXT_FIELDS:
        val = src.get(key)
        if val is None:
            continue
        out[key] = str(val)

    for key, (lo, hi, default) in NUM_FIELDS.items():
        if key not in src and key not in ("typewriter_cps", "matrix_density"):
            continue
        out[key] = _num(src.get(key, default), lo, hi, default)

    # Always persist the motion-specific knobs so a Matrix/Teletype
    # preset cannot come back as Classic after a round-trip save.
    if "typewriter_cps" not in out:
        out["typewriter_cps"] = _num(src.get("typewriter_cps"), 8, 80, 28)
    if "matrix_density" not in out:
        out["matrix_density"] = _num(src.get("matrix_density"), 0.4, 2.2, 1.0)

    for key in BOOL_FIELDS:
        if key in src:
            out[key] = bool(src[key])

    # Integer-ish fields the editor posts as numbers.
    if "columns" in out:
        out["columns"] = int(out["columns"])
    if "title_size_px" in out:
        out["title_size_px"] = int(out["title_size_px"])
    if "name_size_px" in out:
        out["name_size_px"] = int(out["name_size_px"])
    if "typewriter_cps" in out:
        out["typewriter_cps"] = int(out["typewriter_cps"])

    return out


def merge_look(base: Any, patch: Any) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(patch or {})
    return sanitize_look(merged)
