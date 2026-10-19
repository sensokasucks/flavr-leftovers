"""Paid list (core/paid.py) and the YouTube paid items it needs: Super Stickers, Jewels
gifts, Super Chat amounts. Gift shapes copied from real captures (data/youtube_new_fields.jsonl,
2026-10-08 / 09), names and ids made up. Run from fridge-stream-core:

    python -m unittest tests.test_paid -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.youtube import YouTubeAdapter  # noqa: E402
from adapters.youtube_capture import FieldScout  # noqa: E402
from core.alerts import build_alert  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.paid import PaidLog, parse_money, split_amount_prefix  # noqa: E402
from core.store import Store  # noqa: E402

STAR = "//www.gstatic.com/youtube/img/pdg/gift/assets/silver_star_v2_320x320.png"


def run(coro):
    return asyncio.run(coro)


def jewels_item(mid="Chw1", who="@quiet_otter", gift="Star") -> dict:
    return {"addChatItemAction": {"item": {"giftMessageViewModel": {
        "text": {"content": f"sent {gift}", "styleRuns": [{"startIndex": 0, "length": 9}]},
        "authorName": {"content": who + " ", "styleRuns": [{"startIndex": 0, "length": 13}]},
        "id": mid,
        "authorAvatar": {"avatarViewModel": {"image": {"sources": [
            {"url": "https://yt4.ggpht.com/ytc/abc=s32-c-k-c0x00ffffff-no-rj", "width": 32, "height": 32},
            {"url": "https://yt4.ggpht.com/ytc/abc=s64-c-k-c0x00ffffff-no-rj", "width": 64, "height": 64}]}}},
        "giftImage": {"sources": [{"url": STAR + "=w480-h480", "width": 480, "height": 480},
                                  {"url": STAR + "=w640-h640", "width": 640, "height": 640}]},
        "giftImageA11yLabel": f"{who} sent a gift, {gift}",
        "rendererContext": {},
    }}}}


def gift_widget(who="@quiet_otter", channel="UCotter") -> dict:
    return {"clickTrackingParams": "x", "updateOrAddInteractivityWidgetAction": {"widgetRenderer": {
        "interactivityWidgetRenderer": {
            "id": "UgxLiveChatId", "type": "INTERACTIVITY_WIDGET_TYPE_GIFT", "priority": 0,
            "content": {"giftA11yLabel": f"{who} sent a gift, Image of a star",
                        "elementRenderer": {"compatibilityOptions": {
                            "liveChatId": "UgxLiveChatId", "liveChatAuthorExternalChannelId": channel}}}}}}}


def sticker_item(mid="st1", who="@sticker_fan", amount="$2.00", label="Dancing cat") -> dict:
    return {"addChatItemAction": {"item": {"liveChatPaidStickerRenderer": {
        "id": mid, "authorName": {"simpleText": who}, "authorExternalChannelId": "UC" + who,
        "purchaseAmountText": {"simpleText": amount},
        "sticker": {"thumbnails": [{"url": "//lh3.googleusercontent.com/cat=s40", "width": 40},
                                   {"url": "//lh3.googleusercontent.com/cat=s176", "width": 176}],
                    "accessibility": {"accessibilityData": {"label": label}}},
        "moneyChipBackgroundColor": 1, "stickerDisplayWidth": 88, "stickerDisplayHeight": 88,
    }}}}


def superchat_item(mid="sc1", who="@big_fan", amount="€2,50", text="love the stream") -> dict:
    return {"addChatItemAction": {"item": {"liveChatPaidMessageRenderer": {
        "id": mid, "authorName": {"simpleText": who}, "authorExternalChannelId": "UC" + who,
        "purchaseAmountText": {"simpleText": amount}, "message": {"runs": [{"text": text}]}}}}}


class Money(unittest.TestCase):
    def test_amounts(self):
        """Super Chat amount texts in many currencies parse to (amount, currency code)."""
        cases = {
            "$5.00": (5.0, "USD"), "CA$10.00": (10.0, "CAD"), "€2,50": (2.5, "EUR"), "1.000,50 €": (1000.5, "EUR"),
            "₹1,000.00": (1000.0, "INR"), "¥500": (500.0, "JPY"), "PHP 100.00": (100.0, "PHP"),
            "R$10,00": (10.0, "BRL"), "A$2.00": (2.0, "AUD"), "$1,000": (1000.0, "USD"), "£3.99": (3.99, "GBP"),
        }
        for text, want in cases.items():
            self.assertEqual(parse_money(text), want, text)
        self.assertEqual(parse_money(""), (None, ""))
        self.assertEqual(parse_money("free"), (None, ""))

    def test_prefix(self):
        """A "[$5.00] " amount prefix is split off the message."""
        self.assertEqual(split_amount_prefix("[$5.00] hello"), ("hello", "$5.00"))
        self.assertEqual(split_amount_prefix("[nope"), ("[nope", ""))


class YouTubePaid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "new.jsonl"
        bus = EventBus()
        self.chat: list = []

        async def on_chat(e):
            self.chat.append(e)

        bus.on_chat(on_chat)
        self.yt = YouTubeAdapter({"youtube": {"video_id": "abc"}}, bus, MetricsAggregator({}))
        self.yt.scout = FieldScout(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_super_sticker_is_shown_with_its_picture(self):
        run(self.yt._on_innertube_action(sticker_item()))
        e = self.chat[0]
        self.assertTrue(e.is_paid)
        self.assertEqual((e.paid_kind, e.paid_amount, e.paid_currency, e.paid_label), ("supersticker", 2.0, "USD", "Dancing cat"))
        self.assertEqual(e.message, "[$2.00] :Dancing cat:")
        em = e.emotes[0]
        self.assertEqual(e.message[em["start"]:em["end"] + 1], ":Dancing cat:")
        self.assertEqual(em["url"], "https://lh3.googleusercontent.com/cat=s176")   # biggest, https
        self.assertTrue(em["sticker"])
        self.assertFalse(self.path.exists())                                         # known data, quiet

    def test_super_chat_amount_is_a_number(self):
        run(self.yt._on_innertube_action(superchat_item()))
        e = self.chat[0]
        self.assertEqual((e.paid_kind, e.paid_amount, e.paid_currency), ("superchat", 2.5, "EUR"))
        self.assertEqual(e.message, "[€2,50] love the stream")

    def test_jewels_gift_with_sender_from_the_animation(self):
        run(self.yt._on_innertube_action(gift_widget()))
        run(self.yt._on_innertube_action(jewels_item()))
        run(self.yt._on_innertube_action(jewels_item()))          # same id again: once
        self.assertEqual(len(self.chat), 1)
        e = self.chat[0]
        self.assertEqual((e.paid_kind, e.paid_label, e.is_paid, e.paid_amount), ("jewels", "Star", True, None))
        self.assertEqual(e.user.id, "UCotter")
        self.assertEqual(e.user.display_name, "@quiet_otter")
        self.assertEqual(e.message, "sent Star :Star:")
        self.assertEqual(e.paid_image, "https:" + STAR + "=w640-h640")
        em = e.emotes[0]
        self.assertEqual(e.message[em["start"]:em["end"] + 1], ":Star:")
        self.assertTrue(e.user.profile_image_url.startswith("https://yt4.ggpht.com/"))
        self.assertFalse(self.path.exists())

    def test_jewels_gift_without_animation_uses_the_name(self):
        run(self.yt._on_innertube_action(jewels_item(mid="g2", who="@someone", gift="Go team!")))
        e = self.chat[0]
        self.assertEqual((e.user.id, e.paid_label), ("@someone", "Go team!"))

    def test_official_super_chat_and_sticker(self):
        run(self.yt._on_official_item({"id": "o1", "snippet": {
            "type": "superChatEvent", "displayMessage": "$5.00 from Amy: hi",
            "superChatDetails": {"amountMicros": "5000000", "currency": "USD", "amountDisplayString": "$5.00",
                                 "userComment": "hi"}},
            "authorDetails": {"displayName": "Amy", "channelId": "UCamy"}}))
        run(self.yt._on_official_item({"id": "o2", "snippet": {
            "type": "superStickerEvent", "displayMessage": "",
            "superStickerDetails": {"amountMicros": "1990000", "currency": "USD", "amountDisplayString": "$1.99",
                                    "superStickerMetadata": {"stickerId": "x", "altText": "Waving hand"}}},
            "authorDetails": {"displayName": "Bo", "channelId": "UCbo"}}))
        sc, st = self.chat
        self.assertEqual((sc.paid_kind, sc.paid_amount, sc.message), ("superchat", 5.0, "hi"))
        self.assertEqual((st.paid_kind, st.paid_amount, st.message), ("supersticker", 1.99, "Super Sticker: Waving hand"))


class Alerts(unittest.TestCase):
    def test_new_kinds(self):
        a = build_alert(kind="jewels", username="otter", item="Star", platform="youtube")
        self.assertEqual((a["headline"], a["falls_back"]), ("otter sent Star!", "superchat"))
        self.assertIn("gift-alert", a["css_classes"])
        s = build_alert(kind="supersticker", username="cat", amount=2, currency="USD", image="https://x/cat.png")
        self.assertEqual((s["headline"], s["image"]), ("cat sent a Super Sticker (2.00 USD)!", "https://x/cat.png"))
        k = build_alert(kind="kicks", username="tipper", amount=100, currency="KICKs")
        self.assertEqual(k["headline"], "tipper sent 100 KICKs!")
        # an amount Core can't read as a number shows the platform's own text, never a made-up one
        u = build_alert(kind="superchat", username="x", amount_text="₦500.00")
        self.assertEqual(u["amount_fmt"], "₦500.00")


class List(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.paid = PaidLog(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, **kw):
        return run(self.paid.add(**kw))

    def fill(self):
        now = time.time()
        self.add(platform="youtube", kind="superchat", username="amy", message="hi", amount=5, currency="USD",
                 amount_text="$5.00", message_id="m1", when=now - 300)
        self.add(platform="twitch", kind="bits", username="bo", message="cheer100 gg", amount=100, currency="bits",
                 message_id="m2", when=now - 200)
        self.add(platform="kick", kind="kicks", username="cy", amount=50, currency="KICKs", when=now - 100)
        self.add(platform="youtube", kind="jewels", username="di", item="Star", message_id="m3", when=now - 50)
        self.add(platform="twitch", kind="subscribe", username="ed", when=now - 10)

    def test_add_and_no_duplicates(self):
        self.assertIsNotNone(self.add(platform="youtube", kind="superchat", username="amy", message_id="x1"))
        self.assertIsNone(self.add(platform="youtube", kind="superchat", username="amy", message_id="x1"))
        self.assertIsNotNone(self.add(platform="twitch", kind="superchat", username="amy", message_id="x1"))
        self.assertEqual(run(self.paid.list({"status": "all"}))["total"], 2)

    def test_filters_totals_and_ticks(self):
        self.fill()
        money = run(self.paid.list({"group": "money"}))
        self.assertEqual([r["username"] for r in money["rows"]], ["amy", "bo", "cy", "di"])   # oldest first
        self.assertEqual(money["unticked"], 4)                                                 # subs don't count
        totals = {t.get("currency") or t.get("kind"): t for t in money["totals"]}
        self.assertEqual(totals["USD"]["amount"], 5)
        self.assertEqual(totals["bits"]["amount"], 100)
        self.assertEqual(totals["jewels"]["count"], 1)
        self.assertEqual([r["username"] for r in run(self.paid.list({"group": "subs"}))["rows"]], ["ed"])
        self.assertEqual(len(run(self.paid.list({"group": "all"}))["rows"]), 5)
        self.assertEqual([r["username"] for r in run(self.paid.list({"platforms": "kick,twitch", "group": "money"}))["rows"]],
                         ["bo", "cy"])
        self.assertEqual([r["username"] for r in run(self.paid.list({"min": 60}))["rows"]], ["bo"])
        self.assertEqual([r["username"] for r in run(self.paid.list({"kinds": "jewels,kicks"}))["rows"]], ["cy", "di"])
        self.assertEqual([r["username"] for r in run(self.paid.list({"q": "gg"}))["rows"]], ["bo"])
        self.assertEqual([r["username"] for r in run(self.paid.list({"has_message": "yes"}))["rows"]], ["amy", "bo"])
        self.assertEqual(run(self.paid.list({"sort": "biggest"}))["rows"][0]["username"], "bo")
        self.assertEqual(run(self.paid.list({"since": time.time() - 150, "group": "money"}))["total"], 2)

        amy = money["rows"][0]["id"]
        self.assertEqual(run(self.paid.tick([amy])), 1)
        self.assertEqual([r["username"] for r in run(self.paid.list({"group": "money"}))["rows"]], ["bo", "cy", "di"])
        self.assertEqual([r["username"] for r in run(self.paid.list({"status": "done"}))["rows"]], ["amy"])
        self.assertEqual(run(self.paid.tick_matching({"platforms": "twitch"})), 2)    # bo + ed
        self.assertEqual(run(self.paid.unticked()), 2)
        self.assertEqual(run(self.paid.tick([amy], done=False)), 1)
        self.assertEqual(run(self.paid.unticked()), 3)

    def test_delete_only_ticked(self):
        self.fill()
        run(self.paid.tick_matching({"group": "all"}))
        run(self.paid.tick([1], done=False))
        self.assertEqual(run(self.paid.delete_ticked(0)), 4)
        self.assertEqual(run(self.paid.list({"status": "all", "group": "all"}))["total"], 1)

    def test_csv_is_safe_for_spreadsheets(self):
        self.add(platform="youtube", kind="superchat", username="x", message="=HYPERLINK(\"http://bad\")",
                 amount=1, currency="USD")
        text = run(self.paid.export_csv({"status": "all"}))
        self.assertIn("'=HYPERLINK", text)
        self.assertTrue(text.startswith("time,platform,type,name,amount"))


class CoreRecordsPaid(unittest.TestCase):
    """Core puts paid chat, power-ups and platform subs / tips on the list; tests never."""

    def test_core(self):
        """Core lists paid chat and paid alerts; a red-flagged chatter's money is listed, marked, never alerted."""
        from main import StreamCore
        from core.red_flags import RedFlags

        core = StreamCore({})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        core.store = Store(Path(tmp.name) / "t.db")
        core.red_flags = RedFlags(core.store, {})
        core.state.config = {"red_flags": {"phrases": ["buy viewers"]},
                             "points": {"enabled": True, "jewels_points": 40}}
        sent: list = []

        class WS:
            async def broadcast(self, payload):
                sent.append(payload)

            def push_roster(self, fn):
                pass

        core.state.ws_manager = WS()
        core.bus.on_alert(core._on_alert)      # (start() does this in a running Core)

        def chat(name, text, **kw):
            plat = kw.pop("platform", Platform.YOUTUBE)
            return ChatEvent(platform=plat, user=ChatUser(platform=plat, id="UC" + name, username=name),
                             message=text, **kw)

        async def go():
            await core._on_chat(chat("amy", "[$5.00] hi", is_paid=True, paid_amount=5.0, paid_currency="USD",
                                     paid_kind="superchat", message_id="s1"))
            await core._on_chat(chat("cat", "[$2.00] :Dancing cat:", is_paid=True, paid_amount=2.0,
                                     paid_currency="USD", paid_kind="supersticker", paid_label="Dancing cat",
                                     paid_image="https://x/cat.png", message_id="s2"))
            await core._on_chat(chat("otter", "sent Star :Star:", is_paid=True, paid_kind="jewels",
                                     paid_label="Star", paid_image="https://x/star.png", message_id="s3"))
            await core._on_chat(chat("bo", "hello", platform=Platform.TWITCH, highlight="gigantified"))
            await core._on_chat(chat("hi", "just chatting", platform=Platform.TWITCH, highlight="highlighted"))
            await core._on_alert({**build_alert(kind="subscribe", username="ed", platform="twitch"),
                                  "source": "platform"})
            await core._on_alert({**build_alert(kind="member_gift", username="gus", platform="youtube", qty=3),
                                  "source": "platform"})
            await core._on_alert({**build_alert(kind="kicks", username="cy", platform="kick", amount=50,
                                                currency="KICKs"), "source": "platform"})
            await core._on_alert(build_alert(kind="superchat", username="test", is_test=True))
            # a red-flagged chatter's money is still listed (and marked), never shown
            await core._on_chat(chat("spam", "buy viewers cheap", platform=Platform.TWITCH))
            await core._on_chat(chat("spam", "cheer500", platform=Platform.TWITCH, is_paid=True, paid_amount=500.0,
                                     paid_currency="bits", paid_kind="bits", message_id="b9"))

        run(go())
        rows = run(core.paid.list({"group": "all"}))["rows"]
        got = [(r["username"], r["kind"], r["amount"], r["item"], r["message"], r["flagged"]) for r in rows]
        self.assertEqual(got, [
            ("amy", "superchat", 5.0, "", "hi", False),
            ("cat", "supersticker", 2.0, "Dancing cat", "", False),
            ("otter", "jewels", None, "Star", "", False),
            ("bo", "powerup", None, "Gigantified emote", "hello", False),
            ("ed", "subscribe", None, "", "", False),
            ("gus", "member_gift", None, "", "", False),
            ("cy", "kicks", 50.0, "", "", False),
            ("spam", "bits", 500.0, "", "cheer500", True),
        ])
        self.assertEqual(rows[1]["amount_text"], "$2.00")
        self.assertEqual(rows[1]["image_url"], "https://x/cat.png")
        # the alerts Core fired for the paid chat (not the flagged one)
        alerts = [p["data"] for p in sent if p["type"] == "alert"]
        kinds = [(a["kind"], a.get("source")) for a in alerts]
        self.assertIn(("supersticker", "chat"), kinds)
        self.assertIn(("jewels", "chat"), kinds)
        sticker = next(a for a in alerts if a["kind"] == "supersticker")
        self.assertEqual((sticker["image"], sticker["amount_fmt"], sticker["message"]), ("https://x/cat.png", "2.00 USD", ""))
        self.assertFalse([a for a in alerts if a["username"] == "spam"])
        # a YouTube gift pays points.jewels_points to its sender (set to 40 here; default 0)
        self.assertEqual(next(a for a in alerts if a["kind"] == "jewels").get("points_awarded"), 40)
        self.assertEqual(rows[5]["qty"], 3)


if __name__ == "__main__":
    unittest.main()
