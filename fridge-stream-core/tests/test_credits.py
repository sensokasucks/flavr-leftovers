"""Credits look sanitizer, engine config round-trip, CSV and movie extras."""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.cast import CastBoard  # noqa: E402
from core.credits import CreditsEngine  # noqa: E402
from core.credits_theme import LOOK_DEFAULTS, MOTION_IDS, merge_look, sanitize_look  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402


def _event(name: str, msg: str = "hi", **kw) -> ChatEvent:
    return ChatEvent(
        platform=Platform.TWITCH,
        user=ChatUser(platform=Platform.TWITCH, id=name, username=name, display_name=name.title(), **kw),
        message=msg,
    )


class LookTests(unittest.TestCase):
    def test_every_editor_motion_allowed(self):
        for mid in ("crawl", "crawl-down", "starwars", "cards", "fade", "slides", "ticker", "typewriter", "matrix"):
            self.assertIn(mid, MOTION_IDS)
            self.assertEqual(sanitize_look({"motion": mid})["motion"], mid)

    def test_motion_aliases(self):
        self.assertEqual(sanitize_look({"motion": "teletype"})["motion"], "typewriter")
        self.assertEqual(sanitize_look({"motion": "TTY"})["motion"], "typewriter")
        self.assertEqual(sanitize_look({"motion": "nametape"})["motion"], "ticker")
        self.assertEqual(sanitize_look({"motion": "simple"})["motion"], "crawl")

    def test_standalone_keys_become_core_keys(self):
        out = sanitize_look({"sw_tilt_deg": 32, "sw_perspective_px": 320, "page_hold_sec": 2.4, "page_fade_sec": 0.65})
        self.assertEqual(out["tilt_deg"], 32)
        self.assertEqual(out["perspective_px"], 320)
        self.assertEqual(out["page_duration_sec"], 2.4)
        self.assertEqual(out["page_transition_ms"], 650)
        for old in ("sw_tilt_deg", "sw_perspective_px", "page_hold_sec", "page_fade_sec"):
            self.assertNotIn(old, out)

    def test_core_key_wins_over_alias(self):
        out = sanitize_look({"tilt_deg": 40, "sw_tilt_deg": 30})
        self.assertEqual(out["tilt_deg"], 40)

    def test_clamps_enums_bools(self):
        out = sanitize_look({
            "matrix_density": 9, "columns": "7", "typewriter_cps": -3, "opacity": "abc",
            "typewriter_unit": "word", "name_enter": "slide", "glow": "false", "letterbox": 1,
            "mode": "clear",
        })
        self.assertEqual(out["matrix_density"], 2.2)
        self.assertEqual(out["columns"], 4)
        self.assertEqual(out["typewriter_cps"], 4)
        self.assertEqual(out["opacity"], 1)
        self.assertEqual(out["typewriter_unit"], "line")
        self.assertEqual(out["name_enter"], "slide")
        self.assertIs(out["glow"], False)
        self.assertIs(out["letterbox"], True)
        self.assertEqual(out["mode"], "clear")

    def test_patch_only_and_unknown_keys_pass(self):
        out = sanitize_look({"future_knob": "x", "title": "Hi"})
        self.assertEqual(out, {"future_knob": "x", "title": "Hi"})
        merged = merge_look({"motion": "crawl", "title_color": "#fff"}, {"motion": "matrix"})
        self.assertEqual(merged["motion"], "matrix")
        self.assertEqual(merged["title_color"], "#fff")

    def test_defaults_cover_new_keys(self):
        for key in ("typewriter_unit", "typewriter_cps", "matrix_density", "letterbox", "grain",
                    "clear_when_done", "title_own_page"):
            self.assertIn(key, LOOK_DEFAULTS)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_configure_keeps_new_and_unknown_look_keys(self):
        eng = CreditsEngine({"credits": {
            "enabled": True, "motion": "teletype", "typewriter_cps": 40, "matrix_density": 1.5,
            "letterbox": True, "some_new_key": 3, "page_hold_sec": 2,
        }}, self.root)
        self.assertEqual(eng.theme["motion"], "typewriter")
        self.assertEqual(eng.theme["typewriter_cps"], 40)
        self.assertEqual(eng.theme["matrix_density"], 1.5)
        self.assertTrue(eng.theme["letterbox"])
        self.assertEqual(eng.theme["some_new_key"], 3)
        self.assertEqual(eng.theme["page_duration_sec"], 2)
        for engine_key in ("enabled", "ignore_usernames", "min_message_length"):
            self.assertNotIn(engine_key, eng.theme)

    def test_apply_theme_sanitizes(self):
        eng = CreditsEngine({"credits": {"enabled": True}}, self.root)
        eng.apply_theme({"motion": "matrix", "matrix_density": 50, "persist": False})
        self.assertEqual(eng.theme["motion"], "matrix")
        self.assertEqual(eng.theme["matrix_density"], 2.2)
        self.assertNotIn("persist", eng.theme)

    def test_clear_mode(self):
        eng = CreditsEngine({"credits": {"enabled": True, "mode": "clear"}}, self.root)
        self.assertEqual(eng.play["mode"], "clear")
        eng.set_play({"mode": "loop"})
        self.assertEqual(eng.play["mode"], "loop")
        eng.set_play({"mode": "clear", "restart": True})
        self.assertEqual(eng.public_play()["mode"], "clear")
        self.assertEqual(eng.public_play()["generation"], 1)

    def test_filters(self):
        eng = CreditsEngine({
            "twitch": {"channel": "mychan"},
            "credits": {"enabled": True, "min_message_length": 3, "ignore_usernames": ["lurkbot"]},
        }, self.root)
        self.assertIsNone(eng.ingest(_event("mychan", "hello")))
        self.assertIsNone(eng.ingest(_event("lurkbot", "hello")))
        self.assertIsNone(eng.ingest(_event("bob", "hi")))
        self.assertIsNotNone(eng.ingest(_event("bob", "hello")))
        self.assertEqual(len(eng.chatters), 1)

    def test_paid_flag_and_csv(self):
        eng = CreditsEngine({"credits": {"enabled": True}}, self.root)
        ev = _event("alice", "cheer100", is_mod=True)
        ev.is_paid = True
        eng.ingest(ev)
        eng.ingest(_event("alice", "again"))
        self.assertTrue(eng.chatters["twitch:alice"].is_paid)
        rows = list(csv.reader(io.StringIO(eng.roster_csv())))
        self.assertEqual(rows[0], ["platform", "username", "display_name", "messages", "first_seen", "mod"])
        self.assertEqual(rows[1][:4], ["twitch", "alice", "Alice", "2"])
        self.assertEqual(rows[1][5], "1")


