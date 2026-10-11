"""Overlay compatibility: saved extra stylesheets (?css=<name>) for the alerts and chat pages,
the alerts page's URL options, the chat page's template names, and mod deletes / timeouts /
clears reaching the overlays (``chat_removed``). Run from fridge-stream-core:

    python -m unittest tests.test_overlay_compat -v
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.kick import KickAdapter, kick_removed  # noqa: E402
from adapters.twitch import TwitchAdapter  # noqa: E402
from adapters.youtube import YouTubeAdapter, youtube_removed  # noqa: E402
from adapters.youtube_capture import FieldScout  # noqa: E402
from core.chat_style import CHAT_STYLE  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402
from core.overlay_catalog import by_id  # noqa: E402
from core.overlay_style import MAX_CSS_SLOTS, OverlayStyle  # noqa: E402

OVERLAY = ROOT / "overlay"


def run(coro):
    return asyncio.run(coro)


def chat_style(root: Path) -> OverlayStyle:
    return OverlayStyle("chat", CHAT_STYLE.skins, CHAT_STYLE.image_slots, CHAT_STYLE.sound_slots,
                        CHAT_STYLE.default_options, CHAT_STYLE.ranges, overlay_dir=root)


class CssSlots(unittest.TestCase):
    def test_slots_save_list_and_delete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            style = chat_style(root)
            style.write_css(".msg { color: red; }", overlay_dir=root)
            before = style.read_settings(root)["css_version"]
            s = style.write_css(".msg { color: purple; }", overlay_dir=root, slot="Twitch Look")
            self.assertEqual(list(s["css_slots"]), ["twitch-look"])
            self.assertEqual(s["css_version"], before)          # the main sheet's version is untouched
            self.assertTrue((root / "chat-css" / "twitch-look.css").is_file())
            self.assertEqual(style.read_css(root, slot="twitch-look"), ".msg { color: purple; }")
            self.assertEqual(style.read_css(root, slot="default"), ".msg { color: red; }")
            self.assertEqual(style.read_css(root, slot="missing"), "")
            with self.assertRaises(ValueError):
                style.write_css("<style>x</style>", overlay_dir=root, slot="twitch-look")
            with self.assertRaises(ValueError):
                style.write_css(".a{}", overlay_dir=root, slot="!!!")
            self.assertFalse(style.delete_css_slot("default", root))
            self.assertTrue(style.delete_css_slot("twitch-look", root))
            self.assertEqual(style.list_css_slots(root), {})

    def test_slot_cap(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            style = chat_style(root)
            for i in range(MAX_CSS_SLOTS):
                style.write_css("", overlay_dir=root, slot=f"s{i}")
            style.write_css(".again{}", overlay_dir=root, slot="s0")      # re-saving one is fine
            with self.assertRaises(ValueError):
                style.write_css("", overlay_dir=root, slot="one-more")

    def test_admin_routes(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi not installed")
        from api.admin_routes import create_admin_router
        from api.server import CoreState
        import core.chat_style as cs

        token = "unit-test-admin-token-123456"
        hdr = {"X-Admin-Token": token}
        with tempfile.TemporaryDirectory() as d:
            saved = cs.CHAT_STYLE
            cs.CHAT_STYLE = chat_style(Path(d))
            try:
                state = CoreState()
                state.config = {"points": {"admin_token": token}}
                app = FastAPI()
                app.include_router(create_admin_router(state))
                with TestClient(app) as client:
                    res = client.put("/api/admin/chat/style", headers=hdr, json={"css": ".x{}", "slot": "money"}).json()
                    self.assertIn("money", res["css_slots"])
                    st = client.get("/api/admin/chat/style?slot=money", headers=hdr).json()
                    self.assertEqual((st["css"], list(st["css_slots"])), (".x{}", ["money"]))
                    self.assertEqual(client.get("/api/admin/chat/style", headers=hdr).json()["css"], "")
                    self.assertEqual(client.delete("/api/admin/overlay-css/chat/money", headers=hdr).json()["css_slots"], {})
                    self.assertEqual(client.delete("/api/admin/overlay-css/chat/money", headers=hdr).status_code, 404)
                    self.assertEqual(client.delete("/api/admin/overlay-css/nope/money", headers=hdr).status_code, 404)
            finally:
                cs.CHAT_STYLE = saved


class TemplatePlaceholders(unittest.TestCase):
    def test_fill(self):
        from core.css_templates import fill_placeholders

        css = ("body { font-size: {font_size}; color: {text_color}; background: {background_color}; }\n"
               ".name { font-size: {{fontSize}}px; font-family: '{{fontName}}'; height: {{emoteSize}}px; }\n"
               ".row { animation: fadeOut 0.5s ease {message_hide_delay} forwards; margin: {{nicknameLeft}}px; }\n"
               ".bubble { background: {{backgroundColor}}; width: {{mysteryWidth}}px; }\n"
               "a{color:red}")
        out, n = fill_placeholders(css)
        self.assertEqual(n, 9)
        self.assertIn("font-size: var(--chat-size, 16px);", out)
        self.assertIn("background: transparent;", out)                 # Streamlabs' widget background
        self.assertIn("background: rgba(0, 0, 0, 0.55);", out)          # StreamElements' bubble colour
        self.assertIn("font-family: 'Roboto'", out)
        self.assertIn("height: var(--chat-emote-size, 28px);", out)
        self.assertIn("ease var(--chat-hide-delay, 86400s) forwards", out)
        self.assertIn("margin: 0px;", out)
        self.assertIn("{{mysteryWidth}}px", out)                        # unknown ones stay
        self.assertTrue(out.endswith("a{color:red}"))

    def test_saved_css_is_filled(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            style = chat_style(root)
            res = style.write_css("#log { font-size: {font_size}; }", overlay_dir=root, slot="sl")
            self.assertEqual(res["placeholders_filled"], 1)
            self.assertEqual(style.read_css(root, slot="sl"), "#log { font-size: var(--chat-size, 16px); }")


class AlertsPage(unittest.TestCase):
    """The page reads every URL option the builder offers, and has the Streamlabs hooks."""

    def test_streamlabs_hooks(self):
        html = (OVERLAY / "alerts.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'id="alert-text-wrap"[^>]*>\s*<div class="alert-kind"[^>]*></div>\s*<div id="alert-text">')
        js = (OVERLAY / "alerts.js").read_text(encoding="utf-8")
        for needle in ('data-token="', '"layout-"', '"platform-"', '"tier-"', '"animated"', '"fadeIn"', '"fadeOut"', '"--alert-in"', '"--letter-anim"',
                       "dataset.kind", "dataset.platform", "dataset.amount", "dataset.currency", '"alerts-css/"'):
            self.assertIn(needle, js)
        css = (OVERLAY / "animate-lite.css").read_text(encoding="utf-8")
        for page in ("alerts.html", "chat.html"):
            self.assertIn("animate-lite.css", (OVERLAY / page).read_text(encoding="utf-8"))
        for name in ("fadeIn", "fadeOut", "fadeInRight", "slideInLeft", "bounceIn", "zoomOut", "flipInX", "rubberBand"):
            self.assertRegex(css, r"@keyframes " + name + r"\b")

    def test_builder_offers_the_filters(self):
        keys = {p["key"] for p in by_id("alerts")["params"]}
        for k in ("platforms", "kinds", "hide", "group", "min", "min_bits", "min_kicks", "tests", "duration",
                  "sound", "volume", "image", "message", "layout", "align", "queue", "css", "tiers", "in", "out"):
            self.assertIn(k, keys)
        kinds = {o[0] for o in next(p for p in by_id("alerts")["params"] if p["key"] == "kinds")["options"]}
        from core.alerts import KINDS
        self.assertEqual(kinds, set(KINDS))
        js = (OVERLAY / "alerts.js").read_text(encoding="utf-8")
        for group in ("money", "subs", "community"):
            self.assertRegex(js, group + r":\s*\[")


class ChatPage(unittest.TestCase):
    def test_every_family_finds_its_names(self):
        html = (OVERLAY / "chat.html").read_text(encoding="utf-8")
        self.assertIn('id="chat_container"', html)
        self.assertIn('id="log"', html)
        js = (OVERLAY / "chat.js").read_text(encoding="utf-8")
        row = re.search(r'row\.className = "([^"]+)"', js).group(1).split()
        self.assertTrue({"msg", "message-row", "chat_line"} <= set(row))
        for cls in ("meta user-box user_info", "name user user-name nick", "message text user-message"):
            self.assertIn(cls, js)
        self.assertIn('"deleted"', js)
        self.assertIn('"chat_removed"', js)
        keys = {p["key"] for p in by_id("chat")["params"]}
        self.assertTrue({"template", "css"} <= keys)


class Rig:
    def __init__(self, cls, config):
        self.bus = EventBus()
        self.removed: list[dict] = []

        async def on_removed(p):
            self.removed.append(p)

        self.bus.on_chat_removed(on_removed)
        self.adapter = cls(config, self.bus, MetricsAggregator({}))


class Removals(unittest.TestCase):
    def test_twitch(self):
        rig = Rig(TwitchAdapter, {"twitch": {"channel": "fridge", "third_party_emotes": False}})
        run(rig.adapter._on_line(None, "@login=amy;room-id=1;target-msg-id=abc-123;tmi-sent-ts=1 "
                                       ":tmi.twitch.tv CLEARMSG #fridge :bad words"))
        run(rig.adapter._on_line(None, "@ban-duration=600;room-id=1;target-user-id=77;tmi-sent-ts=1 "
                                       ":tmi.twitch.tv CLEARCHAT #fridge :spammer"))
        run(rig.adapter._on_line(None, "@room-id=1;tmi-sent-ts=1 :tmi.twitch.tv CLEARCHAT #fridge"))
        self.assertEqual([(r["message_id"], r["user_id"], r["username"], r["all"]) for r in rig.removed],
                         [("abc-123", "", "", False), ("", "77", "spammer", False), ("", "", "", True)])
        self.assertEqual({r["platform"] for r in rig.removed}, {"twitch"})

    def test_kick(self):
        self.assertEqual(kick_removed("App\\Events\\MessageDeletedEvent", {"id": "x", "message": {"id": "m1"}}),
                         {"message_id": "m1"})
        self.assertEqual(kick_removed("App\\Events\\UserBannedEvent", {"user": {"id": 5, "username": "Spam"}}),
                         {"user_id": "5", "username": "Spam"})
        self.assertEqual(kick_removed("App\\Events\\ChatroomClearEvent", {"id": "x"}), {"everything": True})
        self.assertEqual(kick_removed("App\\Events\\MessageDeletedEvent", {}), {})
        rig = Rig(KickAdapter, {"kick": {"channel_slug": "fridge", "chatroom_id": 1, "avatars": False}})
        frame = json.dumps({"event": "App\\Events\\MessageDeletedEvent", "channel": "chatrooms.1.v2",
                            "data": json.dumps({"id": "e", "message": {"id": "m1"}})})
        run(rig.adapter._handle_raw(frame))
        run(rig.adapter._handle_raw(json.dumps({"event": "App\\Events\\MessageDeletedEvent", "data": "{}"})))
        self.assertEqual([(r["platform"], r["message_id"]) for r in rig.removed], [("kick", "m1")])

    def test_youtube(self):
        self.assertEqual(youtube_removed({"markChatItemAsDeletedAction": {"targetItemId": "Ch1"}}), {"message_id": "Ch1"})
        self.assertEqual(youtube_removed({"removeChatItemByAuthorAction": {"externalChannelId": "UCx"}}), {"user_id": "UCx"})
        self.assertEqual(youtube_removed({"addChatItemAction": {}}), {})
        rig = Rig(YouTubeAdapter, {"youtube": {"video_id": "abc"}})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rig.adapter.scout = FieldScout(Path(tmp.name) / "new.jsonl")     # never the real data/ folder
        run(rig.adapter._on_innertube_action({"markChatItemsByAuthorAsDeletedAction": {"externalChannelId": "UCbad"}}))
        self.assertEqual([(r["platform"], r["user_id"]) for r in rig.removed], [("youtube", "UCbad")])

    def test_core_drops_history_and_tells_overlays(self):
        from main import StreamCore

        core = StreamCore({})
        sent: list = []

        class WS:
            async def broadcast(self, payload):
                sent.append(payload)

        core.state.ws_manager = WS()
        line = lambda plat, mid, uid, name: {"platform": plat, "message_id": mid,  # noqa: E731
                                             "user": {"id": uid, "username": name, "display_name": name}}
        core.recent_chat[:] = [line("twitch", "m1", "1", "amy"), line("twitch", "m2", "2", "spam"),
                               line("twitch", "m3", "2", "spam"), line("kick", "m1", "9", "kay")]

        async def go():
            await core._on_chat_removed({"platform": "twitch", "message_id": "m1", "user_id": "", "username": "", "all": False})
            await core._on_chat_removed({"platform": "twitch", "message_id": "", "user_id": "2", "username": "spam", "all": False})

        run(go())
        self.assertEqual([(i["platform"], i["message_id"]) for i in core.recent_chat], [("kick", "m1")])
        self.assertEqual([p["type"] for p in sent], ["chat_removed", "chat_removed"])
        run(core._on_chat_removed({"platform": "kick", "message_id": "", "user_id": "", "username": "", "all": True}))
        self.assertEqual(core.recent_chat, [])


if __name__ == "__main__":
    unittest.main()
