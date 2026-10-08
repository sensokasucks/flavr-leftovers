"""Chatter pictures saved by Core: store, /avatars routes, hide list, user_update wiring.

    python -m unittest tests.test_avatar_store -v
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.avatar_store import AvatarStore, allowed_url, parse_hide, sniff  # noqa: E402

try:
    from PIL import Image
except ImportError:     # the store still works without Pillow (keeps the original file)
    Image = None


def _jpeg(w: int = 300, h: int = 200) -> bytes:
    if Image is None:
        return b"\xff\xd8\xff\xe0" + b"\0" * 200
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 40, 40)).save(out, format="JPEG")
    return out.getvalue()


class FakeFetch:
    def __init__(self, body: bytes = b"", status: int = 200):
        self.body = body or _jpeg()
        self.status = status
        self.calls: list[str] = []

    async def __call__(self, url: str):
        self.calls.append(url)
        return self.status, self.body


def run(coro):
    return asyncio.run(coro)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_download_saves_png_and_local_url(self):
        fetch = FakeFetch()
        ready = []

        async def go():
            st = AvatarStore(root=self.root, fetcher=fetch)

            async def on_ready(p, uid, local):
                ready.append((p, uid, local))

            st.note("twitch", "123", "https://static-cdn.jtvnw.net/a.png", "lunabyte", "LunaByte", on_ready)
            st.note("twitch", "123", "https://static-cdn.jtvnw.net/a.png", "lunabyte", "LunaByte", on_ready)
            await st.wait_idle()
            st.note("twitch", "123", "https://static-cdn.jtvnw.net/a.png")      # fresh: no new download
            await st.wait_idle()
            return st

        st = run(go())
        self.assertEqual(len(fetch.calls), 1)
        self.assertEqual(len(ready), 1)
        local = st.local_url("twitch", "123")
        self.assertTrue(local.startswith("/avatars/twitch/123."), local)
        self.assertEqual(ready[0][2], local)
        name = local.split("/")[-1].split("?")[0]
        body = (self.root / "twitch" / name).read_bytes()
        if Image is not None:
            self.assertEqual(sniff(body), "png")
            with Image.open(io.BytesIO(body)) as im:
                self.assertEqual(im.size, (128, 128))
        self.assertEqual(st.file_path("twitch", name), self.root / "twitch" / name)
        # index survives a restart
        again = AvatarStore(root=self.root, fetcher=fetch)
        self.assertEqual(again.local_url("twitch", "123"), local)
        self.assertEqual(again.find("@LUNABYTE")["id"], "123")

    def test_new_link_downloads_again(self):
        fetch = FakeFetch()

        async def go():
            st = AvatarStore(root=self.root, fetcher=fetch)
            st.note("kick", "9", "https://files.kick.com/a.png")
            await st.wait_idle()
            st.note("kick", "9", "https://files.kick.com/b.png")
            await st.wait_idle()

        run(go())
        self.assertEqual(len(fetch.calls), 2)

    def test_failures_back_off_and_bad_links_are_ignored(self):
        fetch = FakeFetch(status=403)

        async def go():
            st = AvatarStore(root=self.root, fetcher=fetch)
            st.note("kick", "9", "https://files.kick.com/a.png")
            await st.wait_idle()
            st.note("kick", "9", "https://files.kick.com/a.png")     # within RETRY_SEC
            st.note("kick", "10", "http://files.kick.com/a.png")     # not https
            st.note("kick", "11", "https://127.0.0.1/a.png")         # loopback
            st.note("mixer", "12", "https://x.example/a.png")        # unknown platform
            await st.wait_idle()
            return st

        st = run(go())
        self.assertEqual(len(fetch.calls), 1)
        self.assertEqual(st.local_url("kick", "9"), "")

    def test_not_a_picture_is_refused(self):
        fetch = FakeFetch(body=b"<html>blocked</html>")

        async def go():
            st = AvatarStore(root=self.root, fetcher=fetch)
            st.note("kick", "9", "https://files.kick.com/a.png")
            await st.wait_idle()
            return st

        self.assertEqual(run(go()).local_url("kick", "9"), "")

    def test_save_local_off_keeps_links_only(self):
        fetch = FakeFetch()

        async def go():
            st = AvatarStore(root=self.root, fetcher=fetch, save_local=False)
            st.note("kick", "9", "https://files.kick.com/a.png")
            await st.wait_idle()

        run(go())
        self.assertEqual(fetch.calls, [])

    def test_file_path_refuses_odd_names(self):
        st = AvatarStore(root=self.root, fetcher=FakeFetch())
        for plat, name in (("kick", "../x.png"), ("kick", "a/b.png"), ("etc", "x.png"), ("kick", "..")):
            self.assertIsNone(st.file_path(plat, name))

    def test_hide_list(self):
        self.assertEqual(parse_hide(["Bot", "@bot", "KICK:Someone", "yt:Tube", "x:y", ""]),
                         [("", "bot"), ("kick", "someone"), ("youtube", "tube"), ("", "x:y")])
        st = AvatarStore(root=self.root, fetcher=FakeFetch(), hide=["nightbot", "kick:luna"])
        self.assertTrue(st.is_hidden("twitch", "NightBot"))
        self.assertTrue(st.is_hidden("kick", "x", "Luna"))
        self.assertFalse(st.is_hidden("twitch", "luna"))

    def test_allowed_url(self):
        self.assertTrue(allowed_url("https://yt3.ggpht.com/a=s128"))
        for bad in ("http://a.com/x", "https://localhost/x", "https://10.0.0.2/x", "file:///c:/x", "", "javascript:1"):
            self.assertFalse(allowed_url(bad), bad)


class RouteTests(unittest.TestCase):
    def test_avatar_routes(self):
        from fastapi.testclient import TestClient

        from api.server import CoreState, create_app

        with tempfile.TemporaryDirectory() as d:
            st = AvatarStore(root=Path(d), fetcher=FakeFetch())

            async def fill():
                st.note("youtube", "UC1", "https://yt3.ggpht.com/a", "@marblemoth", "MarbleMoth")
                st.note("youtube", "UC2", "https://yt3.ggpht.com/b", "@hidden_one", "Hidden")
                await st.wait_idle()

            run(fill())
            st.configure({"hide": ["hidden"]})
            state = CoreState()
            state.config = {}
            state.avatars = st
            app = create_app(state)
            local = st.local_url("youtube", "UC1")
            with TestClient(app, base_url="http://127.0.0.1:3850") as client:
                r = client.get(local)
                self.assertEqual(r.status_code, 200)
                self.assertTrue(sniff(r.content))
                self.assertEqual(client.get("/avatars/youtube/nope.png").status_code, 404)
                self.assertEqual(client.get("/avatars/etc/x.png").status_code, 404)
                found = client.get("/api/chatters/avatar", params={"name": "marblemoth"}).json()
                self.assertEqual(found["avatar_local"], local)
                self.assertEqual(found["platform"], "youtube")
                r = client.get("/api/chatters/avatar", params={"name": "MarbleMoth", "redirect": 1},
                               follow_redirects=False)
                self.assertEqual(r.status_code, 302)
                self.assertEqual(r.headers["location"], local)
                self.assertEqual(client.get("/api/chatters/avatar", params={"name": "hidden"}).status_code, 404)
                self.assertEqual(client.get("/api/chatters/avatar", params={"name": "nobody"}).status_code, 404)

    def test_admin_avatars_endpoint_and_config_save_keeps_it(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.admin_routes import create_admin_router
        from api.server import CoreState

        token = "unit-test-admin-token-123456"
        disk = {"points": {"admin_token": token}}
        applied = []

        def load():
            return json.loads(json.dumps(disk))

        def save(cfg, path=None):
            disk.clear()
            disk.update(json.loads(json.dumps(cfg)))

        state = CoreState()
        state.config = load()

        async def apply():
            applied.append(1)

        state.apply_avatar_settings = apply
        app = FastAPI()
        app.include_router(create_admin_router(state))
        hdr = {"X-Admin-Token": token}
        with mock.patch("api.admin_routes.load_config", load), mock.patch("api.admin_routes.save_config", save):
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/admin/avatars").status_code, 401)
                self.assertTrue(client.get("/api/admin/avatars", headers=hdr).json()["save_local"])
                res = client.put("/api/admin/avatars", headers=hdr,
                                 json={"save_local": False, "hide": "nightbot\nkick:luna, Nightbot\n\n"}).json()
                self.assertFalse(res["save_local"])
                self.assertEqual(res["hide"], ["nightbot", "kick:luna"])
                self.assertEqual(disk["avatars"]["hide"], ["nightbot", "kick:luna"])
                self.assertEqual(applied, [1])
                # a stale copy of the whole config form must not undo the picture settings
                stale = load()
                stale["avatars"] = {"save_local": True, "hide": []}
                r = client.put("/api/admin/config", headers=hdr, json={"config": stale})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(disk["avatars"]["hide"], ["nightbot", "kick:luna"])


class CoreWiringTests(unittest.TestCase):
    """main.StreamCore's picture handling, without starting the whole Core."""

    def make(self, root: Path, cfg: dict):
        import main
        from api.server import CoreState

        core = main.StreamCore.__new__(main.StreamCore)
        core.config = cfg
        core.state = CoreState()
        core.state.config = cfg
        core.recent_chat = [{"platform": "kick", "user": {"id": "9", "username": "luna", "profile_image_url": None}}]
        core.avatars = AvatarStore(root=root, fetcher=FakeFetch())
        core._avatars_cfg = {}
        sent = []

        class Mgr:
            async def broadcast(self, data):
                sent.append(data)

        core.state.ws_manager = Mgr()
        return core, sent

    def test_user_update_then_local_copy(self):
        with tempfile.TemporaryDirectory() as d:
            core, sent = self.make(Path(d), {})

            async def go():
                await core._on_user_update({"platform": "kick", "id": "9", "username": "luna",
                                            "profile_image_url": "https://files.kick.com/p.png"})
                await core.avatars.wait_idle()

            run(go())
            self.assertEqual([m["type"] for m in sent], ["user_update", "user_update"])
            self.assertEqual(sent[0]["data"]["avatar_local"], "")
            self.assertTrue(sent[1]["data"]["avatar_local"].startswith("/avatars/kick/9."))
            self.assertEqual(sent[1]["data"]["profile_image_url"], "https://files.kick.com/p.png")
            user = core.recent_chat[0]["user"]
            self.assertEqual(user["avatar_local"], sent[1]["data"]["avatar_local"])

    def test_hidden_chatter_gets_nothing_and_new_hide_clears_pictures(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {"avatars": {"hide": ["luna"]}}
            core, sent = self.make(Path(d), cfg)

            async def go():
                await core._on_user_update({"platform": "kick", "id": "9", "username": "luna",
                                            "profile_image_url": "https://files.kick.com/p.png"})
                await core._on_user_update({"platform": "kick", "id": "7", "username": "moss",
                                            "profile_image_url": "https://files.kick.com/m.png"})
                await core.avatars.wait_idle()
                sent.clear()
                core.state.config = {"avatars": {"hide": ["luna", "moss"]}}
                await core.apply_avatar_settings()

            run(go())
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["data"], {"platform": "kick", "id": "7", "hidden": True,
                                               "profile_image_url": "", "avatar_local": ""})

    def test_import_from_stream_rooms_merges(self):
        with tempfile.TemporaryDirectory() as d:
            disk = {"avatars": {"hide": ["nightbot"]}}
            core, _ = self.make(Path(d), json.loads(json.dumps(disk)))

            def save(cfg, path=None):
                disk.clear()
                disk.update(json.loads(json.dumps(cfg)))

            with mock.patch("main.load_config", lambda: json.loads(json.dumps(disk))), \
                    mock.patch("core.config.save_config", save):
                n1 = run(core.import_avatar_hide(["NightBot", "streamelements", "@Moss"]))
                n2 = run(core.import_avatar_hide(["moss"]))
            self.assertEqual((n1, n2), (2, 0))
            self.assertEqual(disk["avatars"]["hide"], ["nightbot", "streamelements", "moss"])
            self.assertTrue(core.avatars.is_hidden("twitch", "StreamElements"))


if __name__ == "__main__":
    unittest.main()
