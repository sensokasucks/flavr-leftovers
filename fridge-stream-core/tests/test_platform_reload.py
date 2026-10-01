"""Chat platform settings apply without restarting Core.

    python -m unittest tests.test_platform_reload -v
"""

from __future__ import annotations

import asyncio
import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main
from api.server import CoreState
from core.config import DEFAULTS, _deep_merge
from core.event_bus import EventBus
from core.metrics import MetricsAggregator


class FakeAdapter:
    """Stands in for Kick/Twitch/YouTube; records what it was started with."""

    started: list = []
    stopped: list = []
    name = "fake"

    def __init__(self, config, bus, metrics):
        self.config = config
        self.section = copy.deepcopy(config.get(self.name) or {})
        self._running = False

    async def start(self):
        if (self.section.get("channel") or self.section.get("channel_slug") or "") == "":
            return  # real adapters log and return when the channel is unset
        if self.name == "kick" and not self.section.get("chatroom_id"):
            # like KickAdapter._persist_chatroom_id
            kick = dict(self.config.get("kick") or {})
            kick["chatroom_id"] = 1000 + len(kick.get("channel_slug", ""))
            self.config["kick"] = kick
            self.section = copy.deepcopy(kick)
        self._running = True
        FakeAdapter.started.append((self.name, self.section))

    async def stop(self):
        if self._running:
            FakeAdapter.stopped.append(self.name)
        self._running = False


def _fake(name):
    return type(f"Fake{name.title()}", (FakeAdapter,), {"name": name})


def make_core(overrides: dict) -> "main.StreamCore":
    config = _deep_merge(DEFAULTS, overrides)
    core = main.StreamCore.__new__(main.StreamCore)
    core.config = config
    core.bus = EventBus()
    core.metrics = MetricsAggregator(config)
    core.adapters = {}
    core._platform_applied = {}
    core._platform_lock = asyncio.Lock()
    core._kick_stale_rooms = set()
    core.state = CoreState()
    core.state.config = config
    core.state.adapters = core.adapters
    return core


class PlatformReloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeAdapter.started = []
        FakeAdapter.stopped = []
        patcher = mock.patch.dict(
            main.PLATFORM_ADAPTERS,
            {n: _fake(n) for n in ("kick", "twitch", "youtube")},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Never touch the real config.yaml
        for target in ("main.load_config", "core.config.save_config"):
            p = mock.patch(target, side_effect=lambda *a, **k: copy.deepcopy(self.core.config))
            p.start()
            self.addCleanup(p.stop)

    async def _boot(self, overrides):
        self.core = make_core(overrides)
        for name in main.PLATFORM_ADAPTERS:
            await self.core._start_platform(name)
        FakeAdapter.started = []
        FakeAdapter.stopped = []

    def _save(self, **sections):
        """What PUT /config does: a fresh dict replaces state.config."""
        fresh = copy.deepcopy(self.core.state.config)
        for key, val in sections.items():
            fresh[key] = {**(fresh.get(key) or {}), **val}
        self.core.state.config = fresh

    async def test_enable_platform_live(self):
        await self._boot({})
        self.assertEqual(self.core.adapters, {})
        self._save(twitch={"enabled": True, "channel": "fridge"})
        info = await self.core.apply_platforms()
        self.assertEqual(info["changed"], ["twitch"])
        self.assertEqual(info["running"], ["twitch"])
        self.assertEqual(FakeAdapter.started[0][1]["channel"], "fridge")

    async def test_only_changed_platform_reconnects(self):
        await self._boot({
            "twitch": {"enabled": True, "channel": "fridge"},
            "youtube": {"enabled": True, "channel": "x", "video_id": "old"},
        })
        yt_before = self.core.adapters["youtube"]
        self._save(twitch={"channel": "otherchan"})
        info = await self.core.apply_platforms()
        self.assertEqual(info["changed"], ["twitch"])
        self.assertIs(self.core.adapters["youtube"], yt_before)
        self.assertEqual(FakeAdapter.stopped, ["twitch"])

    async def test_unchanged_save_is_noop(self):
        await self._boot({"twitch": {"enabled": True, "channel": "fridge"}})
        self._save()
        info = await self.core.apply_platforms()
        self.assertEqual(info["changed"], [])
        self.assertEqual(FakeAdapter.stopped, [])

    async def test_disable_platform_stops_and_clears_viewers(self):
        await self._boot({"twitch": {"enabled": True, "channel": "fridge"}})
        self.core.metrics.set_viewers("twitch", 50)
        self._save(twitch={"enabled": False})
        await self.core.apply_platforms()
        self.assertNotIn("twitch", self.core.adapters)
        self.assertEqual(self.core.metrics.total_viewers, 0)

    async def test_force_reconnect(self):
        await self._boot({"twitch": {"enabled": True, "channel": "fridge"}})
        old = self.core.adapters["twitch"]
        info = await self.core.apply_platforms(force=("twitch",))
        self.assertEqual(info["changed"], ["twitch"])
        self.assertIsNot(self.core.adapters["twitch"], old)

    async def test_misconfigured_platform_not_listed_running(self):
        await self._boot({})
        self._save(twitch={"enabled": True, "channel": ""})
        info = await self.core.apply_platforms()
        self.assertEqual(info["running"], [])

    async def test_kick_channel_switch_drops_old_chatroom(self):
        await self._boot({"kick": {"enabled": True, "channel_slug": "abc", "chatroom_id": 55}})
        # The admin form sends back the old chatroom_id with the new slug
        self._save(kick={"channel_slug": "newchannel", "chatroom_id": 55})
        await self.core.apply_platforms()
        section = FakeAdapter.started[-1][1]
        self.assertEqual(section["channel_slug"], "newchannel")
        self.assertNotEqual(section.get("chatroom_id"), 55)
        # A later reload of the stale file must not bring the old room back
        FakeAdapter.started = []
        self._save(kick={"channel_slug": "newchannel", "chatroom_id": 55})
        info = await self.core.apply_platforms()
        self.assertEqual(info["changed"], [])

    async def test_kick_losing_cached_chatroom_is_not_a_change(self):
        await self._boot({"kick": {"enabled": True, "channel_slug": "abc"}})
        fresh = copy.deepcopy(self.core.state.config)
        fresh["kick"].pop("chatroom_id", None)
        self.core.state.config = fresh
        info = await self.core.apply_platforms()
        self.assertEqual(info["changed"], [])


class AdminRouteTests(unittest.TestCase):
    def test_put_config_applies_platforms_and_reconnect_route(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import admin_routes

        state = CoreState()
        state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": "tok-123456789"}})
        calls = []

        async def apply_platforms(force=()):
            calls.append(tuple(force))
            return {"changed": ["twitch"], "running": ["twitch"]}

        state.apply_platforms = apply_platforms
        app = FastAPI()
        app.include_router(admin_routes.create_admin_router(state))
        client = TestClient(app)
        headers = {"X-Admin-Token": "tok-123456789"}
        with mock.patch.object(admin_routes, "save_config", return_value=Path("config.yaml")), \
                mock.patch.object(admin_routes, "load_config", return_value=state.config):
            res = client.put("/api/admin/config", json={"config": state.config}, headers=headers)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Reconnected twitch", res.json()["message"])
        self.assertEqual(calls, [()])

        res = client.post("/api/admin/platforms/twitch/reconnect", headers=headers)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(calls[-1], ("twitch",))
        self.assertEqual(client.post("/api/admin/platforms/nope/reconnect", headers=headers).status_code, 404)


if __name__ == "__main__":
    unittest.main()