class MovieExtrasTests(unittest.TestCase):
    def test_style_extras_reach_the_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = CastBoard(Path(tmp), allow_alert_groups=True)
            style = json.loads((ROOT / "config" / "cast" / "movie.json").read_text(encoding="utf-8"))
            style.update(
                id="premiere",
                cards=["A Chat Production", {"type": "mpaa", "line": "Rated C for {count} chatters", "hold_sec": 2}],
                stinger={"kicker": "After the credits", "line": "Same time tomorrow"},
                starring=["Starring"],
                thanks=["Snacks: Mom", {"job": "Moral support", "display_name": "The Cat"}],
                legal=["No {count} chatters were harmed"],
                end_hold_sec=3,
                look={"letterbox": True},
            )
            board.save_style(style)
            board.set_style("premiere")
            snap = board.decorate({"chatters": [
                {"platform": "kick", "username": f"u{i}", "display_name": f"U{i}", "messages": i}
                for i in range(4)
            ]}, started_at=1)
            cast = snap["cast"]
            self.assertEqual([c["line"] for c in cast["cards"]], ["A Chat Production", "Rated C for 4 chatters"])
            self.assertEqual(cast["stinger"]["line"], "Same time tomorrow")
            self.assertEqual(cast["starring"][0]["billing"], "Starring")
            self.assertEqual(cast["starring"][0]["display_name"], "U3")
            self.assertEqual(cast["thanks"][0], {"job": "Snacks", "display_name": "Mom"})
            self.assertEqual(cast["legal"], ["No 4 chatters were harmed"])
            self.assertEqual(cast["end_hold_sec"], 3.0)
            self.assertEqual(cast["look"], {"letterbox": True})

    def test_plain_movie_style_has_no_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = CastBoard(Path(tmp), allow_alert_groups=True)
            board.set_style("movie")
            snap = board.decorate({"chatters": [{"platform": "kick", "username": "a", "display_name": "A"}]}, 1)
            for key in ("cards", "stinger", "starring", "thanks", "legal", "end_hold_sec", "look"):
                self.assertNotIn(key, snap["cast"])


class OverlayFilesTests(unittest.TestCase):
    def test_overlay_and_editor_know_every_motion(self):
        js = (ROOT / "overlay" / "credits.js").read_text(encoding="utf-8")
        editor = (ROOT / "overlay" / "credits-editor.js").read_text(encoding="utf-8")
        html = (ROOT / "overlay" / "credits.html").read_text(encoding="utf-8")
        for mid in MOTION_IDS:
            self.assertIn(f'id: "{mid}"', editor)
        for needle in ("startMatrix", "tickTypewriter", "wantsClear", "/api/credits/theme", "easing", "loop_transition"):
            self.assertIn(needle, js)
        for el in ("sw-world", "sw-track", "matrix", "pages", "ticker", "cards", "stinger", "fade-top", "lb-top", "grain"):
            self.assertIn(f'id="{el}"', html)


if __name__ == "__main__":
    unittest.main()
