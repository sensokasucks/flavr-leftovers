"""Highlighted message: core/highlights.py, api/highlight_routes.py and the end credits'
"Featured" section (core/credits.py feature, core/cast.py decorate).

    python -m pytest tests/test_highlights.py -q
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.highlight_routes import create_highlight_router  # noqa: E402
from api.server import CoreState  # noqa: E402
from core.config import DEFAULTS, _deep_merge  # noqa: E402
from core.credits import CreditsEngine  # noqa: E402
from core.highlights import QUEUE_MAX, HighlightBoard, clean_item, quote_of  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.red_flags import RedFlags  # noqa: E402
from core.store import Store  # noqa: E402

TOKEN = "tok-123456789abc"
HEAD = {"X-Admin-Token": TOKEN}


def line(mid: str, name: str = "moth", text: str = "hello there", platform: str = "twitch", **extra) -> dict:
    """A chat payload "data" dict like main.py _on_chat sends."""
    return {"platform": platform, "message_id": mid, "message": text, "emotes": extra.pop("emotes", []),
            "user": {"id": "u-" + name, "username": name, "display_name": name.title(), "color": "#bf94ff"},
            **extra}


class BoardTests(unittest.TestCase):
    def test_push_shows_then_queues_and_next_moves_on(self):
        b = HighlightBoard()
        first = b.push(line("1"))
        second = b.push(line("2", "otter"))
        self.assertIs(b.current, first)
        self.assertEqual([q["id"] for q in b.queue], [second["id"]])
        b.next()
        self.assertEqual(b.current["id"], second["id"])
        b.next()
        self.assertIsNone(b.current)

    def test_clear_empties_screen_and_queue(self):
        b = HighlightBoard()
        b.push(line("1"))
        b.push(line("2"))
        b.clear()
        self.assertIsNone(b.current)
        self.assertEqual(b.queue, [])

    def test_queue_is_capped(self):
        b = HighlightBoard()
        for i in range(QUEUE_MAX + 5):
            b.push(line(str(i)))
        self.assertEqual(len(b.queue), QUEUE_MAX)

    def test_clean_item_drops_bad_links_and_unknown_fields(self):
        item = clean_item({
            "platform": "twitch", "message": "hi <b>", "evil": "x",
            "emotes": [{"start": 0, "end": 1, "url": "javascript:alert(1)"},
                       {"start": 0, "end": 1, "url": "https://cdn.example/e.png", "name": "hi"}],
            "user": {"display_name": "A", "profile_image_url": "data:text/html,x", "avatar_local": "/avatars/../x",
                     "color": "red;background:url(x)"},
        })
        self.assertNotIn("evil", item)
        self.assertEqual(len(item["emotes"]), 1)
        self.assertEqual(item["user"]["profile_image_url"], "")
        self.assertEqual(item["user"]["avatar_local"], "")
        self.assertEqual(item["user"]["color"], "")
        self.assertEqual(clean_item({"platform": "myspace"})["platform"], "")

    def test_empty_message_refused(self):
        with self.assertRaises(ValueError):
            HighlightBoard().push(line("1", text="   "))

    def test_recent_since_and_restart_reset(self):
        b = HighlightBoard()
        for i in range(5):
            b.note_chat(line(str(i)))
        first = b.recent_since(0)
        self.assertEqual(len(first["items"]), 5)
        self.assertTrue(first["reset"])
        b.note_chat(line("5"))
        nxt = b.recent_since(first["last"])
        self.assertEqual([r["message_id"] for r in nxt["items"]], ["5"])
        self.assertFalse(nxt["reset"])
        # a window that saw a later seq (Core restarted) starts over
        self.assertTrue(b.recent_since(999)["reset"])

    def test_core_echo_not_kept(self):
        b = HighlightBoard()
        b.note_chat(line("1", from_core=True))
        self.assertEqual(len(b.recent), 0)

    def test_forget_user_takes_them_off(self):
        b = HighlightBoard()
        b.note_chat(line("1", "troll"))
        b.push(line("1", "troll"))
        b.push(line("2", "otter"))
        b.forget_user("twitch", "u-troll", "troll")
        self.assertEqual((b.current or {}).get("message_id"), "2")
        self.assertTrue(b.recent[0]["flagged"])

    def test_auto_hide_after_hold(self):
        b = HighlightBoard({"highlight": {"hold_sec": 1}})
        sent = []

        async def on_change(state):
            sent.append(state)

        b.on_change = on_change
        b.push(line("1"))
        b.current["shown_at"] = time.time() - 5
        stop = asyncio.Event()

        async def go():
            task = asyncio.create_task(b.run(stop))
            await asyncio.sleep(0.7)
            stop.set()
            await task

        asyncio.run(go())
        self.assertIsNone(b.current)
        self.assertTrue(sent)

    def test_featured_hook_gets_quote(self):
        b = HighlightBoard()
        got = []
        b.on_featured = lambda *a: got.append(a)
        b.push(line("1", text="what a play [emote:1:wow]"))
        self.assertEqual(got, [("twitch", "moth", "Moth", '"what a play"')])
        self.assertEqual(quote_of({"message": "x" * 100})[-2:], '…"')


class FeaturedCreditsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.eng = CreditsEngine({"credits": {"enabled": True}}, self.root)
        for name in ("moth", "otter", "goose"):
            self.eng.ingest(ChatEvent(platform=Platform.TWITCH, message="hi",
                                      user=ChatUser(platform=Platform.TWITCH, id=name, username=name, display_name=name.title())))

    def test_feature_marks_snapshot_and_survives_reload(self):
        self.assertTrue(self.eng.feature("twitch", "otter", "Otter", '"nice"'))
        self.assertFalse(self.eng.feature("twitch", "otter", "Otter", '"again"'))   # first quote kept
        snap = self.eng.snapshot()
        otter = next(c for c in snap["chatters"] if c["username"] == "otter")
        self.assertTrue(otter["featured"])
        self.assertEqual(otter["featured_quote"], '"nice"')
        self.eng.save()
        again = CreditsEngine({"credits": {"enabled": True}}, self.root)
        self.assertIn("twitch:otter", again.featured)

    def test_movie_style_puts_featured_department_first(self):
        self.eng.cast.set_style("movie")
        self.eng.feature("twitch", "goose", "Goose", '"honk"')
        cast = self.eng.snapshot()["cast"]
        first = cast["departments"][0]
        self.assertEqual(first["id"], "featured")
        self.assertEqual(first["title"], "Featured")
        self.assertEqual([r["username"] for r in first["rows"]], ["goose"])
        self.assertEqual(first["rows"][0]["job"], '"honk"')
        # nobody shows twice
        names = [r["username"] for d in cast["departments"] for r in d["rows"]]
        self.assertEqual(len(names), len(set(names)))

    def test_reset_and_forget_drop_featured(self):
        self.eng.feature("twitch", "moth", "Moth", "")
        self.eng.forget("twitch", "moth")
        self.assertNotIn("twitch:moth", self.eng.featured)
        self.eng.feature("twitch", "otter", "Otter", "")
        self.eng.reset()
        self.assertEqual(self.eng.featured, {})


class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        store = Store(self.root / "core.db", {"enabled": True}, {"enabled": True})
        self.state = CoreState()
        self.state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
        self.state.red_flags = RedFlags(store, {})
        self.board = HighlightBoard(self.state.config)
        self.state.highlights = self.board
        app = FastAPI()
        app.include_router(create_highlight_router(self.state, self.root))
        self.client = TestClient(app)
        self.saved = []
        import api.highlight_routes as hr
        orig = hr.save_config
        hr.save_config = lambda cfg: self.saved.append(json.loads(json.dumps(cfg)))
        self.addCleanup(setattr, hr, "save_config", orig)

    def test_needs_token(self):
        self.assertEqual(self.client.get("/api/admin/highlight").status_code, 401)

    def test_push_recent_line_keeps_emotes(self):
        self.board.note_chat(line("m1", emotes=[{"start": 0, "end": 4, "url": "https://e/x.png", "name": "hello"}]))
        r = self.client.post("/api/admin/highlight", headers=HEAD, json={"platform": "twitch", "message_id": "m1"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["on_screen"])
        self.assertEqual(len(self.board.current["emotes"]), 1)

    def test_old_saved_line_uses_fallback_text(self):
        r = self.client.post("/api/admin/highlight", headers=HEAD, json={
            "platform": "kick", "message_id": "gone", "message": "from the log",
            "user": {"username": "old", "display_name": "Old"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.board.current["message"], "from the log")

    def test_unknown_without_text_is_404(self):
        r = self.client.post("/api/admin/highlight", headers=HEAD, json={"platform": "kick", "message_id": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_red_flagged_refused(self):
        self.board.note_chat(line("m2", "troll"), flagged=True)
        r = self.client.post("/api/admin/highlight", headers=HEAD, json={"platform": "twitch", "message_id": "m2"})
        self.assertEqual(r.status_code, 409)
        self.assertIsNone(self.board.current)

    def test_next_clear_remove_and_settings(self):
        for i in range(3):
            self.board.note_chat(line(f"q{i}"))
            self.client.post("/api/admin/highlight", headers=HEAD, json={"platform": "twitch", "message_id": f"q{i}"})
        st = self.client.get("/api/admin/highlight", headers=HEAD).json()
        self.assertEqual(st["queue_len"], 2)
        rid = st["queue"][0]["id"]
        self.assertEqual(self.client.post("/api/admin/highlight/remove", headers=HEAD, json={"id": rid}).json()["queue_len"], 1)
        self.client.post("/api/admin/highlight/next", headers=HEAD)
        self.assertEqual(self.board.current["message_id"], "q2")
        self.client.post("/api/admin/highlight/clear", headers=HEAD)
        self.assertIsNone(self.board.current)
        r = self.client.put("/api/admin/highlight/settings", headers=HEAD, json={"hold_sec": 9999, "show_avatar": False})
        self.assertEqual(r.json()["settings"]["hold_sec"], 600)
        self.assertEqual(self.saved[-1]["highlight"]["hold_sec"], 600)
        self.assertFalse(self.saved[-1]["highlight"]["show_avatar"])
        # other blocks kept
        self.assertIn("points", self.saved[-1])

    def test_recent_route(self):
        self.board.note_chat(line("r1"))
        data = self.client.get("/api/admin/highlight/recent?after=0", headers=HEAD).json()
        self.assertEqual(data["items"][0]["message_id"], "r1")


if __name__ == "__main__":
    unittest.main()
