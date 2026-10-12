"""Chat widgets (core/widget_store.py, overlay/widget*.js): StreamElements / Streamlabs code
widgets imported from their zip, settings filled in, run in a sandboxed frame. Run from
fridge-stream-core:

    python -m unittest tests.test_widgets -v
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.widget_store import (  # noqa: E402
    FRAME_CSP,
    WidgetStore,
    compose_frame,
    field_values,
    fill_fields,
    guess_platform,
    read_zip,
)

SE_JS = """window.addEventListener('onWidgetLoad', function (obj) { const f = obj.detail.fieldData; });
window.addEventListener('onEventReceived', function (obj) { if (obj.detail.listener !== 'message') return; });
const s = "</script><b>";"""
SE_CSS = ".name { color: {nameColor}; font-size: {{size}}px; } .x{display:block} .y { font-family: {fontName}; }"
SE_HTML = '<div class="main-container" data-title="{title}"></div>'
SE_FIELDS = {"nameColor": {"type": "colorpicker", "label": "Name", "value": "#ff0000"},
             "size": {"type": "number", "label": "Size", "value": 18},
             "title": {"type": "text", "label": "Title", "value": "hi"},
             "testMessage": {"type": "button", "label": "Send a test message"}}
SE_DATA = {"nameColor": "#00ff00", "widgetName": "Fancy Chat", "extra": True}

SL_HTML = """<div id="log" class="sl__chat__layout"></div>
<script type="text/template" id="chatlist_item">
  <div data-from="{from}" data-id="{messageId}"><span class="name">{from}</span><span class="message">{message}</span></div>
</script>"""
SL_JS = "document.addEventListener('onLoad', function(obj) {}); document.addEventListener('onEventReceived', function(obj) {});"
SL_CSS = "body { font-size: {font_size}; background: {background_color}; } #log > div { background: {{bubble}}; }"


def se_export_zip(folder: str = "") -> bytes:
    """What StreamElements' "export" gives: widget.ini naming the five .txt files."""
    buf = io.BytesIO()
    pre = folder + "/" if folder else ""
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(pre + "widget.ini", '[HTML]\npath = "html.txt"\n\n[CSS]\npath = "css.txt"\n\n[JS]\npath = "js.txt"\n\n'
                                        '[FIELDS]\npath = "fields.txt"\n\n[DATA]\npath = "data.txt"\n')
        zf.writestr(pre + "html.txt", SE_HTML)
        zf.writestr(pre + "css.txt", SE_CSS)
        zf.writestr(pre + "js.txt", SE_JS)
        zf.writestr(pre + "fields.txt", json.dumps(SE_FIELDS))
        zf.writestr(pre + "data.txt", json.dumps(SE_DATA))
        zf.writestr("__MACOSX/._html.txt", "junk")
    return buf.getvalue()


def plain_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


class ReadTests(unittest.TestCase):
    def test_se_export(self):
        for folder in ("", "Vamp chat widget"):
            parts = read_zip(se_export_zip(folder))
            self.assertEqual(parts["html"], SE_HTML)
            self.assertEqual(json.loads(parts["fields"]), SE_FIELDS)
            self.assertEqual(json.loads(parts["data"]), SE_DATA)

    def test_github_layout_and_streamlabs_files(self):
        # StreamElements' own GitHub widgets: widget.html / .css / .js / widget.json (the fields)
        parts = read_zip(plain_zip({"CustomChat/widget.html": SE_HTML, "CustomChat/widget.css": SE_CSS,
                                    "CustomChat/widget.js": SE_JS, "CustomChat/widget.json": json.dumps(SE_FIELDS),
                                    "CustomChat/widget.png": "x"}))
        self.assertEqual(set(parts), {"html", "css", "js", "fields"})
        parts = read_zip(plain_zip({"chat.html": SL_HTML, "style.css": SL_CSS, "script.js": SL_JS, "fields.json": "{}"}))
        self.assertEqual(guess_platform(parts), "streamlabs")
        self.assertEqual(guess_platform({"js": SE_JS}), "streamelements")

    def test_bad_zips(self):
        with self.assertRaises(ValueError):
            read_zip(b"not a zip")
        with self.assertRaises(ValueError):
            read_zip(plain_zip({"readme.md": "hello"}))


