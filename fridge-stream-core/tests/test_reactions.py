"""Chat reactions engine (core/reactions.py) + atomic points spend. Run from fridge-stream-core:

    python -m unittest tests.test_reactions -v
"""

from __future__ import annotations

import asyncio
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.permissions import PermissionManager  # noqa: E402
from core.reactions import DEFAULT_REACTIONS, LATER_DEFAULTS, ReactionEngine, normalize_config  # noqa: E402
from core.store import Store  # noqa: E402


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def ev(text, user="alice", platform=Platform.TWITCH, **flags):
    u = ChatUser(platform=platform, id=user.lower(), username=user, display_name=user, **flags)
    e = ChatEvent(platform=platform, user=u, message=text)
    if text.startswith("!"):
        parts = text[1:].split()
        e.is_command = True
        e.command_name = parts[0].lower()
        e.args = parts[1:]
    return e


class Harness:
    """Engine + temp store + captured replies / broadcasts."""

    def __init__(self, tmp: Path, reactions=None, points=True, admins=()):
        self.config = {
            "points": {"enabled": points, "per_message": 0},
            "permissions": {"admin": list(admins), "mod": []},
            "reactions": reactions if reactions is not None else {"enabled": True},
        }
        self.store = Store(tmp / "t.db", self.config["points"], {})
        self.replies, self.broadcasts, self.said = [], [], []

        async def reply(event, text):
            self.replies.append(text)

        async def say(text, platform):
            self.said.append(text)

        async def broadcast(payload):
            self.broadcasts.append(payload)

        self.eng = ReactionEngine(
            get_config=lambda: self.config,
            store=self.store,
            perms=PermissionManager(self.config),
            data_dir=tmp,
            reply=reply,
            say=say,
            broadcast=broadcast,
            groups_active=lambda: {"core", "reactions"},
        )

    def set_entries(self, *entries, **top):
        cfg = {"enabled": True, **top, "entries": list(entries)}
        self.config["reactions"] = cfg

    async def give(self, user, pts, platform="twitch"):
        uid = await self.store.get_or_create_user(platform, user.lower(), user, user)
        await self.store.adjust_points(uid, pts, "test", "test")
        return uid

    async def balance(self, uid):
        return int((await self.store.get_user(uid))["points"])


def entry(**kw):
    base = {"id": "tomato", "emoji": ["🍅"], "commands": ["tomato"], "effect": "throw",
            "targets": ["stage", "user", "guest"], "default_target": "stage",
            "cooldown_user_sec": 0, "max_per_message": 3}
    base.update(kw)
    return base


def run(coro):
    return asyncio.run(coro)


