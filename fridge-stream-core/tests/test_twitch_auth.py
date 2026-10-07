"""Twitch sign-in (device code flow, token store, refresh, disconnect), the Helix chatter
picture lookup and the dashboard's /api/admin/twitch/auth endpoints, all against a fake
Twitch. Nothing here touches the network. Run from fridge-stream-core:

    python -m unittest tests.test_twitch_auth -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import adapters.twitch_auth as twitch_auth  # noqa: E402
from adapters.twitch_auth import BUILTIN_CLIENT_ID, SCOPES, TwitchAuth  # noqa: E402
from adapters.twitch_avatars import TwitchAvatars, pictures_from_users  # noqa: E402


class FakeTwitch:
    """Answers id.twitch.tv like the real thing, one scripted step at a time."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self.approved = False           # the streamer typed the code
        self.refresh_ok = True
        self.valid_tokens = {"tok-1"}
        self.n = 0
        self.now = 1_000_000.0

    def clock(self) -> float:
        return self.now

    async def __call__(self, method, url, data, headers):
        self.calls.append((method, url, dict(data or {}), dict(headers or {})))
        if url.endswith("/device"):
            return 200, {"device_code": "dev-1", "user_code": "ABCDEFGH", "expires_in": 1800, "interval": 5,
                         "verification_uri": "https://www.twitch.tv/activate?device-code=ABCDEFGH"}
        if url.endswith("/token"):
            grant = data.get("grant_type")
            if grant == twitch_auth.DEVICE_GRANT:
                if not self.approved:
                    return 400, {"status": 400, "message": "authorization_pending"}
                return 200, {"access_token": "tok-1", "refresh_token": "ref-1", "expires_in": 14400,
                             "scope": SCOPES, "token_type": "bearer"}
            if grant == "refresh_token":
                if not self.refresh_ok:
                    return 400, {"status": 400, "message": "Invalid refresh token"}
                self.n += 1
                tok = f"tok-r{self.n}"
                self.valid_tokens.add(tok)
                return 200, {"access_token": tok, "refresh_token": f"ref-r{self.n}", "expires_in": 14400, "scope": SCOPES}
            if grant == "client_credentials":
                return 200, {"access_token": "app-tok", "expires_in": 5000, "token_type": "bearer"}
        if url.endswith("/validate"):
            tok = (headers or {}).get("Authorization", "").replace("OAuth ", "")
            if tok in self.valid_tokens:
                return 200, {"client_id": BUILTIN_CLIENT_ID, "login": "sensoka", "user_id": "4242",
                             "scopes": SCOPES, "expires_in": 14000}
            return 401, {"status": 401, "message": "invalid access token"}
        if url.endswith("/revoke"):
            return 200, {}
        return 404, {}


def run(coro):
    return asyncio.run(coro)


