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
        rows = catalog_status({"minecraft": {"enabled": False}}, running_games=[])
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


if __name__ == "__main__":
    unittest.main()
