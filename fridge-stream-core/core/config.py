"""
Configuration loader and saver.

Supports YAML or JSON. Looks for config.yaml / config.json next to
the working directory or under ./config/.

The GUI config editor (admin dashboard) uses the same paths so tech
users and non-tech users share one source of truth.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

log = logging.getLogger("core.config")

# Project root = parent of core/
ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: Dict[str, Any] = {
    "core": {
        "host": "127.0.0.1",
        "port": 3850,
        "command_prefix": "!",
        "log_level": "INFO",
    },
    "kick": {
        "enabled": False,  # opt-in chat platform
        "channel_slug": "YOUR_KICK_CHANNEL",
        "poll_viewer_interval_sec": 15,
    },
    "twitch": {
        "enabled": False,  # opt-in chat platform
        "channel": "YOUR_TWITCH_CHANNEL",
    },
    "youtube": {
        "enabled": False,  # opt-in chat platform
        # mode: "innertube" (no key/quota) | "official" (Data API v3)
        # auto = official if api_key set, else innertube
        "mode": "innertube",
        "api_key": "",
        "channel_id": "",
        "video_id": "",
        "live_chat_id": "",
    },
    "minecraft": {
        "enabled": False,
        "player_name": "YourInGameName",
        "client_mod_url": "http://127.0.0.1:3852",
        "server_mod_url": "http://127.0.0.1:3853",
    },
    "permissions": {
        "admin": ["YOUR_USERNAME"],
        "mod": [],
    },
    "metrics": {
        "messageWindowSec": 60,
        "commandWindowSec": 120,
        "viewerWeight": 0.4,
        "cpmWeight": 0.3,
        "commandWeight": 0.3,
        "maxViewersForFull": 500,
        "maxCpmForFull": 30,
        "maxCommandsForFull": 10,
    },
    "overlay": {
        "show_inventory_seconds": 12,
    },
    "points": {
        "enabled": True,
        "per_message": 1,
        "cooldown_sec": 30,
        "admin_token": "change-me",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def resolve_config_path(path: Path | str | None = None) -> Optional[Path]:
    """Return the first existing config file path, or None."""
    candidates = []
    if path:
        candidates.append(Path(path))
    candidates.extend(
        [
            Path("config.yaml"),
            Path("config.yml"),
            Path("config.json"),
            Path("config/config.yaml"),
            Path("config/config.yml"),
            Path("config/config.json"),
            ROOT / "config" / "config.yaml",
            ROOT / "config" / "config.yml",
            ROOT / "config" / "config.json",
        ]
    )
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None


def default_config_write_path() -> Path:
    """Preferred path when creating / overwriting config.yaml."""
    preferred = ROOT / "config" / "config.yaml"
    preferred.parent.mkdir(parents=True, exist_ok=True)
    return preferred


def load_config(path: Path | str | None = None) -> dict:
    data: dict = {}
    found = resolve_config_path(path)
    if found:
        text = found.read_text(encoding="utf-8")
        if found.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text)
        log.info("Loaded config from %s", found)
    else:
        log.warning("No config file found – using defaults. Copy config.example.yaml")

    return _deep_merge(DEFAULTS, data)


def save_config(data: dict, path: Path | str | None = None) -> Path:
    """
    Write config as clean YAML (no comments). Merges with DEFAULTS keys
    so the on-disk file stays complete and readable.

    Returns the path written.
    """
    if path:
        target = Path(path)
    else:
        existing = resolve_config_path()
        target = existing if existing and existing.suffix in (".yaml", ".yml") else default_config_write_path()

    # Keep only known top-level sections + any extra user keys
    merged = _deep_merge(DEFAULTS, data or {})

    # Prefer a stable key order matching DEFAULTS
    ordered: Dict[str, Any] = {}
    for key in DEFAULTS:
        if key in merged:
            ordered[key] = merged[key]
    for key, val in merged.items():
        if key not in ordered:
            ordered[key] = val

    target.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        ordered,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    # Header so non-tech users know what the file is
    header = (
        "# Fridge Stream Core configuration\n"
        "# Edited by the admin Config UI or by hand.\n"
        "# Restart Stream Core after changing this file.\n\n"
    )
    target.write_text(header + text, encoding="utf-8")
    log.info("Saved config to %s", target)
    return target.resolve()


def resolve_commands_path() -> Path:
    p = ROOT / "config" / "commands.json"
    if p.exists():
        return p
    example = ROOT / "config" / "commands.example.json"
    if example.exists():
        return example
    return p


def load_commands(path: Path | str | None = None) -> dict:
    target = Path(path) if path else resolve_commands_path()
    if not target.exists():
        return {}
    return json.loads(target.read_text(encoding="utf-8"))


def save_commands(data: dict, path: Path | str | None = None) -> Path:
    """Write commands.json (pretty-printed). Always targets config/commands.json."""
    if path:
        target = Path(path)
    else:
        target = ROOT / "config" / "commands.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data or {}, indent=2, ensure_ascii=False) + "\n"
    target.write_text(text, encoding="utf-8")
    log.info("Saved commands to %s", target)
    return target.resolve()


def config_file_info() -> Tuple[Optional[str], Optional[str]]:
    """Return (config_path, commands_path) as strings for the API."""
    cfg = resolve_config_path()
    cmd = resolve_commands_path()
    return (
        str(cfg) if cfg else str(default_config_write_path()),
        str(cmd),
    )
