"""First-run / GitHub-clone sanity checks. Run from fridge-stream-core:

    python -m unittest tests.test_boot -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DEFAULTS, load_config, sanitize_yaml_text
from core.credits import CreditsEngine
from core.models import ChatEvent, ChatUser, Platform
from core.permissions import PermissionManager
from core.store import Store
from core.alerts import (
    KINDS,
    build_alert,
    css_classes_for,
    kind_catalog,
    read_alert_settings,
    write_alert_settings,
    write_custom_css,
)


GITHUB_TABBED_EXAMPLE = """\
core:
  host: "127.0.0.1"
  port: 3850
metrics:
  maxCommandsForFull: 10
	overlay:
  show_inventory_seconds: 12
points:
  enabled: true
  admin_token: "change-me"
"""


class SanitizeYamlTests(unittest.TestCase):
    def test_example_file_has_no_tabs(self):
        text = (ROOT / "config" / "config.example.yaml").read_bytes()
        self.assertNotIn(9, text, "config.example.yaml must not contain tab bytes")

    def test_tab_before_overlay_unindents(self):
        cleaned, changed = sanitize_yaml_text(GITHUB_TABBED_EXAMPLE)
        self.assertTrue(changed)
        self.assertNotIn("\t", cleaned)
        self.assertIn("\noverlay:\n", cleaned)
        from core.config import _parse_yaml

        parsed = _parse_yaml(cleaned, "memory")
        self.assertEqual(parsed["overlay"]["show_inventory_seconds"], 12)
        self.assertEqual(parsed["metrics"]["maxCommandsForFull"], 10)

    def test_nested_tabs_become_spaces(self):
        raw = "kick:\n\tenabled: false\n"
        cleaned, changed = sanitize_yaml_text(raw)
        self.assertTrue(changed)
        self.assertEqual(cleaned, "kick:\n  enabled: false\n")

    def test_bom_stripped(self):
        cleaned, changed = sanitize_yaml_text("\ufeffcore:\n  port: 3850\n")
        self.assertTrue(changed)
        self.assertFalse(cleaned.startswith("\ufeff"))


class SeedAndLoadTests(unittest.TestCase):
    def test_example_loads(self):
        cfg = load_config(ROOT / "config" / "config.example.yaml")
        self.assertFalse(cfg["kick"]["enabled"])
        self.assertFalse(cfg["twitch"]["enabled"])
        self.assertFalse(cfg["youtube"]["enabled"])
        self.assertFalse(cfg["minecraft"]["enabled"])
        self.assertFalse(cfg["chat_log"]["enabled"])
        self.assertFalse(cfg["points"]["enabled"])
        self.assertFalse(cfg["credits"]["enabled"])
        self.assertEqual(cfg["overlay"]["show_inventory_seconds"], 12)
        self.assertEqual(cfg["overlay"]["alert_duration_ms"], 6000)
        self.assertEqual(cfg["core"]["port"], DEFAULTS["core"]["port"])


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_message_from_same_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "t.db", {"enabled": True, "per_message": 1, "cooldown_sec": 0})
            event = ChatEvent(
                platform=Platform.KICK,
                user=ChatUser(platform=Platform.KICK, id="1", username="bob"),
                message="hi",
            )
            first = await store.process_chat(event)
            second = await store.process_chat(event)
            self.assertEqual(first["user_id"], second["user_id"])
            self.assertGreaterEqual(second["balance"] or 0, 1)

    async def test_chat_log_off_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "t.db", {"enabled": False})
            self.assertFalse(store.log_chat)
            event = ChatEvent(
                platform=Platform.KICK,
                user=ChatUser(platform=Platform.KICK, id="2", username="alice"),
                message="hello",
            )
            await store.process_chat(event)

            def count():
                with store._connect() as conn:
                    return int(conn.execute("SELECT COUNT(*) AS n FROM chat_messages").fetchone()["n"])

            self.assertEqual(await store._run(count), 0)

    async def test_chat_log_on_writes_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(
                Path(tmp) / "t.db",
                {"enabled": False},
                {"enabled": True},
            )
            event = ChatEvent(
                platform=Platform.KICK,
                user=ChatUser(platform=Platform.KICK, id="3", username="carol"),
                message="logged",
            )
            await store.process_chat(event)

            def count():
                with store._connect() as conn:
                    return int(conn.execute("SELECT COUNT(*) AS n FROM chat_messages").fetchone()["n"])

            self.assertEqual(await store._run(count), 1)


class PermissionTests(unittest.TestCase):
    def test_string_admin_is_accepted(self):
        pm = PermissionManager({"permissions": {"admin": "Sensoka", "mod": []}})
        self.assertIn("sensoka", pm.admins)


class AlertBuilderTests(unittest.TestCase):
    def test_catalog_covers_all_kinds(self):
        keys = {row["kind"] for row in kind_catalog()}
        self.assertEqual(keys, set(KINDS))

    def test_follow_headline(self):
        payload = build_alert(kind="follow", username="Ada", platform="kick", is_test=True)
        self.assertEqual(payload["kind"], "follow")
        self.assertEqual(payload["headline"], "Ada followed!")
        self.assertTrue(payload["is_test"])
        self.assertEqual(payload["duration_ms"], 6000)
        self.assertIn("id", payload)

    def test_superchat_formats_amount(self):
        payload = build_alert(
            kind="superchat",
            username="bob",
            display_name="Bob",
            platform="youtube",
            amount=4.99,
            currency="USD",
            message="hi",
        )
        self.assertEqual(payload["amount_fmt"], "4.99 USD")
        self.assertIn("4.99 USD", payload["headline"])
        self.assertEqual(payload["message"], "hi")
        self.assertEqual(payload["platform"], "youtube")

    def test_bits_defaults_and_unknown_kind(self):
        payload = build_alert(kind="bits", username="cheer")
        self.assertEqual(payload["currency"], "bits")
        self.assertIn("500 bits", payload["headline"])
        with self.assertRaises(ValueError):
            build_alert(kind="not-a-kind")

    def test_duration_clamped(self):
        lo = build_alert(kind="host", duration_ms=100)
        hi = build_alert(kind="host", duration_ms=99999)
        self.assertEqual(lo["duration_ms"], 1500)
        self.assertEqual(hi["duration_ms"], 30000)

    def test_css_classes_match_streamlabs(self):
        payload = build_alert(kind="follow", username="Ada")
        self.assertIn("follower-alert", payload["css_classes"])
        self.assertIn("cheer-alert", css_classes_for("bits"))
        self.assertIn("superchat-alert", css_classes_for("superchat"))

    def test_custom_css_roundtrip_and_reject_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_custom_css("/* hi */\n.name { color: red; }\n", overlay_dir=root)
            settings = read_alert_settings(overlay_dir=root)
            self.assertEqual(settings["skin"], "classic")
            self.assertGreater(settings["css_version"], 0)
            css_file = root / "alerts-custom.css"
            self.assertIn(".name", css_file.read_text(encoding="utf-8"))
            write_alert_settings(skin="custom", overlay_dir=root)
            self.assertEqual(read_alert_settings(overlay_dir=root)["skin"], "custom")
            with self.assertRaises(ValueError):
                write_custom_css("<script>alert(1)</script>", overlay_dir=root)

    def test_overlay_html_has_streamlabs_hooks(self):
        html = (ROOT / "overlay" / "alerts.html").read_text(encoding="utf-8")
        for needle in (
            'id="alert-box"',
            'id="alert-message"',
            'id="alert-user-message"',
            'id="alert-image"',
            "widget-AlertBox",
            "alerts-custom.css",
        ):
            self.assertIn(needle, html)


class CreditsEngineTests(unittest.TestCase):
    def test_disabled_does_not_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eng = CreditsEngine({"credits": {"enabled": False}}, root)
            event = ChatEvent(
                platform=Platform.KICK,
                user=ChatUser(platform=Platform.KICK, id="1", username="bob"),
                message="hi",
            )
            self.assertIsNone(eng.ingest(event))
            self.assertEqual(len(eng.chatters), 0)
            self.assertIsNotNone(eng.ingest(event, force=True))
            self.assertEqual(len(eng.chatters), 1)
            self.assertIsNone(eng.ingest(event, force=True))
            self.assertEqual(eng.chatters["kick:bob"].messages, 2)

    def test_ignore_bots(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = CreditsEngine({"credits": {"enabled": True}}, Path(tmp))
            event = ChatEvent(
                platform=Platform.TWITCH,
                user=ChatUser(platform=Platform.TWITCH, id="n", username="nightbot"),
                message="hi",
            )
            self.assertIsNone(eng.ingest(event))

    def test_overlay_file_exists(self):
        html = (ROOT / "overlay" / "credits.html").read_text(encoding="utf-8")
        self.assertIn("requestAnimationFrame", html)
        self.assertIn("/api/credits/theme", html)
        self.assertIn("card-kicker", html)
        self.assertIn("letterbox", html)


class CastBoardTests(unittest.TestCase):
    def test_job_cap_and_quotes(self):
        from core.cast import clamp_job, parse_quoted_args
        from core.models import ChatUser, Platform, strip_handle
        self.assertEqual(len(clamp_job("x" * 80)), 50)
        parts = parse_quoted_args('!credit "bob" clear')
        self.assertIn("bob", parts)
        self.assertIn("clear", parts)
        self.assertEqual(strip_handle("@Lo-FiLynx"), "Lo-FiLynx")
        user = ChatUser(platform=Platform.YOUTUBE, id="1", username="@FooBar", display_name="@FooBar")
        self.assertEqual(user.username, "foobar")
        self.assertEqual(user.display_name, "FooBar")

    def test_pin_survives_decorate(self):
        from core.cast import CastBoard
        with tempfile.TemporaryDirectory() as tmp:
            board = CastBoard(Path(tmp), allow_alert_groups=True)
            board.set_style("movie")
            board.pin("kick", "bob", "Gaffer")
            snap = board.decorate({
                "chatters": [{
                    "platform": "kick", "username": "bob", "display_name": "Bob",
                    "messages": 3, "is_mod": True, "is_subscriber": False, "is_vip": False,
                }]
            }, started_at=1)
            self.assertEqual(snap["style"], "movie")
            self.assertEqual(snap["chatters"][0].get("job"), "Gaffer")
            self.assertTrue(snap["cast"]["cards"])
            self.assertTrue(snap["cast"]["legal"])

    def test_core_only_raid_group(self):
        from core.cast import CastBoard
        with tempfile.TemporaryDirectory() as tmp:
            board = CastBoard(Path(tmp), allow_alert_groups=False)
            board.set_style("movie")
            board.tag_alert("raid", "kick", "raid")
            snap = board.decorate({
                "by_platform": {"kick": 1},
                "chatters": [{
                    "platform": "kick", "username": "raid", "display_name": "Raid",
                    "messages": 1, "is_mod": False, "is_subscriber": False, "is_vip": False,
                }],
            }, started_at=1)
            sources = [g["source"] for g in (snap["cast"] or {}).get("groups") or []]
            self.assertNotIn("raiders", sources)

    def test_raid_auto_joins_and_legal_placeholders(self):
        from core.credits import CreditsEngine
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config" / "cast").mkdir(parents=True)
            eng = CreditsEngine({"credits": {"enabled": True, "style_id": "movie"}}, root)
            added = eng.ingest_alert("raid", "kick", "raiderbob", extra={"viewers": 42})
            self.assertIsNotNone(added)
            self.assertEqual(added.alert_note, "with 42")
            snap = eng.snapshot()
            sources = [g["source"] for g in (snap["cast"] or {}).get("groups") or []]
            self.assertIn("raiders", sources)
            legal = " ".join((snap["cast"] or {}).get("legal") or [])
            self.assertIn("speaking roles", legal)

    def test_credits_chat_roll_is_gated(self):
        from core.credits import CreditsEngine
        with tempfile.TemporaryDirectory() as tmp:
            eng = CreditsEngine({"credits": {"enabled": True}}, Path(tmp))
            reply, play, need_mod = eng.handle_credits_chat(
                "!credits", username="bob", platform="kick"
            )
            self.assertIn("roster", reply.lower())
            self.assertFalse(need_mod)
            reply, play, need_mod = eng.handle_credits_chat(
                "!credits roll", username="bob", platform="kick"
            )
            self.assertTrue(need_mod)
            self.assertTrue(play and play.get("restart"))
            reply, play, need_mod = eng.handle_credits_chat(
                "!credits clear", username="bob", platform="kick"
            )
            self.assertTrue(need_mod)
            self.assertEqual(play.get("mode"), "clear")
            eng.set_play(play)
            self.assertEqual(eng.play["mode"], "clear")
            reply, play, need_mod = eng.handle_credits_chat(
                "!rollcredits", username="bob", platform="kick"
            )
            self.assertTrue(need_mod)
            me, _, _ = eng.handle_credits_chat("!credits me", username="nobody", platform="kick")
            self.assertIn("not on the credits", me.lower())


if __name__ == "__main__":
    unittest.main()
