"""Chat platforms keep trying when they can't connect, and say why.

    python -m pytest tests/test_adapter_retry.py -q
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters import kick as kick_mod  # noqa: E402
from adapters import twitch as twitch_mod  # noqa: E402
from adapters import youtube as yt_mod  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.metrics import MetricsAggregator  # noqa: E402


def _cfg(**sections):
    return {"core": {}, **sections}


async def _until(cond, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if cond():
            return True
        await asyncio.sleep(0.01)
    return False


class IrcLineReaderTests(unittest.TestCase):
    def test_emoji_split_across_reads_is_kept(self):
        line = "@id=1 :bob!bob@bob.tmi.twitch.tv PRIVMSG #chan :hi \U0001F600 there\r\n".encode("utf-8")
        cut = line.index("\U0001F600".encode("utf-8")) + 2  # inside the 4-byte emoji
        reader = twitch_mod.IrcLineReader()
        self.assertEqual(reader.feed(line[:cut]), [])
        out = reader.feed(line[cut:])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].endswith("hi \U0001F600 there"))

    def test_several_lines_and_a_partial_one(self):
        reader = twitch_mod.IrcLineReader()
        self.assertEqual(reader.feed(b"PING :a\r\nPING :b\r\nPI"), ["PING :a", "PING :b"])
        self.assertEqual(reader.feed(b"NG :c\r\n"), ["PING :c"])


class TwitchSilentLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_silent_link_pings_then_reconnects(self):
        received = []

        async def handle(reader, writer):
            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    received.append(data)  # never answers: a dead link
            except Exception:
                pass
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        with mock.patch.object(twitch_mod, "HOST", "127.0.0.1"), \
                mock.patch.object(twitch_mod, "PORT", port), \
                mock.patch.object(twitch_mod, "IDLE_PING", 0.1), \
                mock.patch.object(twitch_mod, "PONG_TIMEOUT", 0.1):
            ad = twitch_mod.TwitchAdapter(_cfg(twitch={"channel": "fridge", "avatars": False,
                                                       "third_party_emotes": False}),
                                          EventBus(), MetricsAggregator({}))
            await ad.start()
            try:
                self.assertTrue(await _until(lambda: any(b"PING :keepalive" in d for d in received)))
                self.assertTrue(await _until(lambda: ad.state == "retrying"))
                self.assertIn("silent", ad.last_error)
            finally:
                await ad.stop()
                server.close()
                await server.wait_closed()
        self.assertEqual(ad.state, "stopped")


class YouTubeRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_not_live_yet_retries_until_chat_opens(self):
        ad = yt_mod.YouTubeAdapter(_cfg(youtube={"video_id": "abcdefghijk"}), EventBus(), MetricsAggregator({}))
        answers = [("", "", "v"), ("key", "cont", "v")]
        polls = []

        async def boot(client):
            return answers.pop(0) if answers else ("key", "cont", "v")

        async def poll(client, key, cont, ver):
            polls.append(cont)
            await asyncio.sleep(0.05)
            return cont, 2.0

        with mock.patch.object(yt_mod, "RETRY_FIRST", 0.05), \
                mock.patch.object(ad, "_bootstrap_innertube", boot), \
                mock.patch.object(ad, "_poll_innertube", poll):
            await ad.start()
            try:
                self.assertTrue(await _until(lambda: ad.state == "retrying"))
                self.assertIn("not live yet", ad.last_error)
                self.assertTrue(ad._running)
                self.assertTrue(await _until(lambda: ad.state == "connected" and polls))
                self.assertEqual(ad.last_error, "")
            finally:
                await ad.stop()

    async def test_missing_video_says_why(self):
        ad = yt_mod.YouTubeAdapter(_cfg(youtube={}), EventBus(), MetricsAggregator({}))
        await ad.start()
        self.assertFalse(ad._running)
        self.assertIn("No YouTube live video", ad.last_error)


class KickRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_failure_at_start_keeps_retrying(self):
        ad = kick_mod.KickAdapter(_cfg(kick={"channel_slug": "fridge", "avatars": False}),
                                  EventBus(), MetricsAggregator({}))
        answers = [None, None, 4242]
        connected = asyncio.Event()

        async def resolve(slug):
            cid = answers.pop(0) if answers else 4242
            if cid is None:
                ad._lookup_error = "Kick blocked the lookup (403)"
            return cid

        async def ws_loop():
            connected.set()
            await asyncio.sleep(3600)

        async def no_viewers():
            return None

        with mock.patch.object(kick_mod, "LOOKUP_RETRY_FIRST", 0.05), \
                mock.patch.object(ad, "_resolve_chatroom_id", resolve), \
                mock.patch.object(ad, "_persist_chatroom_id", lambda cid: None), \
                mock.patch.object(ad, "_poll_viewers", no_viewers), \
                mock.patch.object(ad, "_ws_loop", ws_loop):
            await ad.start()
            try:
                self.assertTrue(ad._running)
                self.assertEqual(ad.state, "retrying")
                self.assertIn("403", ad.last_error)
                await asyncio.wait_for(connected.wait(), 3)
                self.assertEqual(ad.chatroom_id, 4242)
            finally:
                await ad.stop()

    def test_bad_chatroom_id_in_config_is_ignored(self):
        ad = kick_mod.KickAdapter(_cfg(kick={"channel_slug": "fridge", "chatroom_id": "abc"}),
                                  EventBus(), MetricsAggregator({}))
        self.assertIsNone(ad.chatroom_id)


if __name__ == "__main__":
    unittest.main()
