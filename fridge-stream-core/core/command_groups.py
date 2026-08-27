"""
Command group catalog and live enablement.

Groups live in config.yaml under `command_groups`. Each command in
commands.json points at a group via its `group` field.

A group is active when:
  - `always` is true (core), or
  - `enabled` is true AND its optional `bind` is satisfied.

`bind` ties a group to an integration / config section:
  - bind: minecraft  → minecraft.enabled AND the game integration is running
  - bind: points     → points.enabled
  - bind: <section>  → that section's `enabled` flag

Unknown groups used by commands (not listed in config) default to
enabled + unbound, so they stay on until you add a catalog entry.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set

DEFAULT_GROUPS: Dict[str, Dict[str, Any]] = {
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
}

# Game ids that must be running, not just enabled in config.
GAME_BINDS = {"minecraft", "factorio"}


def _norm_name(name: Any) -> str:
    return str(name or "").strip().lower()


def normalize_group_spec(raw: Any, name: str = "") -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    always = bool(data.get("always", name == "core"))
    bind = data.get("bind")
    if bind is not None:
        bind = str(bind).strip().lower() or None
        if bind in ("none", "null", "-"):
            bind = None
    enabled = True if always else bool(data.get("enabled", True))
    desc = data.get("description") or DEFAULT_GROUPS.get(name, {}).get("description") or ""
    return {
        "enabled": enabled,
        "always": always,
        "bind": bind,
        "description": str(desc),
    }


def merge_group_catalog(
    configured: Optional[dict],
    extra_names: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Defaults + config.yaml + groups referenced by commands."""
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in DEFAULT_GROUPS.items():
        out[name] = normalize_group_spec(spec, name)

    if isinstance(configured, dict):
        for raw_name, spec in configured.items():
            name = _norm_name(raw_name)
            if not name:
                continue
            base = out.get(name, {})
            merged = normalize_group_spec({**base, **(spec if isinstance(spec, dict) else {})}, name)
            if name == "core":
                merged["always"] = True
                merged["enabled"] = True
            out[name] = merged

    for raw in extra_names or []:
        name = _norm_name(raw)
        if name and name not in out:
            out[name] = normalize_group_spec({"enabled": True, "always": False, "bind": None}, name)
    return out


def bind_satisfied(
    bind: Optional[str],
    config: dict,
    running_games: Set[str],
) -> tuple[bool, str]:
    """Return (ok, reason)."""
    if not bind:
        return True, "unbound"
    bind = bind.lower().strip()
    section = (config or {}).get(bind)
    enabled_flag = None
    if isinstance(section, dict) and "enabled" in section:
        enabled_flag = bool(section.get("enabled"))

    if bind in GAME_BINDS or bind in running_games:
        if enabled_flag is False:
            return False, f"{bind}.enabled=false"
        if bind not in running_games:
            return False, f"{bind} integration not running"
        return True, f"{bind} running"

    if enabled_flag is not None:
        if enabled_flag:
            return True, f"{bind}.enabled"
        return False, f"{bind}.enabled=false"

    return False, f"unknown bind '{bind}'"


def resolve_active_groups(
    config: dict,
    running_games: Optional[Iterable[str]] = None,
    extra_names: Optional[Iterable[str]] = None,
) -> Set[str]:
    games = {str(g).lower() for g in (running_games or [])}
    catalog = merge_group_catalog((config or {}).get("command_groups"), extra_names)
    active: Set[str] = set()
    for name, spec in catalog.items():
        if spec.get("always"):
            active.add(name)
            continue
        if not spec.get("enabled", True):
            continue
        ok, _ = bind_satisfied(spec.get("bind"), config or {}, games)
        if ok:
            active.add(name)
    active.add("core")
    return active


def catalog_status(
    config: dict,
    running_games: Optional[Iterable[str]] = None,
    extra_names: Optional[Iterable[str]] = None,
) -> list[dict]:
    """Admin-facing list of groups with live active/reason."""
    games = {str(g).lower() for g in (running_games or [])}
    catalog = merge_group_catalog((config or {}).get("command_groups"), extra_names)
    active = resolve_active_groups(config, games, extra_names)
    rows = []
    for name in sorted(catalog):
        spec = catalog[name]
        ok, reason = bind_satisfied(spec.get("bind"), config or {}, games)
        if spec.get("always"):
            reason = "always on"
        elif not spec.get("enabled", True):
            reason = "group disabled"
        rows.append({
            "id": name,
            "enabled": bool(spec.get("enabled", True)),
            "always": bool(spec.get("always")),
            "bind": spec.get("bind"),
            "description": spec.get("description") or "",
            "active": name in active,
            "reason": reason,
        })
    return rows


class CommandGroups:
    """Thin wrapper around the function API (older call sites)."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self.reload(config)

    def reload(self, config: dict | None = None) -> None:
        if config is not None:
            self._config = config
        extra = None
        self._catalog = merge_group_catalog((self._config or {}).get("command_groups"), extra)

    def is_enabled(self, group_id: str, *, integration_running: dict | None = None) -> bool:
        running = set((integration_running or {}).keys()) if integration_running else set()
        if integration_running:
            running = {k for k, v in integration_running.items() if v}
        return _norm_name(group_id) in resolve_active_groups(self._config, running)

    def list_groups(self) -> list[dict]:
        return catalog_status(self._config)

    def as_config_dict(self) -> dict:
        return {k: dict(v) for k, v in self._catalog.items()}

    def active_ids(self, *, integration_running: dict | None = None) -> set[str]:
        running = set()
        if integration_running:
            running = {k for k, v in integration_running.items() if v}
        return resolve_active_groups(self._config, running)
