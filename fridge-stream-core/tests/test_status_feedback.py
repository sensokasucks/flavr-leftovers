"""Status says why a platform isn't connected; pasted links work; restarts are announced.

    python -m pytest tests/test_status_feedback.py -q
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import admin_routes  # noqa: E402
from api.server import CoreState  # noqa: E402
from core import restart  # noqa: E402
from core.config import DEFAULTS, _deep_merge  # noqa: E402
from core.platform_links import kick_slug, twitch_channel, youtube_video_id  # noqa: E402

TOKEN = "tok-123456789abc"
HEAD = {"X-Admin-Token": TOKEN}


class LinkTests(unittest.TestCase):
    def test_youtube_links(self):
        vid = "dQw4w9WgXcQ"
        for raw in (vid, f"https://www.youtube.com/watch?v={vid}", f"youtube.com/watch?feature=share&v={vid}",
                    f"https://youtu.be/{vid}?si=abc", f"https://www.youtube.com/live/{vid}?si=x",
                    f"https://m.youtube.com/shorts/{vid}",
                    f"https://studio.youtube.com/video/{vid}/livestreaming", f"  {vid}  "):
            self.assertEqual(youtube_video_id(raw), vid, raw)
        for bad in ("", "hello", "https://example.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/@channel"):
            self.assertEqual(youtube_video_id(bad), "", bad)

    def test_kick_and_twitch_links(self):
        self.assertEqual(kick_slug("https://kick.com/Sensoka"), "Sensoka")
        self.assertEqual(kick_slug("kick.com/sensoka/"), "sensoka")
        self.assertEqual(kick_slug("@sensoka"), "sensoka")
        self.assertEqual(kick_slug("https://kick.com/popout/sensoka/chat"), "sensoka")
        self.assertEqual(twitch_channel("https://www.twitch.tv/Sensoka_TV?sr=a"), "sensoka_tv")
        self.assertEqual(twitch_channel("#Fridge"), "fridge")
        self.assertEqual(twitch_channel("https://www.twitch.tv/popout/fridge/chat?popout="), "fridge")


class RestartNeededTests(unittest.TestCase):
    def test_port_and_game_toggle_need_restart(self):
        boot = _deep_merge(DEFAULTS, {"minecraft": {"enabled": False}})
        live = copy.deepcopy(boot)
        self.assertEqual(restart.restart_needed(boot, live, []), [])
        live["core"]["port"] = 3860
        live["minecraft"] = {"enabled": True}
        out = restart.restart_needed(boot, live, [SimpleNamespace(id="minecraft", name="Minecraft")])
        self.assertTrue(any("port" in x for x in out))
        self.assertIn("switching Minecraft on", out)

    def test_chat_platform_changes_never_need_restart(self):
        boot = copy.deepcopy(DEFAULTS)
        live = copy.deepcopy(boot)
        live["twitch"] = {"enabled": True, "channel": "x"}
        self.assertEqual(restart.restart_needed(boot, live, []), [])


def _client(state):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(admin_routes.create_admin_router(state))
    return TestClient(app)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.state = CoreState()
        self.state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
        self.state.boot_config = copy.deepcopy(self.state.config)
        self.saved = []

        def fake_save(cfg):
            self.saved.append(copy.deepcopy(cfg))
            return Path("config.yaml")

        for name, fn in (("save_config", fake_save),
                         ("load_config", lambda: copy.deepcopy(self.saved[-1] if self.saved else self.state.config))):
            p = mock.patch.object(admin_routes, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)
        self.client = _client(self.state)

    def test_status_reports_why(self):
        class Adapter:
            def status_info(self):
                return {"state": "retrying", "connected": False, "last_error": "Kick blocked the lookup (403)",
                        "last_message_at": None}

        class Core:
            def platform_info(self, name):
                return Adapter().status_info() if name == "kick" else {}

        self.state.config["kick"]["enabled"] = True
        self.state.adapters = {"kick": Adapter()}
        self.state.core = Core()
        res = self.client.get("/api/admin/status", headers=HEAD).json()
        kick = res["platforms"]["kick"]
        self.assertFalse(kick["running"])
        self.assertEqual(kick["state"], "retrying")
        self.assertIn("403", kick["last_error"])
        self.assertIn("server_time", res)
        self.assertEqual(res["restart_needed"], [])

    def test_save_says_what_needs_a_restart(self):
        form = copy.deepcopy(self.state.config)
        form["core"]["port"] = 3861
        res = self.client.put("/api/admin/config", json={"config": form}, headers=HEAD).json()
        self.assertIn("Restart Core to apply", res["message"])
        self.assertTrue(res["restart_needed"])
        form["core"]["port"] = 3850
        res = self.client.put("/api/admin/config", json={"config": form}, headers=HEAD).json()
        self.assertEqual(res["restart_needed"], [])
        self.assertNotIn("restart", res["message"].lower())

    def test_save_cleans_pasted_links(self):
        form = copy.deepcopy(self.state.config)
        form["kick"]["channel_slug"] = "https://kick.com/fridge"
        form["youtube"]["video_id"] = "https://youtu.be/dQw4w9WgXcQ"
        self.client.put("/api/admin/config", json={"config": form}, headers=HEAD)
        self.assertEqual(self.saved[-1]["kick"]["channel_slug"], "fridge")
        self.assertEqual(self.saved[-1]["youtube"]["video_id"], "dQw4w9WgXcQ")

    def test_youtube_video_box(self):
        calls = []

        async def apply_platforms(force=()):
            calls.append(tuple(force))
            return {"changed": ["youtube"], "running": ["youtube"]}

        self.state.apply_platforms = apply_platforms
        self.state.config["youtube"]["enabled"] = True
        res = self.client.post("/api/admin/platforms/youtube/video", headers=HEAD,
                               json={"video": "https://www.youtube.com/live/dQw4w9WgXcQ?si=1"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.saved[-1]["youtube"]["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(self.saved[-1]["points"]["admin_token"], TOKEN)  # rest of config kept
        self.assertEqual(calls, [("youtube",)])
        bad = self.client.post("/api/admin/platforms/youtube/video", headers=HEAD, json={"video": "my stream"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("YouTube video link", bad.json()["detail"])

    def test_restart_endpoint(self):
        with mock.patch.object(restart, "can_restart", return_value=(False, "")):
            res = self.client.post("/api/admin/restart", headers=HEAD)
        self.assertEqual(res.status_code, 409)
        self.assertIn("START Stream Core.bat", res.json()["detail"])
        asked = []
        self.state.request_restart = lambda: asked.append(1)
        with mock.patch.object(restart, "can_restart", return_value=(True, "loop")):
            res = self.client.post("/api/admin/restart", headers=HEAD)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(asked, [1])


class WizardTests(unittest.TestCase):
    def test_bad_port_asks_again(self):
        import wizard

        answers = iter(["abc", "99999", "4000"])
        with mock.patch("builtins.input", lambda _: next(answers)), mock.patch("builtins.print"):
            self.assertEqual(wizard._prompt_int("Admin port", 3977), 4000)


if __name__ == "__main__":
    unittest.main()
