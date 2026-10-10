"""Command groups + name/alias conflict resolution."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.command_groups import resolve_active_groups, catalog_status
from core.command_router import CommandRouter
from core.permissions import PermissionManager


class GroupResolveTests(unittest.TestCase):
    def test_core_always_on(self):
        active = resolve_active_groups({"command_groups": {"core": {"enabled": False}}})
        self.assertIn("core", active)

    def test_minecraft_requires_running_and_enabled(self):
        cfg = {
            "minecraft": {"enabled": True},
            "command_groups": {"minecraft": {"enabled": True, "bind": "minecraft"}},
        }
        self.assertNotIn("minecraft", resolve_active_groups(cfg, running_games=[]))
        self.assertIn("minecraft", resolve_active_groups(cfg, running_games=["minecraft"]))
        cfg["minecraft"]["enabled"] = False
        self.assertNotIn("minecraft", resolve_active_groups(cfg, running_games=["minecraft"]))

    def test_manual_disable(self):
        cfg = {
            "minecraft": {"enabled": True},
            "command_groups": {"minecraft": {"enabled": False, "bind": "minecraft"}},
        }
        self.assertNotIn("minecraft", resolve_active_groups(cfg, running_games=["minecraft"]))

    def test_points_bind(self):
        cfg = {"points": {"enabled": False}, "command_groups": {"points": {"enabled": True, "bind": "points"}}}
        self.assertNotIn("points", resolve_active_groups(cfg))
        cfg["points"]["enabled"] = True
        self.assertIn("points", resolve_active_groups(cfg))

    def test_catalog_includes_reason(self):
        cfg = {"minecraft": {"enabled": False},
               "command_groups": {"minecraft": {"enabled": True, "bind": "minecraft"}}}
        rows = catalog_status(cfg, running_games=[])
        mc = next(r for r in rows if r["id"] == "minecraft")
        self.assertFalse(mc["active"])
        self.assertIn("enabled=false", mc["reason"])


class ConflictTests(unittest.TestCase):
    def _router(self, commands: dict) -> CommandRouter:
        tmp = Path(tempfile.mkdtemp()) / "commands.json"
        tmp.write_text(json.dumps(commands), encoding="utf-8")
        return CommandRouter(tmp, PermissionManager({"permissions": {"admin": ["a"], "mod": []}}))

    def test_alias_loses_to_higher_priority(self):
        r = self._router({
            "spawn": {"aliases": ["summon"], "group": "core", "priority": 0, "template": "a"},
            "summon": {"group": "core", "priority": 10, "template": "b"},
        })
        self.assertEqual(r.find("summon").name, "summon")
        self.assertTrue(any(c["token"] == "summon" for c in r.conflicts))

    def test_first_wins_on_tie(self):
        r = self._router({
            "alpha": {"aliases": ["go"], "group": "core", "priority": 1, "template": "a"},
            "beta": {"aliases": ["go"], "group": "core", "priority": 1, "template": "b"},
        })
        self.assertEqual(r.find("go").name, "alpha")

    def test_reload_picks_up_new_file(self):
        r = self._router({"help": {"group": "core", "special": "help", "handler": "core"}})
        self.assertIsNotNone(r.find("help"))
        r.commands_path.write_text(json.dumps({
            "help": {"group": "core", "special": "help", "handler": "core"},
            "ping": {"group": "core", "handler": "core"},
        }), encoding="utf-8")
        info = r.reload()
        self.assertEqual(info["loaded"], 2)
        self.assertIsNotNone(r.find("ping"))


# Minecraft-style game commands with allow-lists, written to a temp file so the test never
# depends on config/commands.json (that's also the streamer's own, locally edited file).
ALLOW_LIST_COMMANDS = {
    "give": {"aliases": ["item"], "permission": "public", "args": ["item", "qty?"],
             "allowedValues": ["diamond", "iron_ingot", "bread", "torch"],
             "defaultQty": 1, "maxQty": 64, "template": "give {player} {arg1} {qty}",
             "group": "minecraft", "handler": "game"},
    "spawn": {"aliases": ["summon"], "permission": "public", "args": ["entity", "qty?"],
              "allowedValues": ["creeper", "zombie", "skeleton", "chicken"],
              "defaultQty": 1, "maxQty": 8, "template": "execute at {player} run summon {arg1} ~ ~1 ~",
              "qtyTemplate": "execute at {player} run summon {arg1} ~ ~1 ~",
              "group": "minecraft", "handler": "game"},
    "effect": {"aliases": ["potion"], "permission": "public", "args": ["effect", "seconds?"],
               "allowedValues": ["speed", "regeneration", "night_vision"],
               "defaultSeconds": 30, "maxSeconds": 120,
               "template": "effect give {player} {arg1} {seconds} 1 true",
               "group": "minecraft", "handler": "game"},
}


class GameCommandAllowListTests(unittest.TestCase):
    """Game commands with an allow-list only pass listed ids into the game command."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.commands_path = Path(tmp.name) / "commands.json"
        self.commands_path.write_text(json.dumps(ALLOW_LIST_COMMANDS), encoding="utf-8")

    def _run(self, text):
        from core.models import ChatEvent, ChatUser, Platform

        r = CommandRouter(self.commands_path,
                          PermissionManager({"permissions": {"admin": [], "mod": []}}),
                          default_player="Steve")
        r.set_enabled_groups({"core", "minecraft"})
        ev = ChatEvent(platform=Platform.KICK, user=ChatUser(platform=Platform.KICK, id="1", username="viewer"),
                       message=text)
        self.assertTrue(r.parse_message(ev))
        return r.try_execute(ev)

    def test_injection_and_dangerous_values_refused(self):
        for text in ("!give netherite_sword[enchantments={levels:{sharpness:255}}]",
                     "!give command_block", "!give tnt 64", "!spawn wither",
                     "!spawn ender_dragon", "!effect instant_damage", "!summon tnt"):
            req, reason = self._run(text)
            self.assertIsNone(req, text)
            self.assertIn("invalid value", reason)

    def test_listed_values_work_lowercased(self):
        req, _ = self._run("!give Diamond 5")
        self.assertEqual(req.template, "give Steve diamond 5")
        req, _ = self._run("!spawn creeper")
        self.assertIn("summon creeper", req.template)
        req, _ = self._run("!effect speed 45")
        self.assertEqual(req.template, "effect give Steve speed 45 1 true")


if __name__ == "__main__":
    unittest.main()
