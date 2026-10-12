"""Plugin API 2: feature plugins, services between plugins, start order, own database,
dashboard pages, settings moved from an old section, and the admin / game checks for
plugin routes. Run from fridge-stream-core:

    python -m unittest tests.test_plugin_features -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import plugin_manifest  # noqa: E402
from core.config import apply_moved_sections  # noqa: E402
from tests.test_plugins import TempPluginsDir, _write_plugin  # noqa: E402

BANK_PY = '''
from core.plugin_api import BasePlugin

class Ledger:
    def __init__(self):
        self.entries = []

class Bank(BasePlugin):
    name = "bank"

    async def start(self):
        self.ctx.get_config()["_order"].append("bank")
        self.ledger = Ledger()

    async def stop(self):
        self.ctx.get_config()["_order"].append("bank-stop")

    async def execute(self, req):
        return {"success": True, "reply": "bank says " + str(req.special)}

    def service(self, name):
        return self.ledger if name == "ledger" else None

    @staticmethod
    def payout_rates(body):
        return {"rate": 2, **body}

    @classmethod
    def routes(cls, router, get_running):
        from fastapi import Header, Request

        @router.post("/api/bank/mint")
        async def mint(request: Request):
            inst = get_running()
            inst.ctx.require_game(request)
            return {"ok": True}

        @router.get("/api/bank/admin")
        async def admin(x_admin_token: str = Header(None)):
            get_running().ctx.require_admin(x_admin_token)
            return {"ok": True}
'''

SHOP_PY = '''
from core.plugin_api import BasePlugin

class Shop(BasePlugin):
    name = "shop"

    async def start(self):
        self.ctx.get_config()["_order"].append("shop")
        self.ledger = self.ctx.service("ledger")

    async def stop(self):
        self.ctx.get_config()["_order"].append("shop-stop")

    async def execute(self, req):
        return {"success": True}
'''

BANK = {"id": "bank", "name": "Bank", "core_api": 2, "category": "feature", "entry": "plugin:Bank",
        "provides": ["ledger"], "config_moved_from": ["oldbank"], "specials": ["bank_balance"],
        "command_group": {"description": "Bank", "aliases": ["oldbank"]},
        "pages": [{"id": "main", "title": "Bank", "file": "pages/index.html", "nav": "On stream"}]}
# "aaa" sorts first, so only "after" puts it behind the bank
SHOP = {"id": "aaa", "core_api": 2, "entry": "plugin:Shop", "after": ["ledger"]}


class FeatureTests(TempPluginsDir):
    def setUp(self):
        super().setUp()
        _write_plugin(self.base, "bank", BANK, {"plugin.py": BANK_PY, "pages/index.html": "<p>bank page</p>",
                                               "secret.txt": "not a page"})
        _write_plugin(self.base, "aaa", SHOP, {"plugin.py": SHOP_PY})
        self.cfg = {"bank": {"enabled": True}, "aaa": {"enabled": True},
                    "points": {"admin_token": "tok-123456789"}, "_order": []}

    def test_manifest_fields(self):
        m = plugin_manifest.find("bank")
        self.assertEqual(m.category, "feature")
        self.assertEqual(m.provides, ["ledger"])
        self.assertEqual(m.pages[0]["nav"], "On stream")
        self.assertEqual(plugin_manifest.find("aaa").category, "game")
        self.assertEqual(plugin_manifest.moved_sections(), {"oldbank": "bank"})

    def test_bad_new_fields(self):
        cases = {
            "badcat": ({"category": "toy"}, "category"),
            "badprov": ({"provides": "ledger"}, "provides"),
            "badpage": ({"pages": [{"id": "x", "file": "pages/missing.html"}]}, "pages[0] file"),
            "escape": ({"pages": [{"id": "x", "file": "pages/../plugin.json"}]}, "pages[0] file"),
            "badnav": ({"pages": [{"id": "x", "file": "pages/a.html", "nav": "Elsewhere"}]}, "nav"),
            "selfmove": ({"config_moved_from": ["selfmove"]}, "own id"),
            "badspecial": ({"specials": ["Bad Name"]}, "specials"),
            "badalias": ({"command_group": {"aliases": "x"}}, "aliases"),
        }
        for pid, (extra, words) in cases.items():
            _write_plugin(self.base, pid, {"id": pid, "kind": "http", "http": {}, **extra}, {"pages/a.html": "x"})
        found = {m.id: m for m in plugin_manifest.discover(force=True)}
        for pid, (_, words) in cases.items():
            self.assertIn(words, found[pid].error, pid)

    def test_start_order_and_services(self):
        mgr = self.manager(self.cfg)
        asyncio.run(mgr.start_enabled())
        order = self.cfg["_order"]
        self.assertEqual(order, ["bank", "shop"])
        self.assertIs(mgr.games["aaa"].ledger, mgr.games["bank"].ledger)
        d = mgr.directory
        self.assertIs(d.running("bank"), mgr.games["bank"])
        self.assertIsNone(d.service("nothing"))
        self.assertEqual(d.class_hook("bank", "payout_rates")({"x": 1}), {"rate": 2, "x": 1})
        self.assertIsNone(d.class_hook("aaa", "payout_rates"))
        self.assertEqual(d.ids(), ["aaa", "bank"])
        asyncio.run(mgr.stop_all())
        self.assertEqual(order[2:], ["shop-stop", "bank-stop"])

    def test_service_missing_when_provider_off(self):
        self.cfg["bank"]["enabled"] = False
        mgr = self.manager(self.cfg)
        asyncio.run(mgr.start_enabled())
        self.assertIsNone(mgr.games["aaa"].ledger)

    def test_own_database(self):
        mgr = self.manager(self.cfg)
        ctx = mgr.context("bank")
        self.assertIs(ctx, mgr.context("bank"))

        async def go():
            await ctx.db.script("CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v INTEGER)")
            await ctx.db.executemany("INSERT INTO t VALUES (?, ?)", [("a", 1), ("b", 2)])
            await ctx.db.execute("UPDATE t SET v = v + 10 WHERE k = ?", ("a",))
            rows = await ctx.db.fetchall("SELECT * FROM t ORDER BY k")
            one = await ctx.db.fetchone("SELECT v FROM t WHERE k = 'zzz'")
            total = await ctx.db.transaction(lambda c: c.execute("SELECT SUM(v) FROM t").fetchone()[0])
            return rows, one, total

        rows, one, total = asyncio.run(go())
        self.assertEqual(rows, [{"k": "a", "v": 11}, {"k": "b", "v": 2}])
        self.assertIsNone(one)
        self.assertEqual(total, 13)
        self.assertTrue((self.base / "data" / "plugins" / "bank" / "bank.db").is_file())
        asyncio.run(mgr.stop_all())

    def test_moved_section(self):
        raw = {"oldbank": {"enabled": True, "rate": 5}}
        out = apply_moved_sections(raw)
        self.assertEqual(out["bank"], {"enabled": True, "rate": 5})
        self.assertIn("oldbank", out)                                  # old block kept
        mine = apply_moved_sections({"oldbank": {"rate": 5}, "bank": {"rate": 9}})
        self.assertEqual(mine["bank"], {"rate": 9})                    # own section wins
        filled = apply_moved_sections({"oldbank": {"enabled": False, "rate": 5, "fee": 2}, "bank": {"enabled": True}})
        self.assertEqual(filled["bank"], {"enabled": True, "rate": 5, "fee": 2})   # the rest comes from the old block

    def test_specials_aliases_and_moved_bind(self):
        from core.command_groups import bind_satisfied
        from core.models import ChatUser, ExecuteRequest, Platform

        self.assertEqual(plugin_manifest.special_owners(), {"bank_balance": "bank"})
        groups = plugin_manifest.group_defaults()
        self.assertEqual(groups["oldbank"]["bind"], "bank")             # old group name follows the plugin
        mgr = self.manager(self.cfg)
        self.assertEqual(mgr.special_owner("bank_balance"), "bank")
        self.assertIsNone(mgr.special_owner("points_balance"))
        # an old "bind: oldbank" in config.yaml now means "the bank plugin is running"
        self.assertEqual(bind_satisfied("oldbank", self.cfg, set())[0], False)
        self.assertEqual(bind_satisfied("oldbank", self.cfg, {"bank"})[0], True)
        asyncio.run(mgr.start_enabled())
        req = ExecuteRequest(command_name="balance", template="", args=[], special="bank_balance",
                             user=ChatUser(platform=Platform.KICK, id="1", username="viewer"))
        self.assertEqual(asyncio.run(mgr.games["bank"].execute(req))["reply"], "bank says bank_balance")
        asyncio.run(mgr.stop_all())

    def test_info_rows(self):
        mgr = self.manager(self.cfg)
        rows = {r["id"]: r for r in mgr.info(self.cfg, "")}
        self.assertEqual(rows["bank"]["category"], "feature")
        self.assertEqual(rows["bank"]["pages"][0]["url"], "/plugin-pages/bank/index.html")
        self.assertEqual(rows["aaa"]["pages"], [])

    def test_pages_and_route_checks(self):
        from fastapi.testclient import TestClient

        from api.server import CoreState, create_app

        mgr = self.manager(self.cfg)
        state = CoreState()
        state.config = self.cfg
        state.games = mgr.games
        state.plugins = mgr
        client = TestClient(create_app(state), base_url="http://127.0.0.1:3850",
                            client=("127.0.0.1", 50000))
        asyncio.run(mgr.start_enabled())

        res = client.get("/plugin-pages/bank/index.html")
        self.assertEqual(res.status_code, 200)
        self.assertIn("bank page", res.text)
        self.assertEqual(client.get("/plugin-pages/bank/../secret.txt").status_code, 404)
        self.assertEqual(client.get("/plugin-pages/bank/%2E%2E/secret.txt").status_code, 404)
        self.assertEqual(client.get("/plugin-pages/nobody/index.html").status_code, 404)

        self.assertEqual(client.post("/api/bank/mint").status_code, 200)              # a game on this PC
        browser = client.post("/api/bank/mint", headers={"Origin": "http://127.0.0.1:3850"})
        self.assertEqual(browser.status_code, 403)
        self.assertEqual(client.get("/api/bank/admin").status_code, 401)
        ok = client.get("/api/bank/admin", headers={"X-Admin-Token": "tok-123456789"})
        self.assertEqual(ok.status_code, 200)


if __name__ == "__main__":
    unittest.main()
