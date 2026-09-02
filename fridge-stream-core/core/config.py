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
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

log = logging.getLogger("core.config")

# Project root = parent of core/
ROOT = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    """Invalid or unreadable config file."""


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
    "factorio": {
        "enabled": False,
        "bridge_url": "http://127.0.0.1:3847",
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
        "alert_duration_ms": 6000,
    },
    "points": {
        "enabled": False,
        "per_message": 1,
        "cooldown_sec": 30,
        "admin_token": "change-me",
    },
    "chat_log": {
        "enabled": False,  # persist messages to SQLite (Chat History tab)
    },
    "credits": {
        "enabled": False,  # unique-chatter end credits overlay
        "ignore_own_channel": True,
        "min_message_length": 1,
        "ignore_usernames": [
            "nightbot",
            "streamelements",
            "streamlabs",
            "moobot",
            "fossabot",
            "wizebot",
            "sery_bot",
            "commanderroot",
            "soundalerts",
        ],
        "title": "Thanks for watching",
        "subtitle": "",
        "footer": "See you next stream",
        "section_label": "Chatters",
        "group_by_platform": False,
        "sort": "first_seen",
        "columns": 2,
        "speed_px_per_sec": 42,
        "duration_sec": 0,
        "letterbox": True,
        "grain": True,
        "vignette": True,
        "gap_after_loop_sec": 2.5,
        "mode": "loop",
        "show_platform": True,
        "show_message_count": False,
        "highlight_mods": True,
        "highlight_vips": True,
        "announce_roll": True,
        "style_id": "movie",
        "command_permission": "mod",
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
    "command_groups": {
        "core": {
            "enabled": True,
            "always": True,
            "bind": None,
            "description": "Built-in Core commands (!help, !permit)",
        },
        "points": {
            "enabled": True,
            "always": False,
            "bind": "points",
            "description": "Chat points (!points / !balance)",
        },
        "minecraft": {
            "enabled": True,
            "always": False,
            "bind": "minecraft",
            "description": "Minecraft integration (!spawn, !give, …)",
        },
        "factorio": {
            "enabled": True,
            "always": False,
            "bind": "factorio",
            "description": "Factorio stats overlay (Fridge Factorio Stats bridge)",
        },
        "credits": {
            "enabled": True,
            "always": False,
            "bind": "credits",
            "description": "End credits (!credit / !credits)",
        },
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


def sanitize_yaml_text(text: str) -> Tuple[str, bool]:
    """
    YAML forbids tab characters as indentation. Windows editors (and an
    earlier example file) sometimes sneak a tab in, which crashes PyYAML
    with ScannerError on the next key.

    - Strip a UTF-8 BOM if present.
    - If a known top-level section is tab-indented, unindent it (the
      GitHub example had a tab before `overlay:`).
    - Any other tabs become spaces (tab stops of 2).
    """
    changed = False
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
        changed = True
    if "\t" not in text:
        return text, changed

    top = set(DEFAULTS)
    lines: list[str] = []
    for raw in text.splitlines(True):
        if "\t" not in raw:
            lines.append(raw)
            continue
        changed = True
        newline = "\n" if raw.endswith("\n") else ""
        body = raw[:-1] if newline else raw
        if body.endswith("\r"):
            body = body[:-1]
        stripped = body.lstrip(" \t")
        lead = body[: len(body) - len(stripped)]
        key = stripped.split(":", 1)[0].strip()
        is_section = bool(stripped) and not stripped.startswith("#") and key in top
        if is_section and "\t" in lead:
            lines.append(stripped + newline)
        else:
            lines.append(lead.expandtabs(2) + stripped + newline)
    return "".join(lines), True


def _read_text(path: Path) -> str:
    # utf-8-sig strips a Windows/Notepad BOM if one is present
    return path.read_text(encoding="utf-8-sig")


def _parse_yaml(text: str, source: Path | str) -> dict:
    cleaned, _ = sanitize_yaml_text(text)
    try:
        data = yaml.safe_load(cleaned) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Could not parse {source}. YAML does not allow tab characters "
            f"for indentation.\nDetails: {exc}\n"
            "Fix: copy config/config.example.yaml over config/config.yaml "
            "(or replace tabs with spaces) and try again."
        ) from exc
    if data and not isinstance(data, dict):
        raise ConfigError(f"{source} must be a YAML mapping (key: value), not {type(data).__name__}")
    return data if isinstance(data, dict) else {}


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


def ensure_seed_files() -> None:
    """
    First-run: copy example config/commands into place and create data/.

    Safe to call on every start. Never overwrites an existing config.yaml.
    Also rewrites the example file if it still contains tabs (old clones).
    """
    cfg_dir = ROOT / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)

    example = cfg_dir / "config.example.yaml"
    target = cfg_dir / "config.yaml"
    if example.exists():
        ex_text = _read_text(example)
        cleaned, changed = sanitize_yaml_text(ex_text)
        if changed:
            try:
                example.write_text(cleaned, encoding="utf-8")
                log.warning("Removed tab indentation from %s", example)
            except OSError:
                log.warning("Could not rewrite tab characters in %s", example)
        else:
            cleaned = ex_text
        if not target.exists():
            target.write_text(cleaned, encoding="utf-8")
            log.info("Created %s from config.example.yaml (platforms off)", target)

    cmd_example = cfg_dir / "commands.example.json"
    cmd_target = cfg_dir / "commands.json"
    if not cmd_target.exists() and cmd_example.exists():
        shutil.copyfile(cmd_example, cmd_target)
        log.info("Created %s from commands.example.json", cmd_target)


def load_config(path: Path | str | None = None) -> dict:
    ensure_seed_files()
    data: dict = {}
    found = resolve_config_path(path)
    if found:
        text = _read_text(found)
        if found.suffix in (".yaml", ".yml"):
            cleaned, changed = sanitize_yaml_text(text)
            if changed:
                try:
                    found.write_text(cleaned, encoding="utf-8")
                    log.warning(
                        "Rewrote %s to replace tab indentation (YAML forbids tabs)",
                        found,
                    )
                except OSError:
                    log.warning(
                        "Config %s contains tabs; loaded after converting to spaces",
                        found,
                    )
                text = cleaned
            data = _parse_yaml(text, found)
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Could not parse {found}: {exc}") from exc
            if not isinstance(data, dict):
                data = {}
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
        indent=2,
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
    try:
        data = json.loads(_read_text(target))
    except json.JSONDecodeError as exc:
        log.error("Invalid commands JSON in %s: %s", target, exc)
        return {}
    return data if isinstance(data, dict) else {}


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
