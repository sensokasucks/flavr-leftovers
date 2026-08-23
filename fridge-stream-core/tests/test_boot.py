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
from core.models import ChatEvent, ChatUser, Platform
from core.permissions import PermissionManager
from core.store import Store


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
        self.assertEqual(cfg["overlay"]["show_inventory_seconds"], 12)
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


class PermissionTests(unittest.TestCase):
    def test_string_admin_is_accepted(self):
        pm = PermissionManager({"permissions": {"admin": "Sensoka", "mod": []}})
        self.assertIn("sensoka", pm.admins)


if __name__ == "__main__":
    unittest.main()
