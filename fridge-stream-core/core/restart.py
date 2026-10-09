"""Which saved settings only take effect after Stream Core restarts, and the restart itself.

Chat platforms, command groups, credits, reactions and most other settings apply live.
A few are read once at start: the address Core listens on, the log level, the config
file watcher and switching a game plugin on or off.

Restarting: START Stream Core.bat / start.bat run Core in a loop and start it again when
it exits with RESTART_EXIT_CODE (they set STREAM_CORE_SUPERVISED=1). Without that, Core
re-runs itself in place on Linux/macOS; on Windows it can't safely, so the dashboard
says to close the window and start again.
"""

from __future__ import annotations

import os
from typing import Iterable

RESTART_EXIT_CODE = 75

CORE_FIELDS = {
    "host": "the address Core listens on (host)",
    "port": "the port (every OBS browser source must use the new address)",
    "log_level": "the log level",
    "watch_config": "noticing hand edits to config.yaml",
}


def restart_needed(boot: dict, live: dict, plugins: Iterable = ()) -> list[str]:
    """Plain-language list of settings that differ from what Core started with."""
    boot = boot or {}
    live = live or {}
    out: list[str] = []
    b_core, l_core = boot.get("core") or {}, live.get("core") or {}
    for key, label in CORE_FIELDS.items():
        if str(b_core.get(key)) != str(l_core.get(key)):
            out.append(label)
    for m in plugins:
        pid = getattr(m, "id", "")
        name = getattr(m, "name", "") or pid
        was = bool((boot.get(pid) or {}).get("enabled"))
        now = bool((live.get(pid) or {}).get("enabled"))
        if pid and was != now:
            out.append(f"switching {name} {'on' if now else 'off'}")
    return out


def can_restart() -> tuple[bool, str]:
    """(possible, how) — "loop" when a START .bat restarts us, "exec" to re-run in place."""
    if os.environ.get("STREAM_CORE_SUPERVISED") == "1":
        return True, "loop"
    if os.name != "nt":
        return True, "exec"
    return False, ""
