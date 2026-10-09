"""Dashboard tidy: link people by name, undo Unflag, credits-off warning, filtered chat CSV,
chat overlay pictures default.

    python -m pytest tests/test_dashboard_tidy.py -q
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import admin_routes  # noqa: E402
from api.server import CoreState  # noqa: E402
from core.config import DEFAULTS, _deep_merge  # noqa: E402
from core.credits import CreditsEngine  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.red_flags import RedFlags  # noqa: E402
from core.store import Store  # noqa: E402

TOKEN = "tok-123456789abc"
HEAD = {"X-Admin-Token": TOKEN}


def chat(name: str, uid: str, platform: Platform, text: str = "hi") -> ChatEvent:
    return ChatEvent(platform=platform, user=ChatUser(platform=platform, id=uid, username=name,
                                                      display_name=name.title()), message=text)


class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = Store(self.root / "core.db", {"enabled": True, "per_message": 1, "cooldown_sec": 0},
                           {"enabled": True})
        self.state = CoreState()
        self.state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
        self.state.store = self.store
        self.state.red_flags = RedFlags(self.store, {})
        hidden = []

        async def hide(platform, uid, username, display):
            hidden.append((platform, uid, username))

        self.hidden = hidden
        self.state.red_flag_hide = hide
        app = FastAPI()
        app.include_router(admin_routes.create_admin_router(self.state))
        self.client = TestClient(app)

    def say(self, *events):
        async def go():
            return [await self.store.process_chat(e) for e in events]
        return asyncio.run(go())

    def test_link_by_name_merges_the_known_account(self):
        kick, yt = self.say(chat("bob", "k1", Platform.KICK), chat("bobyt", "UC1", Platform.YOUTUBE))
        res = self.client.post(f"/api/admin/users/{kick['user_id']}/link", headers=HEAD,
                               json={"platform": "youtube", "username": "BobYT"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["merged"])
        self.assertFalse(res.json()["waiting_for_chat"])
        self.assertIsNone(asyncio.run(self.store.get_user(yt["user_id"])))

    def test_link_by_name_before_they_chat(self):
        (kick,) = self.say(chat("bob", "k1", Platform.KICK))
        res = self.client.post(f"/api/admin/users/{kick['user_id']}/link", headers=HEAD,
                               json={"platform": "twitch", "username": "@Bob_TV"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["waiting_for_chat"])
        # their first Twitch line lands on the same person
        (tw,) = self.say(chat("bob_tv", "555", Platform.TWITCH))
        self.assertEqual(tw["user_id"], kick["user_id"])
        self.assertEqual(self.client.post(f"/api/admin/users/{kick['user_id']}/link", headers=HEAD,
                                          json={"platform": "twitch"}).status_code, 400)

    def test_unflag_can_be_undone(self):
        flagged = self.client.post("/api/admin/red-flags/flag", headers=HEAD,
                                   json={"name": "troll", "platform": "kick"}).json()["flagged"]
        self.assertEqual(len(flagged), 1)
        res = self.client.delete(f"/api/admin/red-flags/{flagged[0]['id']}", headers=HEAD).json()
        self.assertEqual(res["flagged"], [])
        self.assertEqual(res["removed"]["username"], "troll")
        self.hidden.clear()
        back = self.client.post("/api/admin/red-flags/restore", headers=HEAD,
                                json={"removed": res["removed"]}).json()
        self.assertEqual([f["username"] for f in back["flagged"]], ["troll"])
        self.assertEqual(back["flagged"][0]["platform"], "kick")
        self.assertEqual(len(self.hidden), 1)            # their lines leave the overlay again
        self.assertEqual(self.client.post("/api/admin/red-flags/restore", headers=HEAD,
                                          json={"removed": {}}).status_code, 400)

    def test_roll_credits_while_off_says_so(self):
        self.state.credits = CreditsEngine({"credits": {"enabled": False}}, self.root)
        res = self.client.post("/api/admin/credits/play", headers=HEAD, json={"playing": True})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(res.json()["credits_enabled"])
        self.assertIn("Credits are off", res.json()["warning"])
        self.state.credits = CreditsEngine({"credits": {"enabled": True}}, self.root)
        res = self.client.post("/api/admin/credits/play", headers=HEAD, json={"playing": True}).json()
        self.assertTrue(res["credits_enabled"])
        self.assertNotIn("warning", res)

    def test_chat_csv_follows_the_filters(self):
        self.say(chat("ann", "k1", Platform.KICK, "hello there"), chat("ben", "t1", Platform.TWITCH, "hello"),
                 chat("cat", "t2", Platform.TWITCH, "bye"))
        text = self.client.get("/api/admin/chat/export?platform=twitch&q=hello", headers=HEAD).text
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 2)                 # header + ben
        self.assertIn("ben", lines[1])


class ChatPicturesDefault(unittest.TestCase):
    def test_pictures_on_unless_saved_off(self):
        from core.chat_style import CHAT_STYLE

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertTrue(CHAT_STYLE.read_settings(d)["options"]["show_avatars"])
            CHAT_STYLE.write_settings(options={"show_avatars": False}, overlay_dir=d)
            self.assertFalse(CHAT_STYLE.read_settings(d)["options"]["show_avatars"])


if __name__ == "__main__":
    unittest.main()
