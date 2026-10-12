"""
Game plugin manifests (``plugins/<id>/plugin.json``).

Reads what is installed without importing any plugin code, so config defaults,
command groups and default commands can be built before Core starts anything.
The code side (importing, starting, routes) lives in ``core/plugins.py``.

A plugin folder:

    plugins/<id>/
      plugin.json      manifest (this module reads it)
      plugin.py        Python client (kind "python"; not needed for kind "http")
      commands.json    default chat commands for group <id> (optional)
      overlay/         pages served at /overlay/<file> next to Core's own (optional)
      pages/           dashboard pages served at /plugin-pages/<id>/<file> (optional, "pages" in plugin.json)

Writing one: docs/PLUGINS.md.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

log = logging.getLogger("core.plugin_manifest")

ROOT = Path(__file__).resolve().parent.parent

# Bumped when the plugin contract changes. A plugin asks for the version it needs ("core_api");
# 2 added "category", "provides" / "after", "pages", "config_moved_from" and ctx.plugins / ctx.db.
PLUGIN_API_VERSION = 2

# Game ids that used to be built into Core. Their command groups only switch on while the
# game is actually running, even when someone's config still says enabled: true but the
# plugin isn't installed (otherwise !spawn would fan out to whatever other game is running).
LEGACY_GAME_IDS = ("minecraft", "factorio", "granvir", "openttd")

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
FIELD_TYPES = {"text", "url", "number", "password", "checkbox", "list", "lines", "map", "select"}
KINDS = {"python", "http"}
CATEGORIES = {"game", "feature"}
# Sidebar groups a plugin page can go under (admin/index.html .nav-heading)
NAV_GROUPS = {"On stream", "Overlays", "Games", "People", "Settings"}
PAGE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

_cache: Optional[List["Manifest"]] = None
_reserved: set[str] = set()


@dataclass
class Manifest:
    id: str
    path: Path
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def name(self) -> str:
        return str(self.data.get("name") or self.id.replace("_", " ").title())

    @property
    def kind(self) -> str:
        return str(self.data.get("kind") or "python")

    @property
    def category(self) -> str:
        """"game" (a game link) or "feature" (adds something to Core itself, e.g. a market)."""
        return str(self.data.get("category") or "game")

    @property
    def provides(self) -> List[str]:
        """Services other plugins can ask for with ctx.plugins.service(name)."""
        return [str(x) for x in self.data.get("provides") or []]

    @property
    def after(self) -> List[str]:
        """Plugin ids or service names this plugin starts after (when they are installed)."""
        return [str(x) for x in self.data.get("after") or []]

    @property
    def pages(self) -> List[Dict[str, Any]]:
        out = []
        for pg in self.data.get("pages") or []:
            out.append({
                "id": str(pg["id"]),
                "title": str(pg.get("title") or self.name),
                "file": str(pg["file"]).replace("\\", "/").lstrip("/"),
                "nav": str(pg.get("nav") or ("Games" if self.category == "game" else "On stream")),
                "keywords": str(pg.get("keywords") or ""),
            })
        return out

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def plugins_dir() -> Path:
    """Where plugins live. STREAM_CORE_PLUGINS_DIR overrides it (tests, portable installs)."""
    env = os.environ.get("STREAM_CORE_PLUGINS_DIR", "").strip()
    return Path(env) if env else ROOT / "plugins"


def set_reserved_ids(names: Iterable[str]) -> None:
    """Core's own config sections; a plugin can't take one of those names."""
    global _reserved
    _reserved = {str(n) for n in names}
    reset_cache()


def reset_cache() -> None:
    global _cache
    _cache = None


def _check_fields(fields: Any, where: str) -> str:
    if fields is None:
        return ""
    if not isinstance(fields, list):
        return f"{where} must be a list"
    for i, f in enumerate(fields):
        if not isinstance(f, dict) or not str(f.get("key") or "").strip():
            return f"{where}[{i}] needs a key"
        if str(f.get("type") or "text") not in FIELD_TYPES:
            return f"{where}[{i}] has unknown type {f.get('type')!r}"
    return ""


def _check_pages(pages: Any, folder: Path) -> str:
    if pages is None:
        return ""
    if not isinstance(pages, list):
        return "pages must be a list"
    seen = set()
    for i, pg in enumerate(pages):
        if not isinstance(pg, dict):
            return f"pages[{i}] must be an object"
        pid = str(pg.get("id") or "")
        if not PAGE_ID_RE.match(pid) or pid in seen:
            return f"pages[{i}] needs a unique id (lowercase letters, digits, - or _)"
        seen.add(pid)
        rel = str(pg.get("file") or "").replace("\\", "/").lstrip("/")
        if not rel.startswith("pages/") or ".." in rel.split("/") or not (folder / rel).is_file():
            return f"pages[{i}] file must be an existing file in the plugin's pages/ folder"
        if pg.get("nav") is not None and str(pg.get("nav")) not in NAV_GROUPS:
            return f"pages[{i}] nav must be one of {sorted(NAV_GROUPS)}"
    return ""


def validate(data: Any, folder: Path) -> str:
    """Empty string when the manifest is usable, else why not (shown on the plugin's card)."""
    if not isinstance(data, dict):
        return "plugin.json must be a JSON object"
    pid = str(data.get("id") or "")
    if not ID_RE.match(pid):
        return f"id {pid!r} must be 2-32 lowercase letters, digits or _ (starting with a letter)"
    if pid != folder.name:
        return f"id {pid!r} does not match its folder name {folder.name!r}"
    if pid in _reserved:
        return f"id {pid!r} is one of Core's own settings sections"
    try:
        need = int(data.get("core_api") or 1)
    except (TypeError, ValueError):
        return "core_api must be a number"
    if need > PLUGIN_API_VERSION:
        return (
            f"made for a newer Stream Core (plugin API {need}, this Core has {PLUGIN_API_VERSION}); "
            "update Stream Core"
        )
    kind = str(data.get("kind") or "python")
    if kind not in KINDS:
        return f"kind must be one of {sorted(KINDS)}"
    if kind == "python":
        entry = str(data.get("entry") or "")
        if ":" not in entry:
            return 'python plugins need "entry": "module:ClassName"'
        mod = entry.split(":", 1)[0]
        if not (folder / f"{mod.replace('.', '/')}.py").is_file():
            return f"entry module {mod}.py is missing"
    if kind == "http" and not isinstance(data.get("http"), dict):
        return 'http plugins need an "http" block'
    if not isinstance(data.get("config_defaults") or {}, dict):
        return "config_defaults must be an object"
    for key, where in (("settings", "settings"),):
        err = _check_fields(data.get(key), where)
        if err:
            return err
    if str(data.get("category") or "game") not in CATEGORIES:
        return f"category must be one of {sorted(CATEGORIES)}"
    for key in ("provides", "after", "config_moved_from"):
        val = data.get(key)
        if val is not None and (not isinstance(val, list) or not all(isinstance(x, str) and ID_RE.match(x) for x in val)):
            return f"{key} must be a list of ids (lowercase letters, digits, _)"
    for old in data.get("config_moved_from") or []:
        if old == pid:
            return "config_moved_from can't name the plugin's own id"
    err = _check_pages(data.get("pages"), folder)
    if err:
        return err
    market = data.get("market")
    if market is not None:
        if not isinstance(market, dict):
            return "market must be an object"
        err = _check_fields(market.get("fields"), "market.fields")
        if err:
            return err
    return ""


def discover(force: bool = False) -> List[Manifest]:
    """Every plugin folder with a plugin.json, sorted by id (broken ones carry .error)."""
    global _cache
    if _cache is not None and not force:
        return _cache
    out: List[Manifest] = []
    base = plugins_dir()
    if base.is_dir():
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            mf = folder / "plugin.json"
            if not mf.is_file():
                continue
            try:
                data = json.loads(mf.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                out.append(Manifest(folder.name, folder, {}, f"plugin.json could not be read: {exc}"))
                continue
            err = validate(data, folder)
            out.append(Manifest(str((data or {}).get("id") or folder.name) if isinstance(data, dict) else folder.name,
                                folder, data if isinstance(data, dict) else {}, err))
            if err:
                log.warning("Plugin %s skipped: %s", folder.name, err)
    _cache = out
    return out


def installed() -> List[Manifest]:
    return [m for m in discover() if m.ok]


def find(plugin_id: str) -> Optional[Manifest]:
    for m in installed():
        if m.id == plugin_id:
            return m
    return None


def installed_ids() -> List[str]:
    return [m.id for m in installed()]


def game_ids() -> set[str]:
    """Group binds that need the game running, not just enabled in config."""
    return set(LEGACY_GAME_IDS) | set(installed_ids())


def config_defaults() -> Dict[str, Dict[str, Any]]:
    """{id: defaults} for config.yaml. Every game starts switched off."""
    out: Dict[str, Dict[str, Any]] = {}
    for m in installed():
        section = copy.deepcopy(m.get("config_defaults") or {})
        section["enabled"] = False
        out[m.id] = section
    return out


def group_defaults() -> Dict[str, Dict[str, Any]]:
    """One command group per plugin, bound to the game running."""
    out: Dict[str, Dict[str, Any]] = {}
    for m in installed():
        grp = m.get("command_group") or {}
        out[m.id] = {
            "enabled": True,
            "always": False,
            "bind": m.id,
            "description": str(grp.get("description") or m.get("description") or m.name),
        }
    return out


def default_commands() -> Dict[str, Dict[str, Any]]:
    """Each plugin's commands.json, merged. The user's own commands.json wins on a clash."""
    out: Dict[str, Dict[str, Any]] = {}
    for m in installed():
        path = m.path / "commands.json"
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Plugin %s commands.json unreadable: %s", m.id, exc)
            continue
        if not isinstance(raw, dict):
            continue
        for name, data in raw.items():
            if not isinstance(data, dict) or name in out:
                continue
            data = dict(data)
            data.setdefault("group", m.id)
            out[name] = data
    return out


def moved_sections() -> Dict[str, str]:
    """{old config section: plugin id} for plugins that took over a section under a new name."""
    out: Dict[str, str] = {}
    for m in installed():
        for old in m.get("config_moved_from") or []:
            out.setdefault(str(old), m.id)
    return out


def start_order(manifests: Iterable[Manifest]) -> List[Manifest]:
    """Plugins sorted so each starts after what its "after" names (ids or provided services).
    Ties keep id order; a loop is broken by id order rather than refusing to start."""
    pending = sorted(manifests, key=lambda m: m.id)
    owners: Dict[str, set] = {}
    for m in pending:
        owners.setdefault(m.id, set()).add(m.id)
        for svc in m.provides:
            owners.setdefault(svc, set()).add(m.id)
    deps = {m.id: {o for name in m.after for o in owners.get(name, ()) if o != m.id} for m in pending}
    done: List[Manifest] = []
    placed: set = set()
    while pending:
        ready = [m for m in pending if deps[m.id] <= placed] or pending[:1]
        m = ready[0]
        done.append(m)
        placed.add(m.id)
        pending.remove(m)
    return done


def overlay_dirs() -> List[Path]:
    return [m.path / "overlay" for m in installed() if (m.path / "overlay").is_dir()]


def market_books() -> List[Dict[str, Any]]:
    """Preview listings plugins ask for (book defaults to game:<id>)."""
    out = []
    for m in installed():
        for row in m.get("market_books") or []:
            if isinstance(row, dict) and row.get("symbol"):
                out.append({"book": f"game:{m.id}", **row})
    return out
