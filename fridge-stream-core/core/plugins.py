"""
Loads, starts and stops the game plugins in ``plugins/``.

Core boots fine with no plugins at all: no game cards, no game commands, no game books.
A plugin that fails to import or start is logged and shown on its dashboard card with the
error; the rest of Core keeps running.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import plugin_manifest
from core.plugin_api import HttpPlugin, PluginContext
from core.plugin_manifest import Manifest

log = logging.getLogger("core.plugins")

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LoadedPlugin:
    manifest: Manifest
    cls: Any = None
    error: str = ""          # import / start problem (manifest problems live on manifest.error)

    @property
    def id(self) -> str:
        return self.manifest.id


def _ensure_package(manifest: Manifest) -> str:
    """Make ``plugins.<id>`` importable from wherever the folder is (relative imports work)."""
    if "plugins" not in sys.modules:
        try:
            importlib.import_module("plugins")
        except ImportError:
            pkg = types.ModuleType("plugins")
            pkg.__path__ = []          # type: ignore[attr-defined]
            sys.modules["plugins"] = pkg
    name = f"plugins.{manifest.id}"
    mod = sys.modules.get(name)
    folder = str(manifest.path)
    if mod is not None and folder in list(getattr(mod, "__path__", []) or []):
        return name
    init = manifest.path / "__init__.py"
    if init.is_file():
        spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[folder])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)          # type: ignore[union-attr]
    else:
        mod = types.ModuleType(name)
        mod.__path__ = [folder]               # type: ignore[attr-defined]
        mod.__package__ = name
        sys.modules[name] = mod
    return name


def load_class(manifest: Manifest):
    """The plugin's class (or Core's HttpPlugin for manifest-only plugins)."""
    if manifest.kind == "http":
        return HttpPlugin
    pkg = _ensure_package(manifest)
    mod_name, cls_name = str(manifest.get("entry")).split(":", 1)
    module = importlib.import_module(f"{pkg}.{mod_name}")
    cls = getattr(module, cls_name, None)
    if cls is None:
        raise ImportError(f"{mod_name}.py has no {cls_name}")
    return cls


class PluginManager:
    def __init__(
        self,
        *,
        get_config: Callable[[], dict],
        games: Dict[str, Any],
        market: Any = None,
        store: Any = None,
        bus: Any = None,
        broadcast: Any = None,
        root: Path = ROOT,
    ):
        self.get_config = get_config
        self.games = games                      # shared with StreamCore.games / CoreState.games
        self.market = market
        self.store = store
        self.bus = bus
        self.broadcast = broadcast
        self.root = root
        self.loaded: Dict[str, LoadedPlugin] = {}
        self.broken: List[Manifest] = []
        self.start_errors: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_all(self) -> None:
        self.loaded = {}
        self.broken = [m for m in plugin_manifest.discover() if not m.ok]
        for m in plugin_manifest.installed():
            lp = LoadedPlugin(m)
            try:
                lp.cls = load_class(m)
            except Exception as exc:
                lp.error = f"could not load: {exc}"
                log.exception("Plugin %s failed to load", m.id)
            self.loaded[m.id] = lp
        if self.loaded:
            log.info("Game plugins installed: %s", ", ".join(sorted(self.loaded)))
        else:
            log.info("No game plugins installed (plugins/ is empty)")

    def context(self, plugin_id: str) -> PluginContext:
        lp = self.loaded[plugin_id]
        return PluginContext(
            id=plugin_id,
            folder=lp.manifest.path,
            root=self.root,
            data_dir=self.root / "data" / "plugins" / plugin_id,
            get_config=self.get_config,
            market=self.market,
            store=self.store,
            bus=self.bus,
            broadcast=self.broadcast,
        )

    def make(self, plugin_id: str, config: Optional[dict] = None):
        """A plugin instance (not started)."""
        lp = self.loaded[plugin_id]
        cfg = config if config is not None else self.get_config()
        ctx = self.context(plugin_id)
        if lp.cls is HttpPlugin:
            inst = HttpPlugin(cfg, ctx, lp.manifest.data)
        else:
            inst = lp.cls(cfg, ctx)
        if getattr(inst, "ctx", None) is None:
            inst.ctx = ctx
        if self.market is not None and hasattr(inst, "attach_market"):
            inst.attach_market(self.market)
        if self.store is not None and hasattr(inst, "attach_store"):
            inst.attach_store(self.store)
        return inst

    # ------------------------------------------------------------------
    # Start / stop (game toggles still need a Core restart)
    # ------------------------------------------------------------------

    async def start_enabled(self) -> None:
        cfg = self.get_config() or {}
        for pid, lp in self.loaded.items():
            if lp.error:
                continue
            if not (cfg.get(pid) or {}).get("enabled", False):
                log.info("%s plugin off (%s.enabled=false)", lp.manifest.name, pid)
                continue
            try:
                inst = self.make(pid, cfg)
                await inst.start()
            except Exception as exc:
                self.start_errors[pid] = f"could not start: {exc}"
                log.exception("Plugin %s failed to start", pid)
                continue
            self.start_errors.pop(pid, None)
            self.games[pid] = inst

    async def stop_all(self) -> None:
        for pid in list(self.games):
            if pid not in self.loaded:
                continue
            inst = self.games.pop(pid)
            try:
                await inst.stop()
            except Exception:
                log.exception("Plugin %s stop failed", pid)

    def apply_config(self, cfg: dict) -> None:
        """A dashboard save replaced the live config (plugins read it live); tell those that care."""
        for pid, inst in list(self.games.items()):
            if pid not in self.loaded:
                continue
            fn = getattr(inst, "apply_config", None)
            if callable(fn):
                try:
                    fn(cfg)
                except Exception:
                    log.exception("Plugin %s apply_config failed", pid)

    # ------------------------------------------------------------------
    # Hooks Core asks plugins for
    # ------------------------------------------------------------------

    def register_routes(self, router, get_running_for: Callable[[str], Callable[[], Any]]) -> None:
        """Installed plugins add their API routes (they answer even while the game is off)."""
        for pid, lp in self.loaded.items():
            fn = getattr(lp.cls, "routes", None) if lp.cls else None
            if not callable(fn):
                continue
            try:
                fn(router, get_running_for(pid))
            except Exception:
                log.exception("Plugin %s routes failed", pid)

    async def state_fragments(self) -> dict:
        """Extra keys for the overlay "update" payload (Minecraft stats, OpenTTD snapshot ...)."""
        out: dict = {}
        for pid, inst in list(self.games.items()):
            fn = getattr(inst, "state_fragment", None)
            if not callable(fn):
                continue
            try:
                part = await fn()
            except Exception:
                log.exception("Plugin %s state_fragment failed", pid)
                continue
            if isinstance(part, dict):
                out.update(part)
        return out

    def dividend_defaults(self, game: str, body: dict, market_cfg: dict) -> dict:
        lp = self.loaded.get(game)
        fn = getattr(lp.cls, "dividend_defaults", None) if lp and lp.cls else None
        if not callable(fn):
            return {}
        try:
            return fn(body, market_cfg) or {}
        except Exception:
            log.exception("Plugin %s dividend_defaults failed", game)
            return {}

    def overlays(self, pid: str, base: str) -> list[dict]:
        """Overlay links for a plugin: its own list when running, else from the manifest."""
        inst = self.games.get(pid)
        fn = getattr(inst, "overlay_catalog", None) if inst is not None else None
        if callable(fn):
            try:
                return list(fn())
            except Exception:
                log.exception("Plugin %s overlay_catalog failed", pid)
        lp = self.loaded.get(pid)
        if lp is None:
            return []
        m = lp.manifest
        out = [
            {"name": str(o.get("name") or o.get("file")), "url": f"{base}/overlay/{o.get('file')}",
             "notes": str(o.get("notes") or "")}
            for o in m.get("overlays") or [] if isinstance(o, dict) and o.get("file")
        ]
        section = (self.get_config() or {}).get(pid) or {}
        key = str((m.get("http") or {}).get("base_url_key") or "bridge_url")
        bridge = str(section.get(key) or (m.get("config_defaults") or {}).get(key) or "").rstrip("/")
        if bridge:
            out += [
                {"name": str(p.get("name") or p.get("path")), "url": f"{bridge}/{str(p.get('path') or '').lstrip('/')}",
                 "notes": str(p.get("notes") or "")}
                for p in m.get("bridge_overlays") or [] if isinstance(p, dict)
            ]
        return out

    def info(self, cfg: dict, base: str) -> list[dict]:
        """Everything the dashboard needs to draw the Plugins cards and Market sub-pages."""
        rows = []
        for pid, lp in sorted(self.loaded.items()):
            m = lp.manifest
            section = dict(cfg.get(pid) or {})
            inst = self.games.get(pid)
            extra: dict = {}
            fn = getattr(inst, "status", None) if inst is not None else None
            if callable(fn):
                try:
                    extra = dict(fn() or {})
                except Exception:
                    log.exception("Plugin %s status failed", pid)
            market_lines: list = []
            fn = getattr(inst, "market_status", None) if inst is not None else None
            if callable(fn):
                try:
                    market_lines = [str(x) for x in (fn() or [])]
                except Exception:
                    log.exception("Plugin %s market_status failed", pid)
            rows.append({
                "id": pid,
                "name": m.name,
                "version": str(m.get("version") or ""),
                "kind": m.kind,
                "description": str(m.get("description") or ""),
                "links": list(m.get("links") or []),
                "settings": list(m.get("settings") or []),
                "market": m.get("market") or None,
                "market_status": market_lines,
                "values": section,
                "configured_enabled": bool(section.get("enabled")),
                "running": pid in self.games,
                "error": lp.error or self.start_errors.get(pid, ""),
                "overlays": self.overlays(pid, base),
                "status": extra,
            })
        for m in self.broken:
            rows.append({
                "id": m.id, "name": m.name, "version": str(m.get("version") or ""), "kind": m.kind,
                "description": str(m.get("description") or ""), "links": [], "settings": [],
                "market": None, "market_status": [], "values": {}, "configured_enabled": False,
                "running": False, "error": m.error, "overlays": [], "status": {},
            })
        return rows
