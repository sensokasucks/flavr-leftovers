"""
Phone remote door: a second, small web server for the streamer's paired phones.

Why a second server: Core's normal server (127.0.0.1:3850: dashboard, overlays, admin API)
stays reachable from this PC only. This one listens on the PC's home-network address
(core/phone_remote.py find_home_address), port PHONE_PORT 3860, and only while the streamer has
switched it on (Setup → Phone remote). It serves:

  /phone/                    the phone page (fridge-stream-core/phone/: big buttons, chat, people)
  POST /phone/api/pair       a phone answers a pairing code and gets its own key
  GET  /phone/api/summary    one call for the Live screen: platforms, credits, curtain,
                             chat games, highlight (built here, read-only)
  GET  /phone/api/flagged    who is red-flagged (names only, for Unflag; never the phrase list)
  GET  /phone/api/reactions  the reactions that can be run on a chatter (id + label)
  POST /phone/api/reply      answer a chatter in the real chat (as Core's replies do)
  /phone/api/admin/<path>    passed on to Core's own admin API, ONLY for the routes in ALLOWED

Every /phone/api call except pair needs the phone's key (``X-Phone-Key``); callers whose
address isn't a home-network one are refused, and no other web page can call in (no CORS, and
the key header needs one). Admin calls are handed to the main app in-process (httpx
ASGITransport) with the admin token added here, so every check and limit of the real route
still applies and the phone never sees the token. Adding a route to ALLOWED makes it reachable
from every paired phone: keep it to things you'd press mid-stream (see the plan's
"Not allowed, ever" list: no Setup, sign-ins, tokens, history clearing, files, plugins, restart).

Who calls what: main.py _run makes one PhoneServer and puts it on core_state.phone_server;
the dashboard's Phone remote card (api/admin_routes.py /phone-remote*) turns it on and off.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import socket
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from core.local_guard import resolve_admin_token
from core.phone_remote import PHONE_PORT, PhoneRemote, is_home_address

log = logging.getLogger("api.phone")

PHONE_DIR = Path(__file__).resolve().parent.parent / "phone"

# (method, path pattern under /api/admin) a phone may call. Everything else is a 403.
ALLOWED = [
    ("GET", r"/activity"),                              # Stream events window
    ("GET", r"/highlight"),                             # Highlighted message (core/highlights.py)
    ("GET", r"/highlight/recent"),                      # live chat list
    ("POST", r"/highlight"),
    ("POST", r"/highlight/(next|clear|remove)"),
    ("POST", r"/stage"),                                # Stream Rooms curtain
    ("POST", r"/credits/play"),                         # End credits roll buttons
    ("POST", r"/chat_games/action"),                    # Ask trivia, End poll, Lock prediction ...
    ("GET", r"/users"),                                 # People tab search
    ("GET", r"/users/\d+"),
    ("POST", r"/users/\d+/points"),                     # give / take points
    ("POST", r"/red-flags/flag"),                       # red-flag a chatter (never the phrase list)
    ("DELETE", r"/red-flags/\d+"),                      # unflag
    ("POST", r"/reactions/test"),                       # run a reaction on a chatter
]
_ALLOWED_RE = [(m, re.compile("^" + p + "$")) for m, p in ALLOWED]
# Pairing tries: at most this many calls a minute from one address (on top of PhoneRemote's code limits).
PAIR_RATE = 20


def allowed(method: str, path: str) -> bool:
    """Is ``method`` + ``path`` (the part after /api/admin) on the phone's list?"""
    method = method.upper()
    return any(m == method and rx.match(path) for m, rx in _ALLOWED_RE)


