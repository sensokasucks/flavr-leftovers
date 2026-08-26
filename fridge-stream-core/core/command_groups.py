"""
Command groups — enable/disable sets of commands by integration or always-on.

Groups are defined in config.yaml under `command_groups` and referenced from
commands.json via `"group": "minecraft"` (etc.). Hot-reload without restart.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional


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
    "alerts": {
        "enabled": True,
        "always": True,
        "description": "Alert overlay helpers",
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
                base = merged.get(str(key), {"enabled": True})
                base.update(val)
                merged[str(key)] = base
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

    def active_ids(self, *, integration_running: Optional[dict[str, bool]] = None) -> set[str]:
        return {
            g["id"]
            for g in self.list_groups()
            if self.is_enabled(g["id"], integration_running=integration_running)
        }


def _as_running_map(running_games: Any) -> dict[str, bool]:
    if not running_games:
        return {}
    if isinstance(running_games, Mapping):
        return {str(k).lower(): bool(v) for k, v in running_games.items()}
    if isinstance(running_games, (str, bytes)):
        return {str(running_games).lower(): True}
    if isinstance(running_games, Iterable):
        return {str(k).lower(): True for k in running_games}
    return {}


def resolve_active_groups(
    config: dict[str, Any] | None = None,
    running_games: Any = None,
    extra: Mapping[str, Any] | None = None,
):
    running = _as_running_map(running_games)
    if extra:
        running.update({str(k).lower(): bool(v) for k, v in extra.items()})
    cg = CommandGroups(config or {})
    flags = {
        g["id"]: cg.is_enabled(g["id"], integration_running=running or None)
        for g in cg.list_groups()
    }
    for key, on in running.items():
        flags.setdefault(key, bool(on))
    return ActiveGroups(flags)


class ActiveGroups(dict):
    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return bool(dict.get(self, key, False))

    def __iter__(self):
        return (k for k, v in dict.items(self) if v)

    def enabled(self) -> set[str]:
        return {k for k, v in dict.items(self) if v}


def _iter_commands(commands: Any):
    if commands is None:
        return
    if hasattr(commands, "commands") and isinstance(getattr(commands, "commands"), dict):
        commands = commands.commands
    if isinstance(commands, dict):
        iterable = commands.values()
    elif isinstance(commands, Iterable) and not isinstance(commands, (str, bytes)):
        iterable = commands
    else:
        return
    seen: set[str] = set()
    for cmd in iterable:
        if isinstance(cmd, dict):
            name = str(cmd.get("name") or "")
            group = str(cmd.get("group") or "core")
            enabled = bool(cmd.get("enabled", True))
            description = str(cmd.get("description") or "")
        else:
            name = str(getattr(cmd, "name", "") or "")
            group = str(getattr(cmd, "group", "core") or "core")
            enabled = bool(getattr(cmd, "enabled", True))
            description = str(getattr(cmd, "description", "") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        yield {
            "name": name,
            "group": group.strip().lower() or "core",
            "enabled": enabled,
            "description": description,
        }


def catalog_status(
    config: dict[str, Any] | None = None,
    running_games: Any = None,
    extra: Mapping[str, Any] | None = None,
    commands: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    if commands is None:
        commands = kwargs.get("commands") or kwargs.get("router")
    groups = resolve_active_groups(config, running_games, extra)
    cg = CommandGroups(config or {})
    rows = []
    for g in cg.list_groups():
        gid = g["id"]
        rows.append({**g, "active": bool(dict.get(groups, gid, False))})
    command_rows = []
    by_group: dict[str, list[str]] = {}
    for row in _iter_commands(commands):
        gid = row["group"]
        row["active"] = bool(dict.get(groups, gid, gid == "core"))
        command_rows.append(row)
        by_group.setdefault(gid, []).append(row["name"])
    return {
        "ok": True,
        "groups": rows,
        "active": sorted(groups.enabled()),
        "commands": command_rows,
        "commands_by_group": by_group,
    }


group_catalog = catalog_status
get_catalog = catalog_status
list_active_groups = resolve_active_groups

__all__ = [
    "DEFAULT_GROUPS",
    "CommandGroups",
    "ActiveGroups",
    "resolve_active_groups",
    "catalog_status",
    "group_catalog",
    "get_catalog",
    "list_active_groups",
]
