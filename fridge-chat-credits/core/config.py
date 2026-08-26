"""Load config/config.yaml and merge with defaults."""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("core.config")

DEFAULT_IGNORE = [
    "nightbot",
    "streamelements",
    "streamlabs",
    "moobot",
    "fossabot",
    "wizebot",
    "sery_bot",
    "commanderroot",
    "soundalerts",
    "kofistreambot",
    "own3d",
]

DEFAULTS: dict[str, Any] = {
    "app": {
        "host": "127.0.0.1",
        "port": 3854,
        "log_level": "INFO",
        "session_file": "data/session.json",
        "save_every_sec": 10,
    },
    "roster": {
        "ignore_usernames": DEFAULT_IGNORE,
        "ignore_own_channel": True,
        "min_message_length": 1,
    },
    "twitch": {
        "enabled": False,
        "channel": "",
    },
    "kick": {
        "enabled": False,
        "channel_slug": "",
        "chatroom_id": None,
    },
    "youtube": {
        "enabled": False,
        "api_key": "",
        "video_id": "",
        "live_chat_id": "",
    },
    "ingest": {
        "stream_core": {
            "enabled": False,
            "ws_url": "ws://127.0.0.1:3850/ws",
        }
    },
    "credits": {
        "title": "Thanks for watching",
        "subtitle": "",
        "footer": "See you next stream",
        "section_label": "Chatters",
        "group_by_platform": False,
        "sort": "first_seen",
        "columns": 2,
        "speed_px_per_sec": 42,
        "gap_after_loop_sec": 2.5,
        "mode": "loop",
        "show_platform": True,
        "show_message_count": False,
        "highlight_mods": True,
        "font_family": '"Palatino Linotype", Palatino, "Times New Roman", Georgia, serif',
        "title_size_px": 54,
        "name_size_px": 22,
        "title_color": "#f3e2b0",
        "name_color": "#f4f0e6",
        "muted_color": "#9a8f78",
        "mod_color": "#e8c36a",
        "background": "transparent",
        "text_shadow": "0 2px 8px rgba(0,0,0,0.85)",
        "letter_spacing_em": 0.04,
        "column_gap_px": 48,
        "row_gap_px": 10,
        "max_width_px": 920,
        "custom_font_url": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(root: Path) -> dict:
    path = root / "config" / "config.yaml"
    if not path.exists():
        example = root / "config" / "config.example.yaml"
        if example.exists():
            log.warning("config.yaml missing — loading config.example.yaml")
            path = example
        else:
            log.warning("No config file found — using built-in defaults")
            return copy.deepcopy(DEFAULTS)

    with path.open("r", encoding="utf-8-sig") as f:
        text = f.read()
    if "\t" in text or text.startswith("\ufeff"):
        lines = []
        for raw in text.lstrip("\ufeff").splitlines(True):
            if "\t" not in raw:
                lines.append(raw)
                continue
            newline = "\n" if raw.endswith("\n") else ""
            body = raw[:-1] if newline else raw
            stripped = body.lstrip(" \t")
            lead = body[: len(body) - len(stripped)]
            lines.append(lead.expandtabs(2) + stripped + newline)
        text = "".join(lines)
        try:
            path.write_text(text, encoding="utf-8")
            log.warning("Rewrote %s to replace tab indentation", path)
        except OSError:
            pass
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"Could not parse {path}. YAML does not allow tab indent.\n{exc}"
        ) from exc
    if not isinstance(raw, dict):
        raw = {}
    return _deep_merge(DEFAULTS, raw)


def save_config(root: Path, data: dict) -> Path:
    """Write config.yaml (merged with defaults). Platform toggles need a restart."""
    merged = _deep_merge(DEFAULTS, data or {})
    path = root / "config" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        merged,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=100,
        indent=2,
    )
    header = (
        "# Fridge Chat Credits configuration\n"
        "# Edited by the control-desk Config editor or by hand.\n"
        "# Restart Chat Credits after changing platforms / ingest.\n\n"
    )
    path.write_text(header + text, encoding="utf-8")
    log.info("Saved config to %s", path)
    return path