class ConfigTests(unittest.TestCase):
    def test_defaults_off_and_clean(self):
        cfg = normalize_config(None)
        self.assertFalse(cfg["enabled"])
        self.assertTrue(cfg["entries"])
        ids = [e["id"] for e in cfg["entries"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_normalize_cleans_bad_values(self):
        cfg = normalize_config({"send_to": "moon", "seeded_defaults": list(LATER_DEFAULTS), "entries": [
            {"id": "A b!", "commands": ["!Throw", "x y"], "targets": ["stage", "nope"], "permission": "god",
             "cost": -5, "require": ["sub", "king"], "max_per_message": 999},
            {"id": "ab"},          # duplicate after slugging
            {"label": ""},         # no id
        ]})
        self.assertEqual(cfg["send_to"], "auto")
        self.assertEqual(len(cfg["entries"]), 1)
        e = cfg["entries"][0]
        self.assertEqual(e["id"], "ab")
        self.assertEqual(e["commands"], ["throw", "xy"])
        self.assertEqual(e["targets"], ["stage"])
        self.assertEqual(e["permission"], "public")
        self.assertEqual(e["cost"], 0)
        self.assertEqual(e["require"], ["sub"])
        self.assertEqual(e["max_per_message"], 50)

    def test_core_defaults_include_reactions(self):
        from core.command_groups import DEFAULT_GROUPS
        from core.config import DEFAULTS
        self.assertIn("reactions", DEFAULTS)
        self.assertFalse(DEFAULTS["reactions"]["enabled"])
        self.assertEqual(DEFAULT_GROUPS["reactions"]["bind"], "reactions")
        self.assertIn("reactions", DEFAULTS["command_groups"])

    def test_save_config_roundtrip_keeps_emoji_and_groups(self):
        from core.config import load_config, save_config
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            data = {"reactions": copy.deepcopy(DEFAULT_REACTIONS), "command_groups": {"custom": {"enabled": True}},
                    "made_up_section": {"x": 1}}
            save_config(data, p)
            back = load_config(p)
            self.assertEqual(back["reactions"]["entries"][0]["emoji"], ["🍅"])
            self.assertIn("custom", back["command_groups"])
            self.assertEqual(back["made_up_section"], {"x": 1})


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_emoji_count_caps_and_variation_selector(self):
        self.h.set_entries(entry(), entry(id="heart", emoji=["❤️"], commands=[], max_per_message=1))
        cfg = self.h.eng.cfg
        hits = dict((e["id"], n) for e, n in self.h.eng.match_triggers(ev("🍅🍅🍅🍅🍅 ❤ lol"), cfg["entries"]))
        self.assertEqual(hits, {"tomato": 3, "heart": 1})

    def test_emote_names_twitch_kick_and_text(self):
        self.h.set_entries(entry(emoji=[], emotes=["PogTomato"]))
        cfg = self.h.eng.cfg
        e1 = ev("nice PogTomato")
        e1.emotes = [{"name": "PogTomato", "start": 5, "end": 13}]
        self.assertEqual(self.h.eng.match_triggers(e1, cfg["entries"])[0][1], 1)
        e2 = ev("[emote:123:PogTomato] [emote:123:PogTomato]", platform=Platform.KICK)
        self.assertEqual(self.h.eng.match_triggers(e2, cfg["entries"])[0][1], 2)
        e3 = ev("pogtomato as plain text")
        self.assertEqual(self.h.eng.match_triggers(e3, cfg["entries"])[0][1], 1)
        self.assertEqual(self.h.eng.match_triggers(ev("pogtomatoes"), cfg["entries"]), [])

    def test_emoji_message_fires_to_overlay_with_mention_target(self):
        self.h.set_entries(entry())
        run(self.h.eng.handle_chat(ev("🍅🍅 @Bob")))
        self.assertEqual(len(self.h.broadcasts), 1)
        d = self.h.broadcasts[0]["data"]
        self.assertEqual((d["effect"], d["route"], d["count"]), ("throw", "overlay", 2))
        self.assertEqual(d["target"], {"type": "user", "name": "Bob"})
        self.assertEqual(d["params"]["impact"], "splat")   # catalog default filled in

    def test_disabled_or_group_off_does_nothing(self):
        self.h.set_entries(entry(), enabled=False)
        run(self.h.eng.handle_chat(ev("🍅")))
        self.h.set_entries(entry())
        self.h.eng._groups_active = lambda: {"core"}
        run(self.h.eng.handle_chat(ev("🍅")))
        self.assertEqual(self.h.broadcasts, [])

    def test_router_owned_command_is_left_alone(self):
        self.h.set_entries(entry())
        self.assertFalse(run(self.h.eng.handle_chat(ev("!tomato"), router_owns_command=True)))
        self.assertTrue(run(self.h.eng.handle_chat(ev("!tomato"))))
        self.assertEqual(len(self.h.broadcasts), 1)

    def test_system_messages_ignored(self):
        self.h.set_entries(entry())
        run(self.h.eng.handle_chat(ev("🍅", badges=["system"])))
        self.assertEqual(self.h.broadcasts, [])


class CommandCountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self.tmp.name))
        self.ws = FakeWS()
        run(self.h.eng.on_client_message(self.ws, {"type": "hello", "data": {"client": "stream_rooms", "protocol": 1}}))
        run(self.h.eng.on_client_message(self.ws, {"type": "room_state", "data": {
            "room": "hall", "targets": [{"id": "screen"}, {"id": "presenter2", "aliases": ["presenter 2"]}],
            "guests": [], "seated": ["alice", "bob"]}}))
        self.ws.sent.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def fire(self, text):
        self.ws.sent.clear()
        run(self.h.eng.handle_chat(ev(text)))
        return self.ws.sent[-1]["data"] if self.ws.sent else None

    def test_split_count(self):
        from core.reactions import split_count
        self.assertEqual(split_count(["x5"]), (5, []))
        self.assertEqual(split_count(["5"]), (5, []))
        self.assertEqual(split_count(["@bob", "5"]), (5, ["@bob"]))
        self.assertEqual(split_count(["bob", "3x"]), (3, ["bob"]))
        self.assertEqual(split_count(["presenter", "2"]), (None, ["presenter", "2"]))
        self.assertEqual(split_count(["presenter", "2", "x3"]), (3, ["presenter", "2"]))

    def test_typed_count_capped(self):
        self.h.set_entries(entry(max_per_message=5))
        self.assertEqual(self.fire("!tomato x4")["count"], 4)
        d = self.fire("!tomato @bob 9")
        self.assertEqual(d["count"], 5)
        self.assertEqual(d["target"], {"type": "user", "name": "bob"})
        d = self.fire("!tomato presenter 2")
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["target"]["name"], "presenter2")
        d = self.fire("!tomato screen x3")
        self.assertEqual((d["count"], d["target"]["name"]), (3, "screen"))

    def test_command_count_default(self):
        self.h.set_entries(entry(commands=["barrage"], max_per_message=1, command_count=10))
        self.assertEqual(self.fire("!barrage")["count"], 10)
        self.assertEqual(self.fire("!barrage x3")["count"], 3)

    def test_each_one_costs(self):
        self.h.set_entries(entry(cost=10, max_per_message=5))
        uid = run(self.h.give("alice", 30))
        self.assertEqual(self.fire("!tomato x5")["count"], 3)     # could only afford 3
        self.assertEqual(run(self.h.balance(uid)), 0)


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self.tmp.name))
        self.ws = FakeWS()
        run(self.h.eng.on_client_message(self.ws, {"type": "hello", "data": {"client": "stream_rooms", "protocol": 1}}))
        run(self.h.eng.on_client_message(self.ws, {"type": "room_state", "data": {
            "room": "theater",
            "targets": [{"id": "screen", "aliases": ["tv"]}, {"id": "podium1"}],
            "guests": [{"id": "guest1", "name": "Mika"}],
            "seated": ["alice", "bob"],
        }}))
        self.ws.sent.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def fire_cmd(self, text, **kw):
        return run(self.h.eng.handle_chat(ev(text, **kw)))

    def last(self):
        return self.ws.sent[-1]["data"]

    def test_game_route_and_named_targets(self):
        self.h.set_entries(entry())
        self.fire_cmd("!tomato tv")
        self.assertEqual(self.last()["route"], "game")
        self.assertEqual(self.last()["target"], {"type": "stage", "name": "screen"})
        self.fire_cmd("!tomato mika")
        self.assertEqual(self.last()["target"], {"type": "guest", "name": "guest1"})
        self.fire_cmd("!tomato bob")
        self.assertEqual(self.last()["target"], {"type": "user", "name": "bob"})
        self.fire_cmd("!tomato")
        self.assertEqual(self.last()["target"], {"type": "stage", "name": ""})
        self.assertEqual(self.h.broadcasts, [])   # nothing leaked to the overlay route

    def test_target_names_with_spaces(self):
        self.h.set_entries(entry())
        run(self.h.eng.on_client_message(self.ws, {"type": "room_state", "data": {
            "room": "panel",
            "targets": [{"id": "screen"}, {"id": "podium2", "label": "Podium 2"}, {"id": "big_piano", "label": "Big Piano"}],
            "guests": [{"id": "presenter2", "name": "Presenter 2", "aliases": ["guest2", "p2"]}],
            "seated": ["sgt_crumpet"],
        }}))
        for text, want in [
            ("!tomato presenter 2", {"type": "guest", "name": "presenter2"}),
            ("!tomato Presenter 2 lol", {"type": "guest", "name": "presenter2"}),
            ("!tomato GUEST 2", {"type": "guest", "name": "presenter2"}),
            ("!tomato podium 2", {"type": "stage", "name": "podium2"}),
            ("!tomato Podium2", {"type": "stage", "name": "podium2"}),
            ("!tomato big piano", {"type": "stage", "name": "big_piano"}),
            ("!tomato big-piano", {"type": "stage", "name": "big_piano"}),
            ("!tomato sgt crumpet", {"type": "user", "name": "sgt_crumpet"}),
            ("!tomato screen please", {"type": "stage", "name": "screen"}),
        ]:
            self.ws.sent.clear()
            self.fire_cmd(text, user="u" + str(len(text)))
            self.assertTrue(self.ws.sent, text + " → " + (self.h.replies[-1] if self.h.replies else "no reply"))
            self.assertEqual(self.last()["target"], want, text)
        self.fire_cmd("!tomato presenter 9", user="x1")
        self.assertIn("no presenter 9 here", self.h.replies[-1])

    def test_spaces_without_room_info(self):
        self.h.set_entries(entry())
        self.h.eng.room_state = None
        self.fire_cmd("!tomato presenter 2 lol")
        self.assertEqual(self.last()["target"], {"type": "stage", "name": "presenter2"})

    def test_bad_and_disallowed_targets_reply(self):
        self.h.set_entries(entry(targets=["stage"]))
        self.fire_cmd("!tomato fridge")
        self.fire_cmd("!tomato @bob")
        self.fire_cmd("!tomato @nobody")
        self.assertEqual(self.ws.sent, [])
        self.assertIn("no fridge here", self.h.replies[0])
        self.assertIn("audience member", self.h.replies[1])

    def test_user_not_seated(self):
        self.h.set_entries(entry())
        self.fire_cmd("!tomato @carol")
        self.assertEqual(self.ws.sent, [])
        self.assertIn("@carol", self.h.replies[-1])

    def test_opt_out_and_opt_in_persist(self):
        self.h.set_entries(entry())
        self.fire_cmd("!nothrow", user="bob")
        self.fire_cmd("!tomato @bob")
        self.assertEqual(self.ws.sent, [])
        self.assertIn("isn't taking reactions", self.h.replies[-1])
        # self-target still fine, and the book survives a restart
        again = ReactionEngine(get_config=lambda: self.h.config, data_dir=Path(self.tmp.name))
        self.assertFalse(again.opt.targetable("BOB", "opt_out"))
        self.fire_cmd("!throwok", user="bob")
        self.fire_cmd("!tomato @bob")
        self.assertEqual(self.last()["target"]["name"], "bob")

    def test_opt_in_mode(self):
        self.h.set_entries(entry(), targeting="opt_in")
        self.fire_cmd("!tomato @bob")
        self.assertEqual(self.ws.sent, [])
        self.fire_cmd("!throwok", user="bob")
        self.fire_cmd("!tomato @bob")
        self.assertEqual(len(self.ws.sent), 1)

    def test_targets_command(self):
        self.h.set_entries(entry())
        self.fire_cmd("!targets")
        self.assertIn("screen, podium1, Mika", self.h.replies[-1])

    def test_cooldowns_user_and_target(self):
        self.h.set_entries(entry(cooldown_user_sec=30, cooldown_target_sec=0))
        self.fire_cmd("!tomato")
        self.fire_cmd("!tomato")
        self.assertEqual(len(self.ws.sent), 1)
        self.assertIn("cooling down (30s)", self.h.replies[-1])
        self.fire_cmd("!tomato", user="bob")      # other user unaffected
        self.assertEqual(len(self.ws.sent), 2)
        self.h.set_entries(entry(cooldown_target_sec=60))
        self.fire_cmd("!tomato @bob", user="alice")
        self.fire_cmd("!tomato @bob", user="dave")
        self.assertEqual(len(self.ws.sent), 3)

    def test_emoji_failures_are_silent(self):
        self.h.set_entries(entry(cooldown_user_sec=30))
        self.fire_cmd("🍅")
        self.fire_cmd("🍅")
        self.assertEqual(len(self.ws.sent), 1)
        self.assertEqual(self.h.replies, [])

    def test_permissions_mod_and_sub(self):
        self.h.set_entries(entry(permission="mod"))
        self.fire_cmd("!tomato")
        self.assertEqual(self.ws.sent, [])
        self.assertIn("mods only", self.h.replies[-1])
        self.fire_cmd("!tomato", is_mod=True)
        self.assertEqual(len(self.ws.sent), 1)
        self.h.set_entries(entry(require=["sub", "vip"]))
        self.fire_cmd("!tomato", user="x")
        self.assertIn("subs / VIPs", self.h.replies[-1])
        self.fire_cmd("!tomato", user="y", is_vip=True)
        self.assertEqual(len(self.ws.sent), 2)

    def test_detach_falls_back_to_overlay_and_forgets_room(self):
        self.h.set_entries(entry())
        self.h.eng.detach(self.ws)
        self.assertIsNone(self.h.eng.room_state)
        self.fire_cmd("!tomato screen")
        self.assertEqual(self.h.broadcasts[-1]["data"]["route"], "overlay")

    def test_game_only_effect_without_game(self):
        self.h.set_entries(entry(effect="wiggle", targets=[]))
        self.h.eng.detach(self.ws)
        self.fire_cmd("!tomato")
        self.assertEqual(self.h.broadcasts, [])
        self.assertIn("stage isn't open", self.h.replies[-1])


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_hello_caps_persist_and_merge(self):
        ws = FakeWS()
        caps = [{"id": "throw", "label": "Throw (3D)", "params": [{"name": "object", "type": "text", "default": "🥚"}]},
                {"id": "disco", "label": "Disco floor", "params": []}]
        run(self.h.eng.on_client_message(ws, {"type": "hello", "data": {"client": "stream_rooms", "effects": caps}}))
        self.assertEqual(ws.sent[0]["type"], "hello_ok")
        eff = {e["id"]: e for e in self.h.eng.known_effects()}
        self.assertTrue(eff["disco"]["in_game"])
        self.assertTrue(eff["throw"]["overlay"])
        self.assertFalse(eff["wiggle"]["in_game"])      # built-in the game didn't list
        self.assertEqual(eff["throw"]["label"], "Throw (3D)")
        self.assertEqual([p["default"] for p in eff["throw"]["params"]], ["🥚"])
        caps2 = [{"id": "throw", "label": "Throw", "params": []}]
        run(self.h.eng.on_client_message(ws, {"type": "hello", "data": {"effects": caps2}}))
        eff = {e["id"]: e for e in self.h.eng.known_effects()}
        self.assertIn("impact", [p["name"] for p in eff["throw"]["params"]])   # built-in settings kept
        again = ReactionEngine(get_config=lambda: self.h.config, data_dir=Path(self.tmp.name))
        self.assertEqual([e["id"] for e in again.game_effects], ["throw"])   # latest hello wins, persisted

    def test_non_hello_client_cannot_say(self):
        ws = FakeWS()
        run(self.h.eng.on_client_message(ws, {"type": "say", "data": {"text": "hi"}}))
        run(self.h.eng.on_client_message(ws, {"type": "room_state", "data": {"room": "x"}}))
        self.assertEqual(self.h.said, [])
        self.assertIsNone(self.h.eng.room_state)

    def test_say_rate_limit_and_trim(self):
        self.h.set_entries(entry(), say_per_minute=2)
        ws = FakeWS()
        run(self.h.eng.on_client_message(ws, {"type": "hello", "data": {}}))
        for i in range(4):
            run(self.h.eng.on_client_message(ws, {"type": "say", "data": {"text": f"  line   {i} " + "x" * 400}}))
        self.assertEqual(len(self.h.said), 2)
        self.assertTrue(self.h.said[0].startswith("line 0 x"))
        self.assertEqual(len(self.h.said[0]), 300)

    def test_overlay_relay(self):
        ws = FakeWS()
        run(self.h.eng.on_client_message(ws, {"type": "hello", "data": {}}))
        run(self.h.eng.on_client_message(ws, {"type": "overlay", "data": {"kind": "banner", "text": "Guest joined"}}))
        self.assertEqual(self.h.broadcasts[-1], {"type": "game_overlay", "data": {"kind": "banner", "text": "Guest joined"}})


class PointsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self.tmp.name), admins=["twitch:boss"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_spend_points_atomic_and_never_negative(self):
        async def go():
            uid = await self.h.give("alice", 25)
            self.assertEqual(await self.h.store.spend_points(uid, 10, 5, "t", "reaction"), (2, 5))
            self.assertEqual(await self.h.store.spend_points(uid, 10, 1, "t", "reaction"), (0, 5))
            results = await asyncio.gather(*[self.h.store.spend_points(uid, 1, 1, "t", "reaction") for _ in range(10)])
            self.assertEqual(sum(r[0] for r in results), 5)
            self.assertEqual(await self.h.balance(uid), 0)
        run(go())

    def test_cost_charges_and_limits_count(self):
        self.h.set_entries(entry(cost=10))
        async def go():
            uid = await self.h.give("alice", 25)
            await self.h.eng.handle_chat(ev("🍅🍅🍅"))
            self.assertEqual(self.h.broadcasts[-1]["data"]["count"], 2)   # afforded 2 of 3
            self.assertEqual(self.h.broadcasts[-1]["data"]["cost"], 20)
            self.assertEqual(await self.h.balance(uid), 5)
            await self.h.eng.handle_chat(ev("!tomato"))
            self.assertEqual(len(self.h.broadcasts), 1)
            self.assertIn("costs 10 points — you have 5", self.h.replies[-1])
        run(go())

    def test_admins_free(self):
        self.h.set_entries(entry(cost=10))
        async def go():
            await self.h.eng.handle_chat(ev("!tomato", user="boss"))
            self.assertEqual(self.h.broadcasts[-1]["data"]["cost"], 0)
        run(go())

    def test_cost_needs_points_enabled(self):
        self.h.set_entries(entry(cost=10))
        self.h.config["points"]["enabled"] = False
        async def go():
            await self.h.give("alice", 100)
            await self.h.eng.handle_chat(ev("!tomato"))
            self.assertEqual(self.h.broadcasts, [])
            st = {s["id"]: s for s in self.h.eng.status()["entries"]}
            self.assertFalse(st["tomato"]["usable"])
        run(go())

    def test_refund_when_game_drops(self):
        self.h.set_entries(entry(cost=10))
        async def go():
            uid = await self.h.give("alice", 30)
            ws = FakeWS()
            await self.h.eng.on_client_message(ws, {"type": "hello", "data": {}})
            await self.h.eng.handle_chat(ev("!tomato"))
            rid = ws.sent[-1]["data"]["id"]
            self.assertEqual(await self.h.balance(uid), 20)
            await self.h.eng.on_client_message(ws, {"type": "reaction_result", "data": {"id": rid, "outcome": "dropped"}})
            self.assertEqual(await self.h.balance(uid), 30)
            # a second "dropped" for the same id can't refund twice
            await self.h.eng.on_client_message(ws, {"type": "reaction_result", "data": {"id": rid, "outcome": "dropped"}})
            self.assertEqual(await self.h.balance(uid), 30)
            await self.h.eng.handle_chat(ev("!tomato", user="alice"))
            rid2 = ws.sent[-1]["data"]["id"]
            await self.h.eng.on_client_message(ws, {"type": "reaction_result", "data": {"id": rid2, "outcome": "hit"}})
            self.assertEqual(await self.h.balance(uid), 20)
            self.assertEqual(self.h.eng.stats["refunded"], 1)
        run(go())

    def test_refund_when_send_fails(self):
        self.h.set_entries(entry(cost=10))

        class DeadWS(FakeWS):
            async def send_json(self, data):
                if data.get("type") == "reaction":
                    raise RuntimeError("gone")

        async def go():
            uid = await self.h.give("alice", 30)
            ws = DeadWS()
            await self.h.eng.on_client_message(ws, {"type": "hello", "data": {}})
            r = await self.h.eng.fire(self.h.eng.cfg["entries"][0], ev("!tomato"))
            self.assertFalse(r["ok"])
            self.assertEqual(await self.h.balance(uid), 30)
            self.assertFalse(self.h.eng.game_clients)
        run(go())


if __name__ == "__main__":
    unittest.main()


class NewReactionTests(unittest.TestCase):
    """Signs ({args}), high fives (need a target), emote pictures, Core's own play()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_sign_uses_the_typed_text(self):
        async def go():
            self.h.config["reactions"] = {"enabled": True}      # defaults: sign, highfive ...
            await self.h.eng.handle_chat(ev("!sign hi", user="zed"))
            self.assertIn("isn't open", self.h.replies[-1])        # no overlay version of a sign
            ws = FakeWS()
            await self.h.eng.on_client_message(ws, {"type": "hello", "data": {"effects": []}})
            await self.h.eng.handle_chat(ev("!sign GO TEAM 2 [emote:1:KEKW]", user="ann"))
            sent = [p["data"] for p in ws.sent if p.get("type") == "reaction"]
            self.assertEqual(sent[-1]["effect"], "sign")
            self.assertEqual(sent[-1]["params"]["text"], "GO TEAM 2 KEKW")
            await self.h.eng.handle_chat(ev("!sign", user="bob"))
            self.assertIn("what should it say", self.h.replies[-1])
        asyncio.run(go())

    def test_highfive_needs_someone(self):
        async def go():
            self.h.config["reactions"] = {"enabled": True, "send_to": "game"}
            ws = FakeWS()
            await self.h.eng.on_client_message(ws, {"type": "hello", "data": {"effects": []}})
            await self.h.eng.handle_chat(ev("!highfive", user="ann"))
            self.assertIn("who with", self.h.replies[-1])
            await self.h.eng.handle_chat(ev("!highfive @ann", user="ann"))
            self.assertIn("who with", self.h.replies[-1])
            await self.h.eng.handle_chat(ev("!hi5 @bob", user="ann"))
            got = [p["data"] for p in ws.sent if p.get("type") == "reaction"]
            self.assertEqual(got[-1]["target"], {"type": "user", "name": "bob"})
        asyncio.run(go())

    def test_emote_names_become_pictures(self):
        async def go():
            self.h.set_entries({"id": "kek", "commands": ["kek"], "effect": "throw", "params": {"object": "KEKW"},
                                "targets": ["stage"], "default_target": "stage"})
            e = ev("KEKW [emote:37226:KEKW]", user="ann")
            await self.h.eng.handle_chat(e)
            yt = ev("hi", user="yo", platform=Platform.YOUTUBE)
            yt.emotes = [{"provider": "youtube", "name": ":face-blue-star-eyes:", "url": "https://yt3.ggpht.com/x=s64",
                          "start": 0, "end": 1}]
            await self.h.eng.handle_chat(yt)
            await self.h.eng.handle_chat(ev("!kek", user="bob"))
            sent = [b["data"] for b in self.h.broadcasts if b.get("type") == "reaction"][-1]
            self.assertEqual(sent["params"]["object_image"]["url"], "https://files.kick.com/emotes/37226/fullsize")
            self.assertEqual(self.h.eng.emotes.picture("face-blue-star-eyes")["url"], "https://yt3.ggpht.com/x=s64")
            self.assertIsNone(self.h.eng.emotes.picture("nope"))
        asyncio.run(go())

    def test_core_play_with_crowd_and_refund(self):
        async def go():
            self.h.config["reactions"] = {"enabled": True, "send_to": "game"}
            self.assertIsNone(await self.h.eng.play("confetti", {}))            # no game connected
            ws = FakeWS()
            await self.h.eng.on_client_message(ws, {"type": "hello", "data": {"effects": []}})
            uid = await self.h.give("ann", 100)
            rid = await self.h.eng.play("seat_move", {"where": "front"}, crowd=[{"username": "ann"}],
                                        charge={"uid": uid, "amount": 30})
            data = ws.sent[-1]["data"]
            self.assertEqual(data["params"]["where"], "front")
            self.assertTrue(data["system"])
            self.assertEqual(data["crowd"], [{"username": "ann"}])
            await self.h.eng.on_client_message(ws, {"type": "reaction_result", "data": {"id": rid, "outcome": "dropped"}})
            self.assertEqual((await self.h.store.get_user(uid))["points"], 130)
        asyncio.run(go())
