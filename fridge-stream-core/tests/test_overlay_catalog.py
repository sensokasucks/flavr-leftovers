"""The overlay catalog behind Sources & overlays: every listed page exists, every switch it
lists is one the page really reads, plugin manifests follow the same shape, and the status
endpoint hands the switches to the dashboard. Run from fridge-stream-core:

    python -m unittest tests.test_overlay_catalog -v
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.overlay_catalog import OVERLAYS, by_id, default_query, sources  # noqa: E402

TYPES = {"bool", "tri", "number", "text", "select", "multi"}


def page_source(file_name: str, folder: Path) -> str:
    """The page plus every local script it loads (a switch may be read in chat.js, market.js ...)."""
    html = (folder / file_name).read_text(encoding="utf-8")
    text = html
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
        # plugin pages are served merged with Core's overlay folder, so look in both
        for path in (folder / src, ROOT / "overlay" / src):
            if path.is_file():
                text += path.read_text(encoding="utf-8")
                break
    # market pages share market.js
    if "market" in file_name:
        text += (ROOT / "overlay" / "market.js").read_text(encoding="utf-8")
    return text


def check_params(test: unittest.TestCase, params: list, text: str, where: str) -> None:
    keys = set()
    for p in params:
        test.assertIn(p["type"], TYPES, f"{where}: {p}")
        test.assertTrue(p.get("key") and p.get("label"), f"{where}: {p}")
        test.assertNotIn(p["key"], keys, f"{where}: duplicate switch {p['key']}")
        keys.add(p["key"])
        if p["type"] in ("select", "multi", "tri"):
            test.assertTrue(p.get("options"), f"{where}: {p['key']} needs options")
        # the page must actually read the switch
        test.assertRegex(text, r'["\']' + re.escape(p["key"]) + r'["\']', f"{where}: page never reads ?{p['key']}")


class CatalogTests(unittest.TestCase):
    def test_pages_exist_and_switches_are_real(self):
        ids = set()
        for o in OVERLAYS:
            self.assertNotIn(o["id"], ids)
            ids.add(o["id"])
            path = ROOT / "overlay" / o["file"]
            self.assertTrue(path.is_file(), o["file"])
            check_params(self, o.get("params") or [], page_source(o["file"], ROOT / "overlay"), o["id"])
            for s in o.get("settings") or []:
                self.assertTrue(s["hash"].startswith("#"), s)
            for c in o.get("config") or []:
                self.assertIn(c["type"], ("bool", "number"), c)
                self.assertIn(".", c["key"], c)

    def test_chat_switches_cover_the_dashboard_options(self):
        keys = {p["key"] for p in by_id("chat")["params"]}
        for k in ("platform", "platforms", "badges", "skin", "hide", "top", "avatars", "sound", "preview"):
            self.assertIn(k, keys)

    def test_default_query_only_for_required_text(self):
        self.assertEqual(default_query(by_id("market-chart")), "symbol=FACT")
        self.assertEqual(default_query(by_id("chat")), "")

    def test_sources_rows(self):
        rows = sources("http://127.0.0.1:3850")
        names = [r["name"] for r in rows]
        self.assertEqual(names[0], "Admin hub (this page)")
        chat = next(r for r in rows if r.get("id") == "chat")
        self.assertEqual(chat["url"], "http://127.0.0.1:3850/overlay/chat.html")
        self.assertEqual(chat["page"], chat["url"])
        self.assertTrue(chat["params"])
        chart = next(r for r in rows if r.get("id") == "market-chart")
        self.assertEqual(chart["url"], "http://127.0.0.1:3850/overlay/market-chart.html?symbol=FACT")
        self.assertIn("Replies + boards overlay", names)
        self.assertTrue(all("url" in r and "name" in r for r in rows))

    def test_plugin_manifests_use_the_same_shape(self):
        for manifest in (ROOT / "plugins").glob("*/plugin.json"):
            m = json.loads(manifest.read_text(encoding="utf-8"))
            folder = manifest.parent / "overlay"
            for o in m.get("overlays") or []:
                if o.get("params"):
                    # a plugin may list one of Core's own pages (Minecraft lists the metrics overlay)
                    where = folder if (folder / o["file"]).is_file() else ROOT / "overlay"
                    self.assertTrue((where / o["file"]).is_file(), o["file"])
                    check_params(self, o["params"], page_source(o["file"], where), f"{manifest.parent.name}/{o['file']}")


class StatusEndpointTests(unittest.TestCase):
    TOKEN = "unit-test-admin-token-123456"

    def test_status_carries_switches(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.admin_routes import create_admin_router
        from api.server import CoreState

        state = CoreState()
        state.config = {"points": {"admin_token": self.TOKEN}, "core": {"host": "127.0.0.1", "port": 3850}}
        app = FastAPI()
        app.include_router(create_admin_router(state))
        with TestClient(app) as client:
            st = client.get("/api/admin/status", headers={"X-Admin-Token": self.TOKEN}).json()
            rows = st["sources"]
            chat = next(r for r in rows if r.get("id") == "chat")
            self.assertTrue(any(p["key"] == "platform" for p in chat["params"]))
            self.assertEqual(chat["settings"][0]["hash"], "#chatlook")
            alerts = next(r for r in rows if r.get("id") == "alerts")
            self.assertEqual(alerts["config"][0]["key"], "overlay.alert_duration_ms")


if __name__ == "__main__":
    unittest.main()