class FillTests(unittest.TestCase):
    def test_values_and_fill(self):
        values = field_values(SE_FIELDS, SE_DATA)
        self.assertEqual(values["nameColor"], "#00ff00")      # saved value beats the default
        self.assertEqual(values["size"], 18)                  # default kept
        self.assertTrue(values["extra"])                      # data keys without a field kept
        css = fill_fields(SE_CSS, values, single=True)
        self.assertIn("color: #00ff00;", css)
        self.assertIn("font-size: 18px;", css)
        self.assertIn(".x{display:block}", css)               # CSS rules untouched
        self.assertIn("{fontName}", css)                      # unknown keys left for css_templates
        self.assertEqual(fill_fields("{a} {{a}}", {"a": True}, single=False), "{a} true")

    def test_compose(self):
        values = field_values(SE_FIELDS, SE_DATA)
        page = compose_frame("streamelements", {"html": SE_HTML, "css": SE_CSS, "js": SE_JS}, values)
        self.assertIn('data-title="hi"', page)
        self.assertIn("font-family: Roboto", page)            # {fontName} filled by css_templates
        self.assertIn('<script src="/overlay/vendor/jquery-3.7.1.min.js">', page)
        self.assertLess(page.index("widget-frame.js"), page.index("onWidgetLoad"))
        self.assertIn("<\\/script><b>", page)                 # widget code stays in its <script>
        self.assertEqual(page.count("</script>"), 4)
        sl = compose_frame("streamlabs", {"html": SL_HTML, "css": SL_CSS, "js": SL_JS}, {"bubble": "#123456"})
        self.assertIn('data-from="{from}"', sl)               # Streamlabs' template names stay
        self.assertIn("background: #123456", sl)
        self.assertIn("background: transparent", sl)          # {background_color}
        self.assertIn('data-platform="streamlabs"', sl)
        self.assertTrue((ROOT / "overlay" / "vendor" / "jquery-3.7.1.min.js").is_file())


class StoreTests(unittest.TestCase):
    def test_add_update_rename_delete(self):
        with tempfile.TemporaryDirectory() as d:
            store = WidgetStore(Path(d))
            w = store.add_zip(se_export_zip(), filename="Vamp chat widget Red.zip")
            self.assertEqual((w["name"], w["platform"], w["title"]), ("vamp-chat-widget-red", "streamelements", "Fancy Chat"))
            self.assertEqual(w["url"], "/overlay/widget.html?name=vamp-chat-widget-red")
            self.assertEqual(store.add_zip(se_export_zip(), filename="Vamp chat widget Red.zip")["name"], "vamp-chat-widget-red-2")
            v1 = w["version"]
            w = store.update(w["name"], values={"nameColor": "#0000ff"})
            self.assertGreater(w["version"], v1)
            self.assertEqual(w["values"]["nameColor"], "#0000ff")
            self.assertIn("#0000ff", store.compose(w["name"]))
            with self.assertRaises(ValueError):
                store.update(w["name"], parts={"fields": "{not json"})
            w = store.update(w["name"], parts={"css": "body{}"}, platform="streamlabs")
            self.assertEqual(w["platform"], "streamlabs")
            self.assertEqual(store.rename(w["name"], "My Chat")["name"], "my-chat")
            self.assertIsNone(store.get("vamp-chat-widget-red"))
            self.assertTrue(store.delete("my-chat"))
            self.assertFalse(store.delete("my-chat"))
            self.assertEqual([x["name"] for x in store.list()], ["vamp-chat-widget-red-2"])
            for bad in ("", "..", "../x", "a/b", "nope"):
                self.assertIsNone(store.get(bad), bad)
                self.assertIsNone(store.compose(bad), bad)
            with self.assertRaises(ValueError):
                store.add({"fields": "{}"})


