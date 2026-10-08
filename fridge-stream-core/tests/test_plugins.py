"""Game plugins: manifests, loading, the bundled four, and the dashboard / API routes.
Run from fridge-stream-core:

    python -m unittest tests.test_plugins -v
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import plugin_manifest  # noqa: E402
from core.command_router import CommandRouter  # noqa: E402
from core.config import DEFAULTS, _deep_merge  # noqa: E402
from core.permissions import PermissionManager  # noqa: E402
from core.plugin_api import BasePlugin, HttpPlugin  # noqa: E402
from core.plugins import PluginManager  # noqa: E402

BUNDLED = ("factorio", "granvir", "minecraft", "openttd")


def _write_plugin(base: Path, pid: str, manifest: dict, files: dict | None = None) -> Path:
    folder = base / pid
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, text in (files or {}).items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


DEMO_PY = '''
from core.plugin_api import BasePlugin

class Demo(BasePlugin):
    name = "demo"
    started = False

    async def start(self):
        Demo.started = True

    async def stop(self):
        Demo.started = False

    async def execute(self, req):
        return {"success": True, "reply": "hi from demo"}

    def status(self):
        return {"detail": "level " + str(self.ctx.section.get("level"))}

    @classmethod
    def routes(cls, router, get_running):
        @router.get("/api/demo/state")
        async def demo_state():
            return {"running": get_running() is not None}
'''


class TempPluginsDir(unittest.TestCase):
    """Points plugin discovery at an empty temp folder for the test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        patcher = mock.patch.dict(os.environ, {"STREAM_CORE_PLUGINS_DIR": str(self.base)})
        patcher.start()
        self.addCleanup(patcher.stop)
        plugin_manifest.reset_cache()
        self.addCleanup(plugin_manifest.reset_cache)

    def manager(self, cfg: dict) -> PluginManager:
        games: dict = {}
        mgr = PluginManager(get_config=lambda: cfg, games=games, root=self.base)
        mgr.load_all()
        return mgr


class ManifestTests(TempPluginsDir):
    def test_empty_folder_means_no_games(self):
        self.assertEqual(plugin_manifest.installed(), [])
        self.assertEqual(plugin_manifest.config_defaults(), {})
        self.assertEqual(plugin_manifest.group_defaults(), {})
        self.assertEqual(plugin_manifest.default_commands(), {})
        self.assertEqual(plugin_manifest.market_books(), [])
        mgr = self.manager({})
        self.assertEqual(mgr.info({}, "http://127.0.0.1:3850"), [])
        asyncio.run(mgr.start_enabled())
        self.assertEqual(mgr.games, {})

    def test_bad_manifests_are_reported_not_loaded(self):
        _write_plugin(self.base, "newer", {"id": "newer", "core_api": 99, "kind": "http", "http": {}})
        _write_plugin(self.base, "wrongname", {"id": "other", "kind": "http", "http": {}})
        _write_plugin(self.base, "nomod", {"id": "nomod", "entry": "missing:Thing"})
        (self.base / "broken").mkdir()
        (self.base / "broken" / "plugin.json").write_text("{not json", encoding="utf-8")
        found = {m.path.name: m for m in plugin_manifest.discover(force=True)}
        self.assertIn("newer Stream Core", found["newer"].error)
        self.assertIn("folder name", found["wrongname"].error)
        self.assertIn("missing.py", found["nomod"].error)
        self.assertIn("could not be read", found["broken"].error)
        self.assertEqual(plugin_manifest.installed(), [])
        rows = self.manager({}).info({}, "")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["error"] for r in rows))

    def test_core_section_names_are_reserved(self):
        before = set(plugin_manifest._reserved)
        self.addCleanup(plugin_manifest.set_reserved_ids, before)
        plugin_manifest.set_reserved_ids({"market", "core"})
        _write_plugin(self.base, "market", {"id": "market", "kind": "http", "http": {}})
        self.assertIn("Core's own", plugin_manifest.discover(force=True)[0].error)

    def test_defaults_groups_commands_books(self):
        _write_plugin(self.base, "demo", {
            "id": "demo", "name": "Demo Game", "entry": "plugin:Demo",
            "config_defaults": {"enabled": True, "level": 3},
            "command_group": {"description": "Demo commands"},
            "market_books": [{"symbol": "DEMO", "name": "Demo Inc"}],
        }, {"plugin.py": DEMO_PY, "commands.json": json.dumps({"jump": {"aliases": ["j"]}})})
        self.assertEqual(plugin_manifest.config_defaults(), {"demo": {"enabled": False, "level": 3}})
        self.assertEqual(plugin_manifest.group_defaults()["demo"]["bind"], "demo")
        self.assertEqual(plugin_manifest.default_commands()["jump"]["group"], "demo")
        self.assertEqual(plugin_manifest.market_books(), [{"book": "game:demo", "symbol": "DEMO", "name": "Demo Inc"}])
        self.assertIn("demo", plugin_manifest.game_ids())
        self.assertIn("minecraft", plugin_manifest.game_ids())     # legacy id stays a game bind


