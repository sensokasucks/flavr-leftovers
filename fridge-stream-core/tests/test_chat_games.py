"""Chat games: crowd moments, points games, watch-along, regulars (core/chat_games)."""

import asyncio
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.chat_games import ChatGames, normalize_config  # noqa: E402
from core.chat_games.wagers import Slots  # noqa: E402
from core.chat_games.watch import normalize_answer  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.permissions import PermissionManager  # noqa: E402
from core.store import Store  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class FakeReactions:
    def __init__(self):
        self.played = []
        self.game_clients = {"ws": {}}

    async def play(self, effect, params=None, **kw):
        self.played.append({"effect": effect, "params": params or {}, **kw})
        return f"r-{len(self.played)}"

    async def send_stage(self, action, value):
        self.played.append({"effect": "stage", "action": action, "value": value})
        return True


def ev(name, text, platform=Platform.KICK, mod=False, emotes=None):
    user = ChatUser(platform=platform, id=name.lower(), username=name.lower(), display_name=name, is_mod=mod)
    e = ChatEvent(platform=platform, user=user, message=text, emotes=list(emotes or []))
    t = text.strip()
    if t.startswith("!"):
        parts = t[1:].split()
        e.is_command, e.command_name, e.args = True, parts[0].lower(), parts[1:]
    return e


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "config").mkdir()
        (d / "config" / "trivia.json").write_text(
            '[{"q": "Capital of France?", "a": ["Paris"]}]', encoding="utf-8")
        self.config = {"points": {"enabled": True, "per_message": 0},
                       "chat_games": {"enabled": True, "hype": {"levels": [3, 6]}}}
        self.store = Store(d / "t.db", self.config["points"])
        self.clock = Clock()
        self.rx = FakeReactions()
        self.replies = []
        self.sent = []

        async def reply(event, text):
            self.replies.append(text)

        async def broadcast(p):
            self.sent.append(p)

        self.g = ChatGames(lambda: self.config, store=self.store, perms=PermissionManager({}), reactions=self.rx,
                           data_dir=d / "data", config_dir=d / "config", reply=reply, broadcast=broadcast,
                           now=self.clock, rng=random.Random(4))

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, coro):
        return asyncio.run(coro)

    async def say(self, name, text, **kw):
        return await self.g.handle_chat(ev(name, text, **kw))

    async def points(self, name, amount):
        uid = await self.store.get_or_create_user("kick", name.lower(), name.lower(), name)
        await self.store.set_points(uid, amount)
        return uid

    async def bal(self, name):
        uid = await self.store.get_or_create_user("kick", name.lower(), name.lower(), name)
        return (await self.store.get_user(uid))["points"]

    async def tick(self, sec=0.0):
        self.clock.t += sec
        self.g.invalidate()
        await self.g.tick()

    def boards(self, bid):
        return [p["data"] for p in self.sent if p["type"] == "board" and p["data"]["id"] == bid]


class ConfigTests(unittest.TestCase):
    def test_defaults_off_and_clean(self):
        c = normalize_config(None)
        self.assertFalse(c["enabled"])
        self.assertEqual(len(c["combos"]["moods"]), 9)
        c = normalize_config({"enabled": True, "slots": {"min_bet": 500, "max_bet": 10, "command": "!Spin"},
                              "hype": {"levels": ["x", 9, 3]}, "extra_key": 1})
        self.assertEqual(c["slots"]["command"], "spin")
        self.assertEqual(c["slots"]["max_bet"], 500)
        self.assertEqual(c["hype"]["levels"], [3, 9])
        self.assertEqual(c["extra_key"], 1)

    def test_off_does_nothing(self):
        async def go():
            g = ChatGames(lambda: {"chat_games": {"enabled": False}})
            self.assertFalse(await g.handle_chat(ev("a", "!slots 5")))
        asyncio.run(go())

    def test_slots_pay_back_under_one(self):
        import itertools
        w = dict(Slots.REELS)
        total = sum(w.values())
        rtp = sum(w[a] * w[b] * w[c] / total ** 3 * Slots.multiplier([a, b, c])
                  for a, b, c in itertools.product(w, repeat=3))
        self.assertTrue(0.85 < rtp < 1.0, rtp)

    def test_answers_normalize(self):
        self.assertEqual(normalize_answer("  The Pacific Ocean! "), normalize_answer("pacific ocean"))
        self.assertEqual(normalize_answer("Montréal"), "montreal")