class DeviceLoginTests(unittest.TestCase):
    def test_sign_in_and_store(self):
        fake = FakeTwitch()

        async def go(path):
            auth = TwitchAuth(path=path, http=fake, clock=fake.clock)
            self.assertFalse(auth.connected)
            self.assertTrue(auth.uses_builtin_app)
            st = await auth.start_login()
            self.assertEqual(st["pending"]["user_code"], "ABCDEFGH")
            self.assertIn("twitch.tv/activate", st["pending"]["verification_uri"])
            self.assertFalse(await auth.poll_once())            # not entered yet
            self.assertFalse(auth.connected)
            fake.approved = True
            self.assertTrue(await auth.poll_once())
            auth.cancel_login()                                  # the background poller is not needed in the test
            self.assertTrue(auth.connected)
            self.assertEqual(auth.login, "sensoka")
            self.assertEqual(auth.user_id, "4242")
            st = await asyncio.sleep(0) or auth.status()
            self.assertIsNone(st["pending"])
            self.assertNotIn("access_token", json.dumps(st))     # the dashboard never sees tokens
            self.assertEqual(await auth.token(), "tok-1")
            # the device request named the built-in app and the scopes
            dev = [c for c in fake.calls if c[1].endswith("/device")][0]
            self.assertEqual(dev[2]["client_id"], BUILTIN_CLIENT_ID)
            self.assertEqual(dev[2]["scopes"], " ".join(SCOPES))
            # persisted, loads back
            again = TwitchAuth(path=path, http=fake, clock=fake.clock)
            self.assertTrue(again.connected)
            self.assertEqual(again.login, "sensoka")

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_token.json"))

    def test_refresh_before_expiry_and_hourly_validate(self):
        fake = FakeTwitch()

        async def go(path):
            auth = TwitchAuth(path=path, http=fake, clock=fake.clock)
            await auth.start_login()
            fake.approved = True
            await auth.poll_once()
            auth.cancel_login()
            calls_before = len(fake.calls)
            self.assertEqual(await auth.token(), "tok-1")
            self.assertEqual(len(fake.calls), calls_before)      # fresh: no network
            fake.now += 2 * 3600
            await auth.token()
            self.assertTrue(fake.calls[-1][1].endswith("/validate"))   # hourly check
            fake.now += 14400                                     # past expiry
            self.assertEqual(await auth.token(), "tok-r1")        # refreshed
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["refresh_token"], "ref-r1")    # the new refresh token is kept
            # Twitch answered 401 somewhere else: next use refreshes
            auth.invalidate()
            self.assertEqual(await auth.token(), "tok-r2")

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_token.json"))

    def test_dead_refresh_token_means_sign_in_again(self):
        fake = FakeTwitch()

        async def go(path):
            auth = TwitchAuth(path=path, http=fake, clock=fake.clock)
            await auth.start_login()
            fake.approved = True
            await auth.poll_once()
            auth.cancel_login()
            fake.refresh_ok = False
            fake.now += 30 * 3600
            self.assertIsNone(await auth.token())
            self.assertFalse(auth.connected)
            self.assertIn("Connect Twitch", auth.status()["error"])
            self.assertFalse(path.exists())                       # file gone with the sign-in

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_token.json"))

    def test_disconnect_revokes_and_deletes(self):
        fake = FakeTwitch()

        async def go(path):
            auth = TwitchAuth(path=path, http=fake, clock=fake.clock)
            await auth.start_login()
            fake.approved = True
            await auth.poll_once()
            auth.cancel_login()
            self.assertTrue(path.exists())
            await auth.disconnect()
            self.assertFalse(auth.connected)
            self.assertFalse(path.exists())
            revoke = [c for c in fake.calls if c[1].endswith("/revoke")]
            self.assertEqual(len(revoke), 1)
            self.assertEqual(revoke[0][2]["token"], "tok-1")
            self.assertIsNone(await auth.token())

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_token.json"))

    def test_expired_code_and_cancel(self):
        fake = FakeTwitch()

        async def go(path):
            auth = TwitchAuth(path=path, http=fake, clock=fake.clock)
            await auth.start_login()
            fake.now += 1801
            self.assertTrue(await auth.poll_once())
            auth.cancel_login()
            self.assertIn("expired", auth.status()["error"])
            self.assertIsNone(auth.status()["pending"])
            await auth.start_login()
            auth.cancel_login()
            self.assertIsNone(auth.status()["pending"])

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_token.json"))

    def test_own_app_with_secret_falls_back_to_app_token(self):
        fake = FakeTwitch()

        async def go(path):
            auth = TwitchAuth(client_id="my-app", client_secret="s3cret", path=path, http=fake, clock=fake.clock)
            self.assertFalse(auth.uses_builtin_app)
            self.assertEqual(auth.client_id, "my-app")
            self.assertEqual(await auth.token(), "app-tok")
            self.assertEqual(await auth.token(), "app-tok")       # cached
            self.assertEqual(len([c for c in fake.calls if c[2].get("grant_type") == "client_credentials"]), 1)
            self.assertTrue(auth.status()["has_secret"])
            self.assertFalse(auth.connected)

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_token.json"))

    def test_changing_the_app_drops_the_old_sign_in(self):
        fake = FakeTwitch()

        async def go(path):
            auth = TwitchAuth(path=path, http=fake, clock=fake.clock)
            await auth.start_login()
            fake.approved = True
            await auth.poll_once()
            auth.cancel_login()
            auth.configure("other-app", "")
            self.assertFalse(auth.connected)
            self.assertFalse(path.exists())

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_token.json"))

    def test_get_auth_is_shared_and_follows_config(self):
        twitch_auth._shared = None
        try:
            a = twitch_auth.get_auth({"twitch": {}})
            b = twitch_auth.get_auth({"twitch": {"client_id": "x"}})
            self.assertIs(a, b)
            self.assertEqual(b.client_id, "x")
            twitch_auth.get_auth({"twitch": {"client_id": ""}})
            self.assertEqual(b.client_id, BUILTIN_CLIENT_ID)
        finally:
            twitch_auth._shared = None


