"""Stream events feed (core/activity.py) behind the Live page's window, and its admin route."""

import logging
import unittest

from core.activity import ActivityLog, ActivityLogHandler, MAX_ITEMS
from core.event_bus import EventBus


class ActivityLogTest(unittest.TestCase):
    def test_ids_rise_and_since_returns_only_newer(self):
        log = ActivityLog()
        log.add("alert", "A followed")
        log.add("command", "!points by B")
        first = log.since(0)
        self.assertEqual([i["text"] for i in first["items"]], ["A followed", "!points by B"])
        self.assertEqual(first["last"], 2)
        log.add("redeem", "C spent 50 points on Confetti")
        later = log.since(first["last"])
        self.assertEqual([i["kind"] for i in later["items"]], ["redeem"])

    def test_unknown_kind_becomes_game_and_empty_text_is_skipped(self):
        log = ActivityLog()
        self.assertIsNone(log.add("alert", "   "))
        self.assertEqual(log.add("weird", "x")["kind"], "game")

    def test_repeated_error_counts_instead_of_flooding(self):
        log = ActivityLog()
        log.add("error", "kick: connect failed", ts=100)
        again = log.add("error", "kick: connect failed", ts=110)
        self.assertEqual(again["count"], 2)
        rows = log.since(0)["items"]
        self.assertEqual(len(rows), 1)
        # a poll that already saw id 1 still gets the bumped line (it has a new id)
        self.assertEqual(log.since(1)["items"][0]["count"], 2)

    def test_old_lines_fall_off(self):
        log = ActivityLog()
        for n in range(MAX_ITEMS + 20):
            log.add("command", f"!c{n}")
        rows = log.since(0, limit=MAX_ITEMS)["items"]
        self.assertEqual(len(rows), MAX_ITEMS)
        self.assertEqual(rows[-1]["text"], f"!c{MAX_ITEMS + 19}")

    def test_log_handler_copies_errors_and_platform_warnings_only(self):
        log = ActivityLog()
        h = ActivityLogHandler(log)
        logger = logging.getLogger("test_activity_tmp")
        kick = logging.getLogger("adapters.kick")
        avatars = logging.getLogger("adapters.twitch_avatars")
        for lg in (logger, kick, avatars):
            lg.addHandler(h)
            lg.propagate = False
        try:
            logger.warning("ordinary warning")
            logger.error("something broke")
            kick.warning("chatroom closed")
            avatars.warning("no picture for x")
        finally:
            for lg in (logger, kick, avatars):
                lg.removeHandler(h)
                lg.propagate = True
        texts = [i["text"] for i in log.since(0)["items"]]
        self.assertEqual(texts, ["test_activity_tmp: something broke", "kick: chatroom closed"])

    def test_bus_note_is_safe_without_a_log(self):
        bus = EventBus()
        bus.note("alert", "nobody listening")   # no error before main.py sets bus.activity
        bus.activity = ActivityLog()
        bus.note("alert", "now saved", "twitch")
        item = bus.activity.since(0)["items"][0]
        self.assertEqual((item["text"], item["platform"]), ("now saved", "twitch"))


class ActivityRouteTest(unittest.TestCase):
    def test_route_needs_token_and_returns_items(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.admin_routes import create_admin_router
        from api.server import CoreState

        state = CoreState()
        state.config = {"points": {"admin_token": "route-test-token-1234"}}
        state.activity = ActivityLog()
        state.activity.add("alert", "D raided with 12")
        app = FastAPI()
        app.include_router(create_admin_router(state))
        client = TestClient(app)
        self.assertEqual(client.get("/api/admin/activity").status_code, 401)
        r = client.get("/api/admin/activity?after=0", headers={"X-Admin-Token": "route-test-token-1234"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["items"][0]["text"], "D raided with 12")


if __name__ == "__main__":
    unittest.main()