def create_phone_app(core_state, remote: PhoneRemote, main_app, core_root: Path) -> FastAPI:
    """The phone door's app. ``main_app`` is Core's own FastAPI app (admin calls go to it in-process)."""
    app = FastAPI(title="Stream Core phone remote", docs_url=None, redoc_url=None, openapi_url=None)
    pair_calls: Dict[str, list] = {}

    @app.middleware("http")
    async def home_network_only(request: Request, call_next):
        """Only callers on the home network (the PC itself counts) get an answer."""
        ip = request.client.host if request.client else ""
        if not (is_home_address(ip) or ip in ("127.0.0.1", "::1")):
            return JSONResponse({"detail": "Home network only"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    def _ip(request: Request) -> str:
        return request.client.host if request.client else ""

    def _phone(request: Request, key: Optional[str]) -> Dict[str, Any]:
        """The paired phone for this call, or 401."""
        phone = remote.check_key(key, _ip(request))
        if phone is None:
            raise HTTPException(401, "This phone isn't paired (or was removed). Pair it again.")
        return phone

    async def _admin(method: str, path: str, *, params=None, json_body=None, phone_name: str = "") -> Response:
        """Call Core's own /api/admin<path> in-process with the admin token."""
        token = resolve_admin_token(core_state.config or {}, core_root)
        transport = httpx.ASGITransport(app=main_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:3850") as client:
            r = await client.request(method, "/api/admin" + path, params=params, json=json_body,
                                     headers={"X-Admin-Token": token or "", "X-Fridge-From": "phone"})
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

    # ── the page ──

    @app.get("/")
    async def root():
        return RedirectResponse("/phone/")

    @app.get("/phone/")
    async def page():
        return FileResponse(PHONE_DIR / "index.html")

    @app.get("/phone/{name}")
    async def asset(name: str):
        """phone.js / phone.css / the icon: files in phone/ only (no folders, no dot-files)."""
        if not re.fullmatch(r"[a-z0-9_-]+\.(js|css|png|svg|webmanifest)", name):
            raise HTTPException(404, "Not found")
        path = PHONE_DIR / name
        if not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path)

    # ── pairing ──

    @app.post("/phone/api/pair")
    async def pair(request: Request, body: Dict[str, Any] = Body(default={})):
        """{code or token, name} -> {key, id, name}. The key is shown to this phone only, once."""
        ip = _ip(request)
        now = time.time()
        recent = [t for t in pair_calls.get(ip, []) if now - t < 60]
        if len(recent) >= PAIR_RATE:
            raise HTTPException(429, "Slow down: too many tries.")
        pair_calls[ip] = recent + [now]
        res = remote.pair(str(body.get("code") or ""), str(body.get("token") or ""), str(body.get("name") or ""), ip)
        if not res.get("ok"):
            raise HTTPException(403, res.get("error") or "Pairing failed")
        log.warning("A phone was paired with Stream Core: %s", res["name"])
        activity = getattr(core_state, "activity", None)
        if activity is not None:
            activity.add("command", f"Phone paired: {res['name']}")
        return res

    # ── phone calls ──

    @app.get("/phone/api/me")
    async def me(request: Request, x_phone_key: Optional[str] = Header(None)):
        """Is this phone still paired? Its name."""
        p = _phone(request, x_phone_key)
        return {"ok": True, "name": p.get("name") or "Phone"}

    @app.get("/phone/api/summary")
    async def summary(request: Request, x_phone_key: Optional[str] = Header(None)):
        """Everything the phone's Live screen shows, in one call (polled every few seconds)."""
        _phone(request, x_phone_key)
        adapters = core_state.adapters or {}
        out: Dict[str, Any] = {
            "platforms": [{"name": n, "connected": bool(getattr(a, "connected", False))} for n, a in adapters.items()],
        }
        eng = getattr(core_state, "credits", None)
        if eng is not None:
            out["credits"] = {"enabled": bool(eng.enabled), "count": len(eng.chatters), "play": eng.public_play()}
        rx = getattr(core_state, "reactions", None)
        if rx is not None:
            out["stage"] = {"connected": bool(rx.game_clients), "curtain": (rx.stage_state or {}).get("curtain", "")}
        games = getattr(core_state, "chat_games", None)
        if games is not None:
            out["chat_games"] = {"enabled": bool(games.cfg.get("enabled")), "boards": len(games.boards or {})}
        hl = getattr(core_state, "highlights", None)
        if hl is not None:
            out["highlight"] = hl.state()
        return out

    @app.get("/phone/api/flagged")
    async def flagged(request: Request, x_phone_key: Optional[str] = Header(None)):
        """Red-flagged chatters (id, platform, names) so the phone can Unflag one. Leaves out the
        phrase list and everything else on the Red flags page."""
        _phone(request, x_phone_key)
        rf = getattr(core_state, "red_flags", None)
        if rf is None:
            return {"flagged": []}
        rows = await rf.list()
        return {"flagged": [{"id": r.get("id"), "platform": r.get("platform") or "",
                             "platform_user_id": r.get("platform_user_id") or "",
                             "username": r.get("username") or "", "display_name": r.get("display_name") or ""}
                            for r in rows[:500]]}

    @app.get("/phone/api/reactions")
    async def reactions(request: Request, x_phone_key: Optional[str] = Header(None)):
        """The reactions the phone's chat menu offers (on, usable now): id + label."""
        _phone(request, x_phone_key)
        eng = getattr(core_state, "reactions", None)
        if eng is None:
            return {"reactions": []}
        out = []
        for e in eng.cfg.get("entries") or []:
            if not e.get("enabled", True):
                continue
            out.append({"id": e["id"], "label": e.get("label") or e["id"]})
        return {"reactions": out[:60]}

    @app.post("/phone/api/reply")
    async def reply(request: Request, body: Dict[str, Any] = Body(default={}), x_phone_key: Optional[str] = Header(None)):
        """Answer a chatter: {platform, message, reply_to_user, reply_to_message_id}. Goes the same
        way as a command's answer (replies.<platform>: real chat when connected, else the overlay)."""
        _phone(request, x_phone_key)
        from core.models import ChatReply, Platform

        text = " ".join(str(body.get("message") or "").split())[:400]
        if not text:
            raise HTTPException(400, "Type something first")
        try:
            plat = Platform(str(body.get("platform") or "").lower())
        except ValueError:
            raise HTTPException(400, "platform must be kick, twitch or youtube")
        core = getattr(core_state, "core", None)
        if core is None:
            raise HTTPException(503, "Core not ready")
        await core.bus.publish_reply(ChatReply(
            platform=plat, message=text, target_platform=plat,
            reply_to_user=str(body.get("reply_to_user") or "")[:60] or None,
            reply_to_message_id=str(body.get("reply_to_message_id") or "")[:120] or None,
            is_system=False, source="command",
        ))
        activity = getattr(core_state, "activity", None)
        if activity is not None:
            activity.add("command", f"Reply from the phone: {text[:80]}", plat.value)
        return {"ok": True}

    @app.api_route("/phone/api/admin/{path:path}", methods=["GET", "POST", "DELETE"])
    async def admin_pass(path: str, request: Request, x_phone_key: Optional[str] = Header(None)):
        """A Live action: passed to Core's admin API if it is on ALLOWED, else 403."""
        phone = _phone(request, x_phone_key)
        sub = "/" + path.strip("/")
        if not allowed(request.method, sub):
            raise HTTPException(403, "The phone can't do that (Setup pages stay on the PC)")
        body = None
        if request.method != "GET":
            raw = await request.body()
            if len(raw) > 20_000:
                raise HTTPException(413, "Too big")
            if raw:
                try:
                    import json as _json
                    body = _json.loads(raw)
                except ValueError:
                    raise HTTPException(400, "Body must be JSON")
        params = dict(request.query_params)
        return await _admin(request.method, sub, params=params, json_body=body, phone_name=str(phone.get("name") or ""))

    return app


class _QuietServer:
    """uvicorn.Server without its own Ctrl+C handling: Core's main server already has it, and two
    servers fighting over the signal handlers would stop Core from quitting cleanly."""

    @staticmethod
    def make(config):
        import uvicorn

        class Quiet(uvicorn.Server):
            def install_signal_handlers(self) -> None:       # older uvicorn
                pass

            @contextlib.contextmanager
            def capture_signals(self):                        # uvicorn 0.29+
                yield

        return Quiet(config)


class PhoneServer:
    """Starts and stops the phone door on the home-network address (one per Core, main.py).

    ``status()`` is what the dashboard card shows: running or not, the address, why it failed.
    """

    def __init__(self, core_state, remote: PhoneRemote, main_app, core_root: Path):
        self.state = core_state
        self.remote = remote
        self.main_app = main_app
        self.root = core_root
        self._server = None
        self._task: Optional[asyncio.Task] = None
        self.address = ""
        self.error = ""
        self.started_at = 0.0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def url(self) -> str:
        return f"http://{self.address}:{PHONE_PORT}/phone/" if self.address else ""

    async def start(self) -> bool:
        """Open the door. False (and ``error`` set) when there's no home network or the port is taken."""
        if self.running:
            return True
        import uvicorn

        self.error = ""
        ip = self.remote.address()
        if not ip:
            self.error = "This PC isn't on a home network (no 192.168.x.x / 10.x.x.x address)."
            return False
        # bind here, so a taken port is an error message and never stops Core (uvicorn exits on bind errors)
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sock = socket.socket(fam, socket.SOCK_STREAM)
        try:
            sock.bind((ip, PHONE_PORT))
        except OSError as e:
            sock.close()
            self.error = f"Couldn't open port {PHONE_PORT} on {ip}: {e.strerror or e}"
            log.warning("Phone remote: %s", self.error)
            return False
        app = create_phone_app(self.state, self.remote, self.main_app, self.root)
        config = uvicorn.Config(app, log_level="warning", loop="asyncio", access_log=False)
        self._server = _QuietServer.make(config)
        self.address = ip
        self.started_at = time.time()
        self._task = asyncio.create_task(self._serve(sock), name="phone-remote")
        log.warning("Phone remote is ON: http://%s:%s/phone/ (home network only)", ip, PHONE_PORT)
        return True

    async def _serve(self, sock: socket.socket) -> None:
        try:
            await self._server.serve(sockets=[sock])
        except Exception as e:      # never take Core down with it
            self.error = f"Phone remote stopped: {e}"
            log.exception("phone remote server failed")
        finally:
            with contextlib.suppress(Exception):
                sock.close()

    async def stop(self) -> None:
        """Close the door (phones get no answer until it is switched on again)."""
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()
        self._task = None
        self._server = None
        if self.address:
            log.warning("Phone remote is OFF")

    def status(self) -> Dict[str, Any]:
        return {"running": self.running, "address": self.address if self.running else "",
                "url": self.url() if self.running else "", "port": PHONE_PORT, "error": self.error}