class LoadingTests(TempPluginsDir):
    def test_python_plugin_starts_routes_and_status(self):
        from fastapi import APIRouter, FastAPI
        from fastapi.testclient import TestClient

        _write_plugin(self.base, "demo", {"id": "demo", "entry": "plugin:Demo"}, {"plugin.py": DEMO_PY})
        cfg = {"demo": {"enabled": True, "level": 7}}
        mgr = self.manager(cfg)
        router = APIRouter()
        mgr.register_routes(router, lambda pid: (lambda: mgr.games.get(pid)))
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        self.assertEqual(client.get("/api/demo/state").json(), {"running": False})
        asyncio.run(mgr.start_enabled())
        self.assertIn("demo", mgr.games)
        self.assertIsInstance(mgr.games["demo"], BasePlugin)
        self.assertEqual(client.get("/api/demo/state").json(), {"running": True})
        row = mgr.info(cfg, "")[0]
        self.assertTrue(row["running"])
        self.assertEqual(row["status"]["detail"], "level 7")
        cfg["demo"]["level"] = 9          # plugins read the live config
        self.assertEqual(mgr.info(cfg, "")[0]["status"]["detail"], "level 9")
        asyncio.run(mgr.stop_all())
        self.assertEqual(mgr.games, {})

    def test_import_error_is_isolated(self):
        _write_plugin(self.base, "crashy", {"id": "crashy", "entry": "plugin:Nope"},
                      {"plugin.py": "raise RuntimeError('boom')\n"})
        _write_plugin(self.base, "demo", {"id": "demo", "entry": "plugin:Demo"}, {"plugin.py": DEMO_PY})
        cfg = {"crashy": {"enabled": True}, "demo": {"enabled": True}}
        mgr = self.manager(cfg)
        asyncio.run(mgr.start_enabled())
        self.assertEqual(sorted(mgr.games), ["demo"])
        rows = {r["id"]: r for r in mgr.info(cfg, "")}
        self.assertIn("boom", rows["crashy"]["error"])
        self.assertEqual(rows["demo"]["error"], "")

    def test_disabled_plugin_is_not_started(self):
        _write_plugin(self.base, "demo", {"id": "demo", "entry": "plugin:Demo"}, {"plugin.py": DEMO_PY})
        mgr = self.manager({"demo": {"enabled": False}})
        asyncio.run(mgr.start_enabled())
        self.assertEqual(mgr.games, {})


class HttpPluginTests(unittest.TestCase):
    MANIFEST = {
        "id": "toy", "kind": "http",
        "config_defaults": {"bridge_url": "http://127.0.0.1:3999"},
        "http": {"base_url_key": "bridge_url", "health": "/stats", "execute": "/command", "metrics": "/api/metrics"},
        "bridge_overlays": [{"name": "Toy overlay", "path": "/overlay.html"}],
    }

    def test_execute_metrics_health(self):
        import httpx

        from core.models import ChatUser, ExecuteRequest, MetricsSnapshot, Platform

        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path, request.headers.get("X-Fridge-Core"),
                         json.loads(request.content) if request.content else None))
            if request.url.path == "/stats":
                return httpx.Response(200, json={"alive": 1})
            if request.url.path == "/command":
                return httpx.Response(200, json={"success": True, "reply": "ok"})
            return httpx.Response(200, json={})

        plug = HttpPlugin({"toy": {"enabled": True, "bridge_url": "http://bridge:1/"}}, None, self.MANIFEST)
        self.assertEqual(plug.overlay_catalog()[0]["url"], "http://bridge:1/overlay.html")

        async def run():
            await plug.start()
            await plug._client.aclose()
            plug._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"X-Fridge-Core": "1"})
            req = ExecuteRequest(command_name="spawn", template="", args=["wolf"], qty=2,
                                 user=ChatUser(platform=Platform.TWITCH, id="1", username="sen"),
                                 platform=Platform.TWITCH)
            res = await plug.execute(req)
            snap = MetricsSnapshot(viewers=5, cpm=1.0, command_rate=0.5, power_level=3)
            await plug.on_metrics(snap)
            healthy = await plug.health()
            await plug.stop()
            return res, healthy

        res, healthy = asyncio.run(run())
        self.assertEqual(res, {"success": True, "reply": "ok"})
        self.assertTrue(healthy)
        cmd = [s for s in seen if s[1] == "/command"][0]
        self.assertEqual(cmd[2], "1")
        self.assertEqual(cmd[3], {"command": "spawn", "args": ["wolf"], "qty": 2, "user": "sen", "platform": "twitch"})
        self.assertEqual([s for s in seen if s[1] == "/api/metrics"][0][3]["powerLevel"], 3)
        self.assertEqual(plug.last_stats, {"alive": 1})

    def test_not_running(self):
        from core.models import ExecuteRequest

        plug = HttpPlugin({"toy": {"enabled": False}}, None, self.MANIFEST)
        res = asyncio.run(plug.execute(ExecuteRequest(command_name="x", template="", args=[])))
        self.assertFalse(res["success"])


