"""
Command groups — enable/disable sets of commands by integration or always-on.

Groups are defined in config.yaml under `command_groups` and referenced from
commands.json via `"group": "minecraft"` (etc.). Hot-reload without restart.
"""

from __future__ import annotations

from typing import Any, Optional


DEFAULT_GROUPS: dict[str, dict[str, Any]] = {
    "core": {
        "enabled": True,
        "always": True,
        "description": "Built-in Core commands (permit, points helpers, etc.)",
    },
    "minecraft": {
        "enabled": True,
        "bind": "minecraft",
        "description": "Minecraft integration commands",
    },
    "points": {
        "enabled": True,
        "bind": "points",
        "description": "Chat points commands",
    },
}


class CommandGroups:
    def __init__(self, config: dict[str, Any] | None = None):
        self._raw: dict[str, dict[str, Any]] = {}
        self._config = config or {}
        self.reload(config)

    def reload(self, config: dict[str, Any] | None = None) -> None:
        if config is not None:
            self._config = config
        cfg_groups = (self._config or {}).get("command_groups") or {}
        merged = {k: dict(v) for k, v in DEFAULT_GROUPS.items()}
        if isinstance(cfg_groups, dict):
            for key, val in cfg_groups.items():
                if not isinstance(val, dict):
                    continue
                base = merged.get(key, {"enabled": True})
                base.update(val)
                merged[key] = base
        self._raw = merged

    def is_enabled(self, group_id: str, *, integration_running: Optional[dict[str, bool]] = None) -> bool:
        gid = (group_id or "core").strip().lower() or "core"
        meta = self._raw.get(gid) or {"enabled": True, "always": gid == "core"}
        if meta.get("always"):
            return True
        if meta.get("enabled") is False:
            return False
        bind = meta.get("bind")
        if not bind:
            return bool(meta.get("enabled", True))
        # Bind to a config section (e.g. minecraft.enabled)
        section = (self._config or {}).get(bind) or {}
        if isinstance(section, dict) and section.get("enabled") is False:
            return False
        if integration_running is not None and bind in integration_running:
            return bool(integration_running.get(bind))
        return True

    def list_groups(self) -> list[dict[str, Any]]:
        out = []
        for key, meta in self._raw.items():
            out.append({
                "id": key,
                "enabled": meta.get("enabled", True),
                "always": bool(meta.get("always")),
                "bind": meta.get("bind"),
                "description": meta.get("description") or "",
            })
        return out

    def as_config_dict(self) -> dict[str, Any]:
        return {k: dict(v) for k, v in self._raw.items()}
