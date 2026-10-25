"""Kick sign-in (the streamer's own Kick app: OAuth code + PKCE, token store, refresh,
posting into chat, disconnect), the dashboard's /api/admin/kick/auth endpoints and the
/kick/callback page, all against a fake Kick. Nothing here touches the network. Run from
fridge-stream-core:

    python -m unittest tests.test_kick_auth -v
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import adapters.kick_auth as kick_auth  # noqa: E402
from adapters.kick_auth import SCOPES, KickAuth, redirect_uri  # noqa: E402


class FakeKick:
    """Answers id.kick.com and api.kick.com like the real thing, one scripted step at a time."""

    def __init__(self):
        self.calls: list[dict] = []
        self.refresh_ok = True
        self.chat_status = 200
        self.valid_tokens = {"tok-1"}
        self.n = 0
        self.now = 1_000_000.0
        self.challenge = ""     # from the authorize address, checked against the verifier

    def clock(self) -> float:
        return self.now

    async def request(self, method, url, *, form=None, json_body=None, params=None, headers=None):
        self.calls.append({"method": method, "url": url, "form": dict(form or {}), "json": json_body,
                           "params": dict(params or {}), "headers": dict(headers or {})})
        bearer = (headers or {}).get("Authorization", "").replace("Bearer ", "")
        if url == kick_auth.TOKEN_URL:
            grant = form.get("grant_type")
            if not form.get("client_secret"):
                return 400, {"error": "invalid_client"}
            if grant == "authorization_code":
                digest = hashlib.sha256(form["code_verifier"].encode()).digest()
                if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != self.challenge:
                    return 400, {"error": "invalid_grant", "error_description": "PKCE mismatch"}
                if form.get("code") != "code-1":
                    return 400, {"error": "invalid_grant"}
                return 200, {"access_token": "tok-1", "refresh_token": "ref-1", "expires_in": "7200",
                             "scope": " ".join(SCOPES), "token_type": "Bearer"}
            if grant == "refresh_token":
                if not self.refresh_ok:
                    return 400, {"error": "invalid_grant"}
                self.n += 1
                tok = f"tok-r{self.n}"
                self.valid_tokens.add(tok)
                return 200, {"access_token": tok, "refresh_token": f"ref-r{self.n}", "expires_in": 7200,
                             "scope": " ".join(SCOPES)}
        if url == kick_auth.USERS_URL:
            if bearer in self.valid_tokens:
                return 200, {"data": [{"user_id": 2460000, "name": "sensoka-FlaVR"}], "message": "OK"}
            return 401, {"message": "Unauthorized"}
        if url == kick_auth.CHAT_URL:
            if bearer not in self.valid_tokens:
                return 401, {"message": "Unauthorized"}
            if self.chat_status != 200:
                return self.chat_status, {"message": "Forbidden"}
            return 200, {"data": {"is_sent": True, "message_id": "m-1"}, "message": "OK"}
        if url == kick_auth.REVOKE_URL:
            return 200, {}
        return 404, {}


def run(coro):
    return asyncio.run(coro)


def _state_and_challenge(fake: FakeKick, status: dict) -> str:
    """Read state + code_challenge out of the authorize address, as Kick would."""
    q = parse_qs(urlsplit(status["pending"]["authorize_url"]).query)
    fake.challenge = q["code_challenge"][0]
    return q["state"][0]


async def _signed_in(fake: FakeKick, path: Path) -> KickAuth:
    auth = KickAuth("my-app", "s3cret", path=path, http=fake, clock=fake.clock)
    state = _state_and_challenge(fake, auth.start_login())
    ok, _ = await auth.finish_login(code="code-1", state=state)
    assert ok
    return auth


class SignInTests(unittest.TestCase):
    def test_needs_own_app_first(self):
        with tempfile.TemporaryDirectory() as d:
            auth = KickAuth(path=Path(d) / "kick_token.json", http=FakeKick())
            st = auth.start_login()
            self.assertIsNone(st["pending"])
            self.assertFalse(st["has_app"])
            self.assertIn("Client ID", st["error"])

    def test_authorize_address(self):
        fake = FakeKick()
        with tempfile.TemporaryDirectory() as d:
            auth = KickAuth("my-app", "s3cret", port=3850, path=Path(d) / "kick_token.json", http=fake, clock=fake.clock)
            st = auth.start_login()
            url = st["pending"]["authorize_url"]
            self.assertTrue(url.startswith("https://id.kick.com/oauth/authorize?"))
            q = parse_qs(urlsplit(url).query)
            self.assertEqual(q["client_id"], ["my-app"])
            self.assertEqual(q["redirect_uri"], ["http://localhost:3850/kick/callback"])
            self.assertEqual(q["scope"], [" ".join(SCOPES)])
            self.assertEqual(q["code_challenge_method"], ["S256"])
            self.assertEqual(q["response_type"], ["code"])
            self.assertNotIn("s3cret", json.dumps(st))          # the secret never goes to the page

    def test_sign_in_and_store(self):
        fake = FakeKick()

        async def go(path):
            auth = await _signed_in(fake, path)
            self.assertTrue(auth.connected)
            self.assertEqual(auth.login, "sensoka-FlaVR")
            self.assertEqual(auth.user_id, "2460000")
            st = auth.status()
            self.assertIsNone(st["pending"])
            self.assertEqual(st["scopes"], SCOPES)
            self.assertEqual(st["missing_scopes"], [])
            self.assertNotIn("tok-1", json.dumps(st))           # the dashboard never sees tokens
            exchange = [c for c in fake.calls if c["form"].get("grant_type") == "authorization_code"][0]
            self.assertEqual(exchange["form"]["redirect_uri"], redirect_uri(3850))
            again = KickAuth("my-app", "s3cret", path=path, http=fake, clock=fake.clock)
            self.assertTrue(again.connected)
            self.assertEqual(again.login, "sensoka-FlaVR")

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_wrong_state_is_ignored_and_keeps_waiting(self):
        fake = FakeKick()

        async def go(path):
            auth = KickAuth("my-app", "s3cret", path=path, http=fake, clock=fake.clock)
            state = _state_and_challenge(fake, auth.start_login())
            ok, msg = await auth.finish_login(code="code-1", state="someone-else")
            self.assertFalse(ok)
            self.assertFalse(auth.connected)
            self.assertIsNotNone(auth.status()["pending"])       # the real press still waits
            self.assertFalse([c for c in fake.calls if c["url"] == kick_auth.TOKEN_URL])
            ok, _ = await auth.finish_login(code="code-1", state=state)
            self.assertTrue(ok)
            ok, _ = await auth.finish_login(code="code-1", state=state)   # used up
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_denied_and_expired(self):
        fake = FakeKick()

        async def go(path):
            auth = KickAuth("my-app", "s3cret", path=path, http=fake, clock=fake.clock)
            state = _state_and_challenge(fake, auth.start_login())
            ok, msg = await auth.finish_login(state=state, error="access_denied")
            self.assertFalse(ok)
            self.assertIn("access_denied", auth.status()["error"])
            state = _state_and_challenge(fake, auth.start_login())
            fake.now += kick_auth.LOGIN_TIMEOUT_SEC + 1
            ok, msg = await auth.finish_login(code="code-1", state=state)
            self.assertFalse(ok)
            self.assertIn("too long", msg)

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_refused_exchange_names_the_redirect_url(self):
        fake = FakeKick()

        async def go(path):
            auth = KickAuth("my-app", "s3cret", path=path, http=fake, clock=fake.clock)
            state = _state_and_challenge(fake, auth.start_login())
            ok, msg = await auth.finish_login(code="wrong", state=state)
            self.assertFalse(ok)
            self.assertIn("http://localhost:3850/kick/callback", msg)
            self.assertFalse(auth.connected)

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))


class TokenTests(unittest.TestCase):
    def test_refresh_before_expiry_keeps_new_refresh_token(self):
        fake = FakeKick()

        async def go(path):
            auth = await _signed_in(fake, path)
            n = len(fake.calls)
            self.assertEqual(await auth.token(), "tok-1")
            self.assertEqual(len(fake.calls), n)                 # fresh: no network
            fake.now += 7200
            self.assertEqual(await auth.token(), "tok-r1")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["refresh_token"], "ref-r1")
            refresh = [c for c in fake.calls if c["form"].get("grant_type") == "refresh_token"][0]
            self.assertEqual(refresh["form"]["client_secret"], "s3cret")
            auth.invalidate()
            self.assertEqual(await auth.token(), "tok-r2")

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_dead_refresh_token_means_sign_in_again(self):
        fake = FakeKick()

        async def go(path):
            auth = await _signed_in(fake, path)
            fake.refresh_ok = False
            fake.now += 8000
            self.assertIsNone(await auth.token())
            self.assertFalse(auth.connected)
            self.assertIn("Connect Kick", auth.status()["error"])
            self.assertFalse(path.exists())

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_changing_the_app_drops_the_old_sign_in(self):
        fake = FakeKick()

        async def go(path):
            auth = await _signed_in(fake, path)
            auth.configure("other-app", "s3cret")
            self.assertFalse(auth.connected)
            self.assertFalse(path.exists())

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_disconnect_revokes_and_deletes(self):
        fake = FakeKick()

        async def go(path):
            auth = await _signed_in(fake, path)
            await auth.disconnect()
            self.assertFalse(auth.connected)
            self.assertFalse(path.exists())
            revoke = [c for c in fake.calls if c["url"] == kick_auth.REVOKE_URL]
            self.assertEqual(revoke[0]["params"], {"token": "tok-1", "token_hint_type": "access_token"})

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_get_auth_follows_config(self):
        kick_auth._shared = None
        try:
            a = kick_auth.get_auth({"kick": {"client_id": "x", "client_secret": "y"}, "core": {"port": 4000}})
            self.assertTrue(a.has_app)
            self.assertEqual(a.redirect_uri, "http://localhost:4000/kick/callback")
            self.assertIs(kick_auth.get_auth(), a)
        finally:
            kick_auth._shared = None


class ChatTests(unittest.TestCase):
    def test_send_chat(self):
        fake = FakeKick()

        async def go(path):
            auth = await _signed_in(fake, path)
            ok, why = await auth.send_chat("hello chat", reply_to_message_id="abc")
            self.assertTrue(ok, why)
            post = [c for c in fake.calls if c["url"] == kick_auth.CHAT_URL][-1]
            self.assertEqual(post["json"], {"broadcaster_user_id": 2460000, "content": "hello chat",
                                            "type": "user", "reply_to_message_id": "abc"})
            ok, _ = await auth.send_chat("x" * 900)
            self.assertTrue(ok)
            post = [c for c in fake.calls if c["url"] == kick_auth.CHAT_URL][-1]
            self.assertEqual(len(post["json"]["content"]), kick_auth.CHAT_MAX_CHARS)
            ok, why = await auth.send_chat("   ")
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_401_refreshes_once_and_403_says_reconnect(self):
        fake = FakeKick()

        async def go(path):
            auth = await _signed_in(fake, path)
            fake.valid_tokens.discard("tok-1")                   # Kick revoked it early
            ok, why = await auth.send_chat("hi")
            self.assertTrue(ok, why)
            self.assertEqual(await auth.token(), "tok-r1")
            fake.chat_status = 403
            ok, why = await auth.send_chat("hi")
            self.assertFalse(ok)
            self.assertIn("Reconnect", why)

        with tempfile.TemporaryDirectory() as d:
            run(go(Path(d) / "kick_token.json"))

    def test_not_connected(self):
        with tempfile.TemporaryDirectory() as d:
            auth = KickAuth("my-app", "s3cret", path=Path(d) / "kick_token.json", http=FakeKick())
            ok, why = run(auth.send_chat("hi"))
            self.assertFalse(ok)
            self.assertIn("Connect Kick", why)


class RouteTests(unittest.TestCase):
    """Dashboard endpoints and the callback page, through FastAPI's test client."""

    TOKEN = "unit-test-admin-token-123456"

    def test_dashboard_and_callback(self):
        from fastapi.testclient import TestClient

        from api.server import CoreState, create_app

        fake = FakeKick()
        with tempfile.TemporaryDirectory() as d:
            kick_auth._shared = KickAuth("my-app", "s3cret", path=Path(d) / "kick_token.json",
                                         http=fake, clock=fake.clock)
            try:
                state = CoreState()
                state.config = {"points": {"admin_token": self.TOKEN},
                                "kick": {"client_id": "my-app", "client_secret": "s3cret"},
                                "core": {"port": 3850}}
                app = create_app(state)
                hdr = {"X-Admin-Token": self.TOKEN}
                with TestClient(app, base_url="http://localhost:3850") as client:
                    self.assertEqual(client.get("/api/admin/kick/auth").status_code, 401)
                    st = client.get("/api/admin/kick/auth", headers=hdr).json()
                    self.assertFalse(st["connected"])
                    self.assertEqual(st["redirect_uri"], "http://localhost:3850/kick/callback")
                    self.assertNotIn("s3cret", json.dumps(st))
                    st = client.post("/api/admin/kick/auth/start", headers=hdr).json()
                    state_val = _state_and_challenge(fake, st)
                    # a stranger's link: refused, nothing changes
                    r = client.get("/kick/callback", params={"code": "code-1", "state": "nope"})
                    self.assertEqual(r.status_code, 400)
                    r = client.get("/kick/callback", params={"code": "code-1", "state": state_val})
                    self.assertEqual(r.status_code, 200)
                    self.assertIn("connected as sensoka-FlaVR", r.text)
                    st = client.post("/api/admin/kick/auth/test", headers=hdr).json()
                    self.assertTrue(st["test_ok"], st["test_message"])
                    st = client.post("/api/admin/kick/auth/disconnect", headers=hdr).json()
                    self.assertFalse(st["connected"])
            finally:
                kick_auth._shared = None


if __name__ == "__main__":
    unittest.main()