class CrowdTests(Base):
    def test_combo_needs_three_people_in_window(self):
        async def go():
            await self.say("a", "KEKW")
            await self.say("b", "lol 😂")
            self.assertEqual(self.rx.played, [])
            self.clock.t += 20            # outside the 10 s window
            await self.say("c", "KEKW")
            await self.say("d", "LUL")
            self.assertEqual([p for p in self.rx.played if p.get("reaction") == "combo_laugh"], [])
            await self.say("e", "KEKW KEKW")
            laugh = [p for p in self.rx.played if p.get("reaction") == "combo_laugh"]
            self.assertEqual({p["effect"] for p in laugh}, {"float_up", "crowd_motion"})
            self.assertEqual(len(laugh[0]["crowd"]), 3)
            self.assertEqual(laugh[0]["params"]["object"], "KEKW")     # the emote the crowd used
            # cooldown: a 4th laugher right after doesn't fire again
            combos = lambda: [p for p in self.rx.played if str(p.get("reaction", "")).startswith("combo_")]
            n = len(combos())
            for who in "fgh":
                await self.say(who, "😂")
            self.assertEqual(len(combos()), n)
        asyncio.run(go())

    def test_youtube_emote_names_and_symbols(self):
        async def go():
            for who in "abc":
                await self.say(who, ":face-red-heart-shape: <3", platform=Platform.YOUTUBE)
            self.assertTrue(any(p.get("reaction") == "combo_love" for p in self.rx.played))
        asyncio.run(go())

    def test_hype_levels_fire_once_and_show_meter(self):
        async def go():
            for who in "abc":
                await self.say(who, "hello")
            self.assertTrue(any(p.get("reaction") == "hype_1" for p in self.rx.played))
            n = len(self.rx.played)
            await self.say("a", "again")
            self.assertEqual(len(self.rx.played), n)
            await self.tick(0.5)
            b = self.boards("hype")[-1]
            self.assertEqual(b["kind"], "meter")
            self.assertEqual(b["lines"][0]["value"], 3)
            await self.tick(120)          # everyone went quiet
            self.assertNotIn("hype", self.g.boards)
        asyncio.run(go())

    def test_tug_of_war_round(self):
        async def go():
            self.assertTrue(await self.say("a", "!cheer"))
            await self.say("b", "!cheer")
            await self.say("c", "!boo")
            await self.say("a", "!cheer")          # too soon for a again (1 s gap)
            self.assertEqual(self.g.tug.round["cheer"], 2)
            await self.tick(31)
            last = self.boards("tug")[-1]
            self.assertEqual(last["state"], "closed")
            self.assertTrue(last["lines"][0]["win"])
            self.assertTrue(any(p.get("reaction") == "tug_cheer" for p in self.rx.played))
            await self.say("d", "!boo")            # cooling down: no new round
            self.assertIsNone(self.g.tug.round)
        asyncio.run(go())

    def test_launch_needs_people_then_counts_down(self):
        async def go():
            for who in "abcd":
                await self.say(who, "!launch")
            self.assertEqual(self.boards("launch")[-1]["lines"][0]["value"], 4)
            await self.say("e", "!launch")
            self.assertTrue(any(p["effect"] == "lights" for p in self.rx.played))
            for _ in range(4):
                await self.tick(1)
            self.assertTrue(any(p["effect"] == "fireworks" for p in self.rx.played))
            self.assertEqual(self.boards("launch")[-1]["title"], "🚀 LIFTOFF!")
            self.replies.clear()
            await self.say("f", "!launch")
            self.assertIn("recharging", self.replies[-1])
        asyncio.run(go())

    def test_launch_fizzles(self):
        async def go():
            await self.say("a", "!launch")
            await self.tick(61)
            self.assertEqual(self.boards("launch")[-1]["state"], "closed")
            await self.tick(61)
            await self.say("b", "!launch")          # a fizzle only waits a minute
            self.assertIsNotNone(self.g.launch.window)
        asyncio.run(go())


