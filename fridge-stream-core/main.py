#!/usr/bin/env python3
"""
Fridge Stream Core – entry point.

Starts (all chat platforms and Minecraft are opt-in via config):
  - Platform adapters: Kick / Twitch / YouTube
  - Minecraft game integration
  - Command router + metrics aggregator
  - FastAPI HTTP/WS server on the configured port (default 3850)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path

if sys.version_info < (3, 10):
    sys.stderr.write(
        "Fridge Stream Core needs Python 3.10 or newer.\n"
        f"This interpreter is {sys.version}\n"
    )
    raise SystemExit(1)

# Ensure project root is on path when run as script
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import uvicorn

    from core.config import ConfigError, ensure_seed_files, load_config, resolve_commands_path
    from core.command_groups import catalog_status, resolve_active_groups
    from core.event_bus import EventBus
    from core.metrics import MetricsAggregator
    from core.permissions import PermissionManager
    from core.command_router import CommandRouter
    from core.models import ChatEvent, ChatReply, ExecuteRequest
    from core.alerts import build_alert
    from core.store import Store
    from adapters.kick import KickAdapter
    from adapters.twitch import TwitchAdapter
    from adapters.youtube import YouTubeAdapter
    from games.minecraft import MinecraftIntegration
    from api.server import create_app, CoreState
except ImportError as exc:
    sys.stderr.write(
        f"Missing a Python package: {exc}\n"
        "On Windows, double-click install.bat once.\n"
        "Or run:  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(1) from exc
