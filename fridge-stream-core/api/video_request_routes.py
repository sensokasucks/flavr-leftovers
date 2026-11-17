"""
Video requests + Discord bot API.

Admin routes (X-Admin-Token, like every /api/admin route), used by Setup → Discord & video
requests (admin/discord.js) and the Live card "Video requests" (also admin/discord.js):
  GET  /api/admin/video-requests              {queue: VideoRequestQueue.state(), discord: {settings, status}}
  PUT  /api/admin/video-requests/settings     {discord: {...}, video_requests: {...}} merged into config.yaml;
                                              the bot reconnects when its connection settings changed
  POST /api/admin/video-requests/connect      {on} Connect / Disconnect the bot (discord.enabled)
  GET  /api/admin/video-requests/discord/server?guild_id=   {channels, roles} for the dropdowns
  POST /api/admin/video-requests/add          {url} the streamer's own request (skips the per-person rules)
  POST /api/admin/video-requests/approve      {id}
  POST /api/admin/video-requests/deny         {id, reason}
  POST /api/admin/video-requests/play         {id} play this one now; no id = the next approved one
  POST /api/admin/video-requests/skip         stop the one playing (auto-play then starts the next)
  POST /api/admin/video-requests/hold         stop the countdown to the next video (the pause between videos)
  POST /api/admin/video-requests/remove       {id} take one out quietly
  POST /api/admin/video-requests/move         {id, step: -1 | 1} approved play order
  POST /api/admin/video-requests/pause        {on} hold / resume the player page

Player routes (no token: the video player page is an overlay, opened in OBS or a browser tab on
this PC, and so is the queue overlay overlay/video-queue.html; Core only listens on 127.0.0.1):
  GET  /api/video-requests/player             VideoRequestQueue.player_state()
  POST /api/video-requests/player/ended       {id} the video reached its end
  POST /api/video-requests/player/error       {id, code} YouTube's player refused it (removed, not embeddable)

Mounted by api/server.py next to create_tts_router.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Body, Header, HTTPException

from core.config import load_config, save_config
from core.discord_bot import public_settings
from core.discord_bot import read_settings as read_discord
from core.local_guard import resolve_admin_token, token_matches
from core.video_requests import read_settings as read_requests

log = logging.getLogger("api.video_requests")

# YouTube player error codes (IFrame API onError) in plain words, for the History list.
PLAYER_ERRORS = {2: "Bad video link.", 5: "The browser couldn't play it.", 100: "The video was removed or is private.",
                 101: "The video's owner doesn't allow playing it outside YouTube.",
                 150: "The video's owner doesn't allow playing it outside YouTube."}
# discord: keys that need a reconnect when they change
RECONNECT_KEYS = ("enabled", "token")


def create_video_request_router(core_state, core_root) -> APIRouter:
    """Build both routers' routes on one APIRouter (api/server.py calls this once)."""
    router = APIRouter(tags=["video-requests"])

    def _auth(token: Optional[str]) -> None:
        expected = resolve_admin_token(core_state.config or {}, core_root)
        if not token_matches(token, expected):
            raise HTTPException(401, "Invalid or missing X-Admin-Token")

    def _queue():
        q = getattr(core_state, "video_requests", None)
        if q is None:
            raise HTTPException(503, "Video requests not ready")
        return q

    def _bot():
        b = getattr(core_state, "discord", None)
        if b is None:
            raise HTTPException(503, "Discord bot not ready")
        return b

    def _cfg() -> Dict[str, Any]:
        return getattr(core_state, "config", None) or load_config()

    def _state() -> Dict[str, Any]:
        cfg = _cfg()
        bot = getattr(core_state, "discord", None)
        return {"queue": _queue().state(),
                "discord": {"settings": public_settings(read_discord(cfg)),
                            "status": bot.public_status() if bot else {"state": "off", "text": "Not ready."}}}

    def _id(body: Dict[str, Any]) -> int:
        try:
            return int(body.get("id"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Which request? (id)")

    def _answer(res: Dict[str, Any]) -> Dict[str, Any]:
        if not res.get("ok"):
            raise HTTPException(409, res.get("reason") or "That didn't work.")
        return _state()

    # ── admin ──
    @router.get("/api/admin/video-requests")
    async def vr_state(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _state()

    @router.put("/api/admin/video-requests/settings")
    async def vr_save(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Merge the two blocks into the live config and save. The token is only replaced when a
        new one is typed (token), and cleared with token_clear; token_set is never stored."""
        _auth(x_admin_token)
        cfg = _cfg()
        old_d = read_discord(cfg)
        d_in = dict(body.get("discord") or {})
        d_new = {**old_d, **{k: v for k, v in d_in.items() if k not in ("token", "token_set", "token_clear")}}
        if str(d_in.get("token") or "").strip():
            d_new["token"] = str(d_in["token"]).strip()
        if d_in.get("token_clear"):
            d_new["token"] = ""
        cfg["discord"] = read_discord({"discord": d_new})
        cfg["video_requests"] = read_requests({"video_requests": {**read_requests(cfg), **dict(body.get("video_requests") or {})}})
        core_state.config = cfg
        save_config(cfg)
        bot = getattr(core_state, "discord", None)
        if bot is not None and any(old_d[k] != cfg["discord"][k] for k in RECONNECT_KEYS):
            await bot.restart()
        return _state()

    @router.post("/api/admin/video-requests/connect")
    async def vr_connect(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        cfg = _cfg()
        d = read_discord(cfg)
        d["enabled"] = bool(body.get("on", True))
        cfg["discord"] = d
        core_state.config = cfg
        save_config(cfg)
        await _bot().restart()
        return _state()

    @router.get("/api/admin/video-requests/discord/server")
    async def vr_server(guild_id: str = "", x_admin_token: Optional[str] = Header(None)):
        """The server's text channels and roles, for the Channels tab's dropdowns."""
        _auth(x_admin_token)
        bot = _bot()
        if bot.status.get("state") != "online":
            raise HTTPException(409, "Connect the bot first.")
        if not guild_id.isdigit():
            raise HTTPException(400, "Pick a server first.")
        try:
            return {"channels": await bot.channels(guild_id), "roles": await bot.roles(guild_id)}
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Discord didn't answer: {e.__class__.__name__}")

    @router.post("/api/admin/video-requests/add")
    async def vr_add(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _answer(await _queue().submit(str(body.get("url") or ""), by="Streamer", source="dashboard", bypass_rules=True))

    @router.post("/api/admin/video-requests/approve")
    async def vr_approve(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _answer(_queue().approve(_id(body), by="Streamer"))

    @router.post("/api/admin/video-requests/deny")
    async def vr_deny(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _answer(_queue().deny(_id(body), by="Streamer", reason=str(body.get("reason") or "")))

    @router.post("/api/admin/video-requests/play")
    async def vr_play(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        rid = body.get("id")
        return _answer(await _queue().play(_id(body) if rid not in (None, "") else None, by="Streamer"))

    @router.post("/api/admin/video-requests/skip")
    async def vr_skip(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _answer(await _queue().skip())

    @router.post("/api/admin/video-requests/hold")
    async def vr_hold(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _answer(_queue().hold())

    @router.post("/api/admin/video-requests/remove")
    async def vr_remove(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _answer(_queue().remove(_id(body)))

    @router.post("/api/admin/video-requests/move")
    async def vr_move(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _answer(_queue().move(_id(body), int(body.get("step") or 1)))

    @router.post("/api/admin/video-requests/pause")
    async def vr_pause(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        _queue().set_paused(bool(body.get("on")))
        return _state()

    # ── the player page (no token) ──
    @router.get("/api/video-requests/player")
    async def vr_player():
        return _queue().player_state()

    @router.post("/api/video-requests/player/ended")
    async def vr_player_ended(body: Dict[str, Any] = Body(default={})):
        await _queue().ended(_id(body))
        return {"ok": True}

    @router.post("/api/video-requests/player/error")
    async def vr_player_error(body: Dict[str, Any] = Body(default={})):
        try:
            code = int(body.get("code") or 0)
        except (TypeError, ValueError):
            code = 0
        await _queue().failed(_id(body), PLAYER_ERRORS.get(code, f"YouTube's player error {code}."))
        return {"ok": True}

    return router