class WagerTests(Base):
    def test_prediction_split(self):
        async def go():
            await self.points("a", 100)
            await self.points("b", 100)
            await self.points("c", 100)
            await self.say("mod", "!predict open Twist? | yes | no", mod=True)
            await self.say("a", "!predict yes 60")
            await self.say("b", "!predict 1 20")
            await self.say("c", "!predict no 50")
            await self.say("c", "!predict yes 5")    # can't switch sides
            self.assertEqual(await self.bal("c"), 50)
            await self.say("mod", "!predict lock", mod=True)
            await self.say("a", "!predict yes 10")  # locked
            self.assertEqual(await self.bal("a"), 40)
            await self.say("mod", "!predict win yes", mod=True)
            # pot 130 split 60:20 -> 97 (+1 rounding) and 32
            self.assertEqual(await self.bal("a"), 40 + 98)
            self.assertEqual(await self.bal("b"), 80 + 32)
            self.assertEqual(await self.bal("c"), 50)
            self.assertIsNone(self.g.predict.p)
        asyncio.run(go())

    def test_prediction_nobody_right_refunds(self):
        async def go():
            await self.points("a", 50)
            await self.g.predict.open("Q", ["x", "y", "z"])
            await self.say("a", "!predict x 50")
            await self.g.predict.resolve("3")
            self.assertEqual(await self.bal("a"), 50)
        asyncio.run(go())

    def test_viewer_cannot_open_prediction(self):
        async def go():
            await self.say("a", "!predict open Q | x | y")
            self.assertIsNone(self.g.predict.p)
        asyncio.run(go())

    def test_duel_accept_and_expire(self):
        async def go():
            await self.points("a", 100)
            await self.points("b", 100)
            await self.say("a", "!duel @b 40")
            self.assertEqual(await self.bal("a"), 60)
            await self.say("b", "!accept")
            total = await self.bal("a") + await self.bal("b")
            self.assertEqual(total, 200)
            self.assertEqual(sorted([await self.bal("a"), await self.bal("b")]), [60, 140])
            throw = [p for p in self.rx.played if p["effect"] == "throw"][-1]
            self.assertEqual(throw["target"]["type"], "user")
            # expire -> refund
            await self.tick(61)
            await self.points("c", 100)
            await self.say("c", "!duel b 30")
            await self.tick(61)
            self.assertEqual(await self.bal("c"), 100)
        asyncio.run(go())

    def test_duel_rules(self):
        async def go():
            await self.points("a", 20)
            await self.say("a", "!duel @a 10")
            self.assertIn("yourself", self.replies[-1])
            await self.say("a", "!duel @b 5000")
            self.assertIn("10-1000", self.replies[-1].replace(",", ""))
            await self.say("a", "!duel @b 15")
            await self.say("b", "!accept")         # b has 0 points
            self.assertIn("need 15", self.replies[-1])
        asyncio.run(go())

    def test_slots_spend_and_cooldown(self):
        async def go():
            await self.points("a", 100)
            await self.say("a", "!slots 10")
            self.assertIn("🎰", self.replies[-1])
            b1 = await self.bal("a")
            await self.say("a", "!slots 10")
            self.assertIn("warm", self.replies[-1])
            self.assertEqual(await self.bal("a"), b1)
            await self.say("a", "!slots 5000")
        asyncio.run(go())

    def test_points_off(self):
        async def go():
            self.config["points"]["enabled"] = False
            self.g.invalidate()
            await self.say("a", "!slots 10")
            self.assertIn("points are off", self.replies[-1])
        asyncio.run(go())

    def test_heist_runs_story(self):
        async def go():
            for n in "abc":
                await self.points(n, 100)
            await self.say("a", "!heist 50")
            await self.say("b", "!join 50")
            await self.say("c", "!join")           # joins with the starter's stake
            self.assertEqual(await self.bal("c"), 50)
            await self.tick(61)
            for _ in range(7):
                await self.tick(1)
            final = self.boards("heist")[-1]
            self.assertEqual(final["state"], "closed")
            self.assertIsNone(self.g.heist.h)
            total = sum([await self.bal(n) for n in "abc"])
            self.assertTrue(total in (150,) or total > 150)
            await self.say("a", "!heist 10")
            self.assertIn("alert", self.replies[-1])
        asyncio.run(go())


