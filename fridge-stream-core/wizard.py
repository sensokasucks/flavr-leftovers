#!/usr/bin/env python3
"""First-run setup wizard for Fridge Stream Core."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML missing — run install.bat or: pip install -r requirements.txt")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
EXAMPLE_PATH = ROOT / "config" / "config.example.yaml"


def load_example() -> dict:
    if EXAMPLE_PATH.exists():
        return yaml.safe_load(EXAMPLE_PATH.read_text(encoding="utf-8")) or {}
    return {}


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def ask_bool(prompt: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    val = input(f"{prompt} [{d}]: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes", "1", "true")


def main() -> int:
    print("=== Fridge Stream Core setup wizard ===\n")
    cfg = load_example()

    if ask_bool("Enable Kick chat?", False):
        cfg.setdefault("kick", {})["enabled"] = True
        cfg["kick"]["channel_slug"] = ask("Kick channel slug (kick.com/THIS)", "YOUR_KICK_CHANNEL")
    else:
        cfg.setdefault("kick", {})["enabled"] = False

    if ask_bool("Enable Twitch chat?", False):
        cfg.setdefault("twitch", {})["enabled"] = True
        cfg["twitch"]["channel"] = ask("Twitch channel name", "YOUR_TWITCH_CHANNEL")
    else:
        cfg.setdefault("twitch", {})["enabled"] = False

    if ask_bool("Enable YouTube chat?", False):
        cfg.setdefault("youtube", {})["enabled"] = True
        cfg["youtube"]["video_id"] = ask("Current live video id (optional now)", "")
        cfg["youtube"]["mode"] = ask("YouTube mode (innertube/official/auto)", "innertube")
    else:
        cfg.setdefault("youtube", {})["enabled"] = False

    admin = ask("Admin username (for !permit etc.)", "YOUR_USERNAME")
    cfg.setdefault("permissions", {})["admin"] = [admin]

    token = cfg.get("points", {}).get("admin_token") or "change-me"
    if token == "change-me":
        token = secrets.token_urlsafe(16)
        print(f"Generated admin token: {token}")
    cfg.setdefault("points", {})["admin_token"] = token
    cfg["points"]["enabled"] = ask_bool("Enable chat points?", False)

    cfg.setdefault("chat_log", {})["enabled"] = ask_bool("Enable chat logging to SQLite?", False)

    if ask_bool("Enable Minecraft integration?", False):
        cfg.setdefault("minecraft", {})["enabled"] = True
        cfg["minecraft"]["player_name"] = ask("In-game player name", "YourInGameName")
    else:
        cfg.setdefault("minecraft", {})["enabled"] = False

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    print(f"\nWrote {CONFIG_PATH}")
    print("Start Core with start.bat or: python main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