class HelixAvatarTests(unittest.TestCase):
    def test_pictures_from_users(self):
        data = {"data": [{"id": "1", "login": "a", "profile_image_url": "https://p/a.png"},
                         {"id": "2", "login": "b", "profile_image_url": ""}]}
        self.assertEqual(pictures_from_users(data), {"1": "https://p/a.png", "2": ""})
        self.assertEqual(pictures_from_users({}), {})

    def test_batches_and_caches(self):
        calls: list[list[str]] = []
        found: list[tuple[str, str]] = []

        async def fetch(ids):
            calls.append(list(ids))
            return 200, {i: f"https://p/{i}.png" for i in ids if i != "3"}

        def cb(i):
            async def _found(url):
                found.append((i, url))
            return _found

        async def go(path):
            a = TwitchAvatars(fetcher=fetch, path=path, batch_delay=0.02)
            for i in ("1", "2", "3"):
                self.assertIsNone(a.get(i))
                a.request(i, cb(i))
            a.request("1", cb("1"))                 # already queued
            a.request("not-an-id", cb("x"))         # ignored: Twitch ids are digits
            await asyncio.sleep(0.1)
            self.assertEqual(calls, [["1", "2", "3"]])            # one request for all three
            self.assertEqual(a.get("1"), "https://p/1.png")
            self.assertEqual(a.get("3"), "")                        # answered: no picture
            a.request("2", cb("2"))                                 # cached: no new request
            await asyncio.sleep(0.05)
            self.assertEqual(len(calls), 1)
            a.stop()
            b = TwitchAvatars(fetcher=fetch, path=path)             # persisted
            self.assertEqual(b.get("2"), "https://p/2.png")

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_avatars.json"))
        self.assertEqual(sorted(found), [("1", "https://p/1.png"), ("2", "https://p/2.png")])

    def test_unauthorized_refreshes_once_then_retries(self):
        class Auth:
            connected = True
            client_id = "x"
            invalidated = 0

            def invalidate(self):
                self.invalidated += 1

        auth = Auth()
        calls = []

        async def fetch(ids):
            calls.append(list(ids))
            return (401, {}) if len(calls) == 1 else (200, {"7": "https://p/7.png"})

        async def go(path):
            a = TwitchAvatars(fetcher=fetch, path=path, auth=auth, batch_delay=0.01)
            got = []

            async def _found(url):
                got.append(url)

            a.request("7", _found)
            await asyncio.sleep(0.08)
            self.assertEqual(len(calls), 2)
            self.assertEqual(auth.invalidated, 1)
            self.assertEqual(got, ["https://p/7.png"])

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_avatars.json"))

    def test_failures_are_not_hammered(self):
        calls = []

        async def fetch(ids):
            calls.append(list(ids))
            return 500, {}

        async def go(path):
            a = TwitchAvatars(fetcher=fetch, path=path, batch_delay=0.01)

            async def _found(url):
                raise AssertionError("no picture expected")

            a.request("5", _found)
            await asyncio.sleep(0.05)
            a.request("5", _found)
            await asyncio.sleep(0.05)
            self.assertEqual(len(calls), 1)
            self.assertIsNone(a.get("5"))

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_avatars.json"))

    def test_disabled_or_no_token(self):
        async def go(path):
            a = TwitchAvatars(enabled=False, path=path)

            async def _found(url):
                raise AssertionError("should not fetch")

            a.request("9", _found)
            await asyncio.sleep(0.01)
            self.assertIsNone(a.get("9"))
            # no auth at all: the real fetcher answers "no token" without touching the network
            b = TwitchAvatars(path=path)
            self.assertEqual(await b._fetch_http(["9"]), (0, {}))

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "twitch_avatars.json"))


class AdminRouteTests(unittest.TestCase):
    """The dashboard endpoints, through FastAPI's test client, with a fake Twitch behind them."""

    TOKEN = "unit-test-admin-token-123456"

    def test_connect_status_disconnect(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.admin_routes import create_admin_router
        from api.server import CoreState

        fake = FakeTwitch()
        with tempfile.TemporaryDirectory() as d:
            twitch_auth._shared = TwitchAuth(path=Path(d) / "twitch_token.json", http=fake, clock=fake.clock)
            try:
                state = CoreState()
                state.config = {"points": {"admin_token": self.TOKEN}, "twitch": {}}
                app = FastAPI()
                app.include_router(create_admin_router(state))
                hdr = {"X-Admin-Token": self.TOKEN}
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/admin/twitch/auth").status_code, 401)   # token required
                    st = client.get("/api/admin/twitch/auth", headers=hdr).json()
                    self.assertFalse(st["connected"])
                    st = client.post("/api/admin/twitch/auth/start", headers=hdr).json()
                    self.assertEqual(st["pending"]["user_code"], "ABCDEFGH")
                    self.assertNotIn("device_code", json.dumps(st))
                    st = client.post("/api/admin/twitch/auth/cancel", headers=hdr).json()
                    self.assertIsNone(st["pending"])
                    # sign in for real (the fake approves at once) and check Disconnect
                    fake.approved = True
                    client.post("/api/admin/twitch/auth/start", headers=hdr)
                    run(twitch_auth._shared.poll_once())
                    twitch_auth._shared.cancel_login()
                    st = client.get("/api/admin/twitch/auth", headers=hdr).json()
                    self.assertTrue(st["connected"])
                    self.assertEqual(st["login"], "sensoka")
                    st = client.post("/api/admin/twitch/auth/disconnect", headers=hdr).json()
                    self.assertFalse(st["connected"])
            finally:
                twitch_auth._shared = None


if __name__ == "__main__":
    unittest.main()