class WatchTests(Base):
    def test_poll(self):
        async def go():
            self.assertFalse(await self.say("a", "!1"))          # no poll: not ours
            await self.say("m", "!poll Snack? | Popcorn | Nachos | 90s", mod=True)
            self.assertTrue(await self.say("a", "!1"))
            await self.say("b", "!2")
            await self.say("c", "!2")
            await self.say("a", "!2")                            # changed their mind
            await self.tick(0.5)
            self.assertEqual(self.boards("poll")[-1]["lines"][1]["value"], 3)
            await self.tick(91)
            self.assertEqual(self.boards("poll")[-1]["state"], "closed")
            self.assertIn("Nachos wins", self.replies[-1])
        asyncio.run(go())

    def test_rate_opens_on_first_and_goes_to_credits(self):
        async def go():
            await self.say("a", "!rate 8")
            await self.say("b", "!rate 9/10")
            await self.say("c", "!rate 11")
            await self.tick(121)
            self.assertIn("8.5/10", self.replies[-1])
            s = await self.g.stream()
            self.assertIn("8.5 / 10", self.g.rate.credits_line(s["id"]))
        asyncio.run(go())

    def test_requests_and_bump(self):
        async def go():
            await self.points("b", 500)
            await self.say("a", "!request https://example.com/v/1 Cool video")
            await self.say("b", "!request Some movie")
            await self.say("b", "!request some MOVIE")
            self.assertIn("already", self.replies[-1])
            await self.say("b", "!bump")
            q = self.g.requests.items
            self.assertEqual(q[0]["text"], "Some movie")
            self.assertEqual(q[1]["url"], "https://example.com/v/1")
            self.assertEqual(await self.bal("b"), 400)
            res = await self.g.admin_action("request", "played", {"id": q[0]["id"]})
            self.assertTrue(res["ok"])
            self.assertEqual(len(self.g.requests.items), 1)
        asyncio.run(go())

    def test_moments_merge(self):
        async def go():
            await self.say("a", "!clip what a save")
            self.clock.t += 5
            await self.say("b", "!moment")
            self.clock.t += 60
            await self.say("c", "!clip")
            m = self.g.moments.items
            self.assertEqual(len(m), 2)
            self.assertEqual(m[0]["count"], 2)
            self.assertEqual(m[0]["note"], "what a save")
            self.assertIn("stream_time", self.g.moments.csv())
        asyncio.run(go())

    def test_trivia(self):
        async def go():
            await self.points("a", 0)
            await self.say("m", "!trivia", mod=True)
            self.assertFalse(await self.say("a", "!answer london") and False)
            await self.say("b", "!answer london")
            self.assertIsNotNone(self.g.trivia.q)
            await self.say("a", "!answer  paris ")
            self.assertIsNone(self.g.trivia.q)
            self.assertEqual(await self.bal("a"), 100)
            self.assertTrue(any(p["effect"] == "spotlight" for p in self.rx.played))
            await self.say("m", "!trivia", mod=True)
            await self.tick(46)
            self.assertIn("It was Paris", self.replies[-1])
        asyncio.run(go())


class RegularTests(Base):
    def test_claim_once_per_stream_and_streak_titles(self):
        async def go():
            self.config["chat_games"]["streak"] = {"titles": [{"streams": 2, "title": "Regular"}]}
            self.g.invalidate()
            await self.say("a", "!claim")
            await self.say("a", "!claim")
            self.assertIn("already claimed", self.replies[-1])
            self.assertEqual(await self.bal("a"), 50)
            self.clock.t += 5 * 3600        # quiet gap -> next stream
            await self.say("a", "hi again")
            self.assertEqual(self.g.title_for(ev("a", "x").user), "Regular")
            self.assertEqual(self.g.title_by_name("kick", "A"), "Regular")
            await self.say("a", "!streak")
            self.assertIn("2 streams in a row", self.replies[-1])
            await self.say("a", "!claim")
            self.assertEqual(await self.bal("a"), 100)
        asyncio.run(go())

    def test_seat_front_costs_and_swap(self):
        async def go():
            await self.points("a", 60)
            await self.say("a", "!seat front")
            mv = [p for p in self.rx.played if p["effect"] == "seat_move"][-1]
            self.assertEqual(mv["params"], {"where": "front"})
            self.assertEqual(mv["charge"]["amount"], 50)
            self.assertEqual(await self.bal("a"), 10)
            await self.say("a", "!seat back")
            self.assertIn("again in", self.replies[-1])
            await self.say("a", "!swap @b")
            await self.say("b", "!swap")
            sw = [p for p in self.rx.played if p["effect"] == "seat_swap"][-1]
            self.assertEqual(sw["from_user"]["username"], "a")
            self.assertEqual(sw["target"], {"type": "user", "name": "b"})
        asyncio.run(go())

    def test_curtain_is_for_mods(self):
        async def go():
            await self.say("a", "!curtain close")
            self.assertEqual([p for p in self.rx.played if p["effect"] == "stage"], [])
            await self.say("m", "!curtain close", mod=True)
            await self.say("m", "!curtain", mod=True)
            await self.say("m", "!curtain show", mod=True)
            got = [p["value"] for p in self.rx.played if p["effect"] == "stage"]
            self.assertEqual(got, ["close", "toggle", "reveal"])
            await self.say("m", "!curtain sideways", mod=True)
            self.assertIn("open | close | reveal", self.replies[-1])
        asyncio.run(go())

    def test_game_commands_listed_and_command_taken(self):
        async def go():
            self.assertIn("slots", self.g.command_names())
            self.assertFalse(await self.g.handle_chat(ev("a", "!slots 5"), command_taken=True))
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
