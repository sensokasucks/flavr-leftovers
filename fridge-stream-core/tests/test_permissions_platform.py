"""Plain names in permissions can't be borrowed on the other platform.

    python -m pytest tests/test_permissions_platform.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.models import ChatUser, Platform  # noqa: E402
from core.permissions import PermissionManager  # noqa: E402


def user(plat, name, uid="1"):
    return ChatUser(platform=Platform(plat), id=uid, username=name)


def cfg(kick_on, twitch_on, admin=("sensoka",), mod=("bob",), kick="sensoka", twitch="sensoka_tv"):
    return {
        "permissions": {"admin": list(admin), "mod": list(mod)},
        "kick": {"enabled": kick_on, "channel_slug": kick},
        "twitch": {"enabled": twitch_on, "channel": twitch},
    }


class PlainNameTests(unittest.TestCase):
    def test_one_platform_on_plain_names_work_as_before(self):
        pm = PermissionManager(cfg(True, False))
        self.assertTrue(pm.is_admin(user("kick", "Sensoka")))
        self.assertTrue(pm.is_mod(user("kick", "bob")))

    def test_both_on_plain_name_only_counts_on_own_channel(self):
        pm = PermissionManager(cfg(True, True))
        self.assertTrue(pm.is_admin(user("kick", "sensoka")))
        # someone registered "sensoka" on Twitch, where the streamer is sensoka_tv
        self.assertFalse(pm.is_admin(user("twitch", "sensoka")))
        self.assertFalse(pm.is_mod(user("twitch", "bob")))
        self.assertEqual(pm.ambiguous_entries(), ["bob"])

    def test_platform_prefixed_entries_always_work(self):
        pm = PermissionManager(cfg(True, True, admin=("twitch:sensoka_tv",), mod=("kick:bob",)))
        self.assertTrue(pm.is_admin(user("twitch", "sensoka_tv")))
        self.assertTrue(pm.is_mod(user("kick", "bob")))
        self.assertFalse(pm.is_mod(user("twitch", "bob")))
        self.assertEqual(pm.ambiguous_entries(), [])

    def test_same_name_on_both_channels(self):
        pm = PermissionManager(cfg(True, True, twitch="sensoka"))
        self.assertTrue(pm.is_admin(user("kick", "sensoka")))
        self.assertTrue(pm.is_admin(user("twitch", "sensoka")))

    def test_follows_live_config(self):
        live = cfg(True, False)
        pm = PermissionManager(live, get_config=lambda: live)
        self.assertTrue(pm.is_mod(user("twitch", "bob")))
        live["twitch"]["enabled"] = True
        live["kick"]["enabled"] = True
        self.assertFalse(pm.is_mod(user("twitch", "bob")))

    def test_permit_by_plain_name_still_works(self):
        pm = PermissionManager(cfg(True, True))
        pm.grant_temp("carol", 5)
        self.assertTrue(pm.is_mod(user("twitch", "carol")))

    def test_youtube_never_matches_plain(self):
        pm = PermissionManager(cfg(False, False))
        self.assertFalse(pm.is_admin(user("youtube", "sensoka")))


if __name__ == "__main__":
    unittest.main()
