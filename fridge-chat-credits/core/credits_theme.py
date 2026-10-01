"""Canonical look + motion defaults for the credits overlay.

Admin → Credits (Stream Core) and the Chat Credits control desk both edit
these keys live. The overlay (`overlay/credits.js`) reads the same shape.
Keep this module import-light — config.py and credits.py both load it.
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
)