class RouteTests(unittest.TestCase):
    TOKEN = "test-token-widgets-123"

    def test_routes(self):
        from fastapi.testclient import TestClient

        from api.server import CoreState, create_app

        with tempfile.TemporaryDirectory() as d:
            state = CoreState()
            state.config = {"points": {"admin_token": self.TOKEN}, "twitch": {"channel": "sensoka"}}
            state.widgets = WidgetStore(Path(d))
            h = {"X-Admin-Token": self.TOKEN}
            with TestClient(create_app(state), base_url="http://127.0.0.1:3850") as client:
                body = {"zip": base64.b64encode(se_export_zip()).decode(), "filename": "fancy.zip"}
                self.assertEqual(client.post("/api/admin/widgets", json=body).status_code, 401)
                r = client.post("/api/admin/widgets", json=body, headers=h)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["widget"]["name"], "fancy")
                # the frame: its own blank origin
                r = client.get("/widget-frame/fancy")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.headers["content-security-policy"], FRAME_CSP)
                self.assertIn("#00ff00", r.text)
                self.assertEqual(client.get("/widget-frame/nope").status_code, 404)
                info = client.get("/api/overlay/widget/fancy").json()
                self.assertEqual((info["platform"], info["channel"], info["currency"]), ("streamelements", "sensoka", "USD"))
                # settings, code, the widget's buttons
                r = client.put("/api/admin/widgets/fancy", json={"values": {"size": 30}}, headers=h)
                self.assertEqual(r.json()["widget"]["values"]["size"], 30)
                self.assertEqual(client.get("/api/admin/widgets/fancy", headers=h).json()["code"]["html"], SE_HTML)
                self.assertEqual(client.post("/api/admin/widgets/fancy/button", json={"field": "testMessage"}, headers=h).status_code, 200)
                self.assertEqual(client.post("/api/admin/widgets/fancy/button", json={"field": "size"}, headers=h).status_code, 400)
                r = client.post("/api/admin/widgets", json={"html": SL_HTML, "css": SL_CSS, "js": SL_JS, "name": "bubbles"}, headers=h)
                self.assertEqual(r.json()["widget"]["platform"], "streamlabs")
                self.assertEqual(client.post("/api/admin/widgets", json={"zip": "bm9wZQ=="}, headers=h).status_code, 400)
                self.assertEqual(client.delete("/api/admin/widgets/fancy", headers=h).status_code, 200)
                self.assertEqual(client.get("/api/overlay/widget/fancy").status_code, 404)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class BridgeTests(unittest.TestCase):
    """overlay/widget-bridge.js: Core packets -> StreamElements / Streamlabs event shapes."""

    def run_js(self, code: str):
        script = f"const B = require({json.dumps(str(ROOT / 'overlay' / 'widget-bridge.js'))});\n" \
                 f"console.log(JSON.stringify((() => {{ {code} }})()));"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_se_message(self):
        ev = self.run_js("""return B.seMessage({platform: 'twitch', message_id: 'm1', timestamp: 1700000000,
            message: 'hi Kappa <b>', emotes: [{start: 3, end: 7, url: 'https://static-cdn.jtvnw.net/emoticons/v2/25/default/dark/2.0', id: '25'}],
            user: {id: '42', username: 'luna', display_name: 'Luna', color: '#f0f', is_mod: true, badges: ['subscriber', 'moderator']}}, {});""")
        self.assertEqual(ev["listener"], "message")
        d = ev["event"]["data"]
        self.assertEqual((d["nick"], d["displayName"], d["userId"], d["msgId"], d["text"]), ("luna", "Luna", "42", "m1", "hi Kappa <b>"))
        self.assertEqual(d["tags"]["badges"], "moderator/1,subscriber/1")
        self.assertEqual((d["tags"]["mod"], d["tags"]["subscriber"], d["tags"]["user-type"]), ("1", "1", "mod"))
        self.assertEqual([b["type"] for b in d["badges"]], ["moderator", "subscriber"])
        self.assertEqual(d["emotes"][0]["name"], "Kappa")
        self.assertTrue(d["emotes"][0]["urls"]["4"].endswith("/3.0"))
        self.assertIn('alt="Kappa"', ev["event"]["renderedText"])
        self.assertIn("&lt;b&gt;", ev["event"]["renderedText"])

    def test_kick_tokens_and_badge_pictures(self):
        ev = self.run_js("""return B.seMessage({platform: 'kick', message_id: 'k1', message: 'yo [emote:39261:kkHuh] ok',
            user: {id: '7', username: 'bob', display_name: 'Bob', badges: ['broadcaster']}}, {'badge-broadcaster': '/media/crown'});""")
        d = ev["event"]["data"]
        self.assertEqual(d["text"], "yo kkHuh ok")
        self.assertEqual((d["emotes"][0]["start"], d["emotes"][0]["end"]), (3, 7))
        self.assertEqual(d["badges"][0]["url"], "/media/crown")
        self.assertEqual(ev["event"]["service"], "kick")

    def test_back_to_back_emotes_get_spaces(self):
        # widgets match emotes as whole space-separated words; YouTube / Kick send them touching
        r = self.run_js("""const yt = B.seMessage({platform: 'youtube', message: 'hi:_k::_k:!',
            emotes: [{start: 2, end: 5, url: 'https://yt3.ggpht.com/a', name: ':_k:'}, {start: 6, end: 9, url: 'https://yt3.ggpht.com/a', name: ':_k:'}],
            user: {}}, {}).event.data;
            const kick = B.seMessage({platform: 'kick', message: '[emote:1:a][emote:2:b]', user: {}}, {}).event.data;
            const tw = B.seMessage({platform: 'twitch', message: 'x Kappa', emotes: [{start: 2, end: 6, url: 'https://static-cdn.jtvnw.net/emoticons/v2/25/default/dark/2.0', animated: true}], user: {}}, {}).event.data;
            return [yt.text, yt.emotes.map((e) => [e.start, e.end]), kick.text, kick.emotes.map((e) => [e.start, e.end]), tw.text, tw.emotes[0].animated, tw.emotes[0].gif];""")
        self.assertEqual(r, ["hi :_k: :_k: !", [[3, 6], [8, 11]], "a b", [[0, 0], [2, 2]], "x Kappa", True, True])

    def test_alerts(self):
        r = self.run_js("""return [B.seAlert({kind: 'gift', display_name: 'Gifter', qty: 5}),
            B.seAlert({kind: 'resub', display_name: 'R', months: 7}), B.seAlert({kind: 'superchat', display_name: 'S', amount: 5, currency: 'USD'}),
            B.seAlert({kind: 'raid', display_name: 'Raider', viewers: 12}), B.seAlert({kind: 'hypetrain'}),
            B.slAlert({kind: 'bits', display_name: 'C', amount: 100, platform: 'twitch'}), B.seRemember({}, B.seAlert({kind: 'follow', display_name: 'F'}))];""")
        gift, resub, tip, raid, none, sl, session = r
        self.assertEqual((gift["listener"], gift["event"]["sender"], gift["event"]["amount"], gift["event"]["bulkGifted"]),
                         ("subscriber-latest", "Gifter", 5, True))
        self.assertEqual(resub["event"]["amount"], 7)
        self.assertEqual((tip["listener"], tip["event"]["amount"]), ("tip-latest", 5))
        self.assertEqual((raid["listener"], raid["event"]["amount"]), ("raid-latest", 12))
        self.assertIsNone(none)
        self.assertEqual((sl["type"], sl["for"], sl["message"][0]["amount"]), ("bits", "twitch_account", 100))
        self.assertEqual(session["follower-latest"]["name"], "F")
        self.assertEqual(session["follower-recent"][0]["name"], "F")

    def test_streamlabs_item_is_escaped(self):
        m = self.run_js("""return B.slMessage({platform: 'youtube', message_id: 'y"1', message: '<img src=x onerror=alert(1)>',
            user: {id: 'u', display_name: '<b>Eve</b>', color: 'red" onmouseover="x', badges: ['member']}}, {});""")
        item = m["item"]
        self.assertNotIn("<img src=x", item["message"])
        self.assertEqual(item["from"], "&lt;b&gt;Eve&lt;/b&gt;")
        self.assertNotIn('"', item["color"])
        self.assertNotIn('"', item["messageId"])
        self.assertIn("subscriber-icon", item["badges"])
        self.assertEqual(m["detail"]["command"], "PRIVMSG")


if __name__ == "__main__":
    unittest.main()