class BundledPluginTests(unittest.TestCase):
    """The four games that used to be built in, from the real plugins/ folder."""

    def setUp(self):
        os.environ.pop("STREAM_CORE_PLUGINS_DIR", None)
        plugin_manifest.reset_cache()
        self.addCleanup(plugin_manifest.reset_cache)

    def test_all_four_install_cleanly(self):
        found = {m.id: m for m in plugin_manifest.discover(force=True)}
        for pid in BUNDLED:
            self.assertIn(pid, found)
            self.assertEqual(found[pid].error, "", pid)
        mgr = PluginManager(get_config=lambda: DEFAULTS, games={})
        mgr.load_all()
        for pid in BUNDLED:
            self.assertEqual(mgr.loaded[pid].error, "", pid)

    def test_config_defaults_kept(self):
        # same defaults as when the games were built in, and all off
        for pid in BUNDLED:
            self.assertFalse(DEFAULTS[pid]["enabled"], pid)
        self.assertEqual(DEFAULTS["minecraft"]["server_mod_url"], "http://127.0.0.1:3853")
        self.assertEqual(DEFAULTS["granvir"]["bridge_url"], "http://127.0.0.1:3855")
        self.assertEqual(DEFAULTS["command_groups"]["minecraft"]["bind"], "minecraft")
        self.assertFalse(DEFAULTS["command_groups"]["openttd"]["always"])

    def test_manifest_fields_reference_real_defaults(self):
        for pid in BUNDLED:
            m = plugin_manifest.find(pid)
            fields = list(m.get("settings") or []) + list((m.get("market") or {}).get("fields") or [])
            for f in fields:
                cur = DEFAULTS[pid]
                for part in str(f["key"]).split("."):
                    self.assertIn(part, cur, f"{pid}: {f['key']}")
                    cur = cur[part]

    def test_plugin_commands_merge_under_the_users_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "commands.json"
            # the user's file renamed !spawn's alias and dropped nothing else
            path.write_text(json.dumps({
                "spawn": {"group": "minecraft", "aliases": ["mob"], "template": "summon {entity}"},
                "points": {"group": "points"},
            }), encoding="utf-8")
            router = CommandRouter(
                commands_path=path,
                permission_manager=PermissionManager(DEFAULTS),
                default_commands=plugin_manifest.default_commands,
            )
            cmds = router.commands
            self.assertEqual(cmds["spawn"].aliases, ["mob"])          # the file wins
            self.assertIn("points", cmds)
            plugin_only = set(plugin_manifest.default_commands()) - {"spawn"}
            self.assertTrue(plugin_only)
            for name in plugin_only:
                self.assertIn(name, cmds)                                # plugin defaults fill the rest

    def test_old_urls_still_answer(self):
        from fastapi.testclient import TestClient

        from api.server import CoreState, create_app

        state = CoreState()
        state.config = DEFAULTS
        state.games = {}
        mgr = PluginManager(get_config=lambda: state.config, games=state.games)
        mgr.load_all()
        state.plugins = mgr
        app = create_app(state)
        with TestClient(app, base_url="http://127.0.0.1:3850") as client:
            self.assertEqual(client.get("/api/stats").json(), {})
            ottd = client.get("/api/openttd/state")
            self.assertEqual(ottd.status_code, 200)
            for page in ("openttd.html", "openttd-ticker.html", "market-openttd.html",
                         "market-minecraft.html", "market-factorio.html", "overlay.html"):
                self.assertEqual(client.get("/overlay/" + page).status_code, 200, page)
            self.assertEqual(client.get("/overlay/nope-not-here.html").status_code, 404)

    def test_factorio_dividend_defaults(self):
        mgr = PluginManager(get_config=lambda: DEFAULTS, games={})
        mgr.load_all()
        self.assertEqual(mgr.dividend_defaults("factorio", {"unit": "items"}, {})["symbol"], "FACT")
        self.assertEqual(mgr.dividend_defaults("factorio", {}, {})["symbol"], "PWR")
        self.assertEqual(mgr.dividend_defaults("granvir", {}, {}), {})


class AdminPluginRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import admin_routes
        from api.server import CoreState

        os.environ.pop("STREAM_CORE_PLUGINS_DIR", None)
        plugin_manifest.reset_cache()
        self.state = CoreState()
        self.state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": "tok-123456789"}})
        self.state.games = {}
        mgr = PluginManager(get_config=lambda: self.state.config, games=self.state.games)
        mgr.load_all()
        self.state.plugins = mgr
        app = FastAPI()
        app.include_router(admin_routes.create_admin_router(self.state))
        self.client = TestClient(app)
        self.headers = {"X-Admin-Token": "tok-123456789"}
        self.saved = []
        p1 = mock.patch.object(admin_routes, "save_config", side_effect=lambda c: self.saved.append(c) or Path("x"))
        p2 = mock.patch.object(admin_routes, "load_config", side_effect=lambda *a, **k: self.state.config)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_list(self):
        res = self.client.get("/api/admin/plugins", headers=self.headers)
        self.assertEqual(res.status_code, 200, res.text)
        ids = [p["id"] for p in res.json()["plugins"]]
        for pid in BUNDLED:
            self.assertIn(pid, ids)

    def test_save_settings(self):
        url = "/api/admin/plugins/minecraft/settings"
        res = self.client.put(url, headers=self.headers, json={"values": {"player_name": "Sen"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["restart_needed"])
        self.assertEqual(self.state.config["minecraft"]["player_name"], "Sen")
        self.assertEqual(self.saved[-1]["minecraft"]["player_name"], "Sen")
        self.assertIn("command_groups", self.saved[-1])                  # the rest of config kept
        bad = self.client.put(url, headers=self.headers, json={"values": {"nope": 1}})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.put("/api/admin/plugins/nope/settings", headers=self.headers,
                                         json={"values": {}}).status_code, 404)

    def test_market_settings(self):
        res = self.client.put("/api/admin/market/settings", headers=self.headers,
                              json={"enabled": True, "hourly_cap_points": 500})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(self.state.config["market"]["enabled"])

    def test_commands_list_marks_plugin_defaults(self):
        from core.command_router import CommandRouter

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "commands.json"
            path.write_text(json.dumps({"points": {"group": "points"}}), encoding="utf-8")
            self.state.router = CommandRouter(commands_path=path, permission_manager=PermissionManager(DEFAULTS),
                                              default_commands=plugin_manifest.default_commands)
            res = self.client.get("/api/admin/commands", headers=self.headers)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("spawn", json.dumps(res.json()))


class CoerceFieldTests(unittest.TestCase):
    def test_types(self):
        from api.admin_routes import _SKIP, coerce_plugin_field

        self.assertEqual(coerce_plugin_field({"type": "number"}, "4"), 4)
        self.assertEqual(coerce_plugin_field({"type": "number", "step": 0.1}, "0.5"), 0.5)
        self.assertIs(coerce_plugin_field({"type": "number"}, ""), _SKIP)
        self.assertIsNone(coerce_plugin_field({"type": "number", "nullable": True}, ""))
        with self.assertRaises(ValueError):
            coerce_plugin_field({"type": "number", "min": 1}, "0")
        self.assertEqual(coerce_plugin_field({"type": "list", "upper": True}, "a, b\nc"), ["A", "B", "C"])
        self.assertEqual(coerce_plugin_field({"type": "lines"}, "x y\n\nz"), ["x y", "z"])
        self.assertTrue(coerce_plugin_field({"type": "checkbox"}, 1))
        self.assertEqual(
            coerce_plugin_field({"type": "map"}, "minecraft:diamond:2\nminecraft:iron_ingot=1"),
            {"minecraft:diamond": 2, "minecraft:iron_ingot": 1},
        )


if __name__ == "__main__":
    unittest.main()
