"""
Stream start / end and the companion bot link: dashboard routes.

  GET  /api/admin/stream             {status: StreamState.status(), settings: {auto_session, restart_grace_min}}
  PUT  /api/admin/stream/settings    {auto_session?, restart_grace_min?}: credits.auto_session and
                                     stream.restart_grace_min, merged into config.yaml
  GET  /api/admin/companion          {settings: public_settings (key → key_set), status}
  PUT  /api/admin/companion/settings {enabled, url, key, key_clear, heartbeat_sec, send_*, moments_clips}:
                                     the key is only replaced when a new one is typed; the link restarts.
                                     moments_clips = moments.twitch_clips (core/chat_moments.py)
  POST /api/admin/companion/test     one hello now → {ok, message}

Used by the Credits page card "When you go live" and Setup → Discord & video requests →
Companion bot (both in admin/discord.js). Every route needs X-Admin-Token. Mounted by
api/server.py next to the video request routes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from core.companion_link import public_settings, read_settings as read_companion
from core.config import load_config, save_config
from core.local_guard import resolve_admin_token, token_matches
from core.chat_moments import read_settings as read_moments
from core.stream_state import read_settings as read_stream


def create_companion_router(core_state, core_root) -> APIRouter:
    router = APIRouter(tags=["companion"])

    def _auth(token: Optional[str]) -> None:
        expected = resolve_admin_token(core_state.config or {}, core_root)
        if not token_matches(token, expected):
            raise HTTPException(401, "Invalid or missing X-Admin-Token")

    def _cfg() -> Dict[str, Any]:
        return getattr(core_state, "config", None) or load_config()

    def _stream_answer() -> Dict[str, Any]:
        cfg = _cfg()
        st = getattr(core_state, "stream", None)
        return {"status": st.status() if st else {"state": "offline", "live": False, "platforms": []},
                "settings": {"auto_session": bool((cfg.get("credits") or {}).get("auto_session")),
                             **read_stream(cfg)}}

    def _companion_answer() -> Dict[str, Any]:
        link = getattr(core_state, "companion", None)
        return {"settings": {**public_settings(read_companion(_cfg())),
                             "moments_clips": read_moments(_cfg())["twitch_clips"]},
                "status": link.status() if link else {"state": "off", "message": "Not ready."}}

    @router.get("/api/admin/stream")
    async def stream_state(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _stream_answer()

    @router.put("/api/admin/stream/settings")
    async def stream_save(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Merge into the live config (only these two keys) and save."""
        _auth(x_admin_token)
        cfg = _cfg()
        if "auto_session" in body:
            credits = dict(cfg.get("credits") or {})
            credits["auto_session"] = bool(body.get("auto_session"))
            cfg["credits"] = credits
        if "restart_grace_min" in body:
            cfg["stream"] = {**dict(cfg.get("stream") or {}),
                             **read_stream({"stream": {"restart_grace_min": body.get("restart_grace_min")}})}
        core_state.config = cfg
        save_config(cfg)
        return _stream_answer()

    @router.get("/api/admin/companion")
    async def companion_state(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _companion_answer()

    @router.put("/api/admin/companion/settings")
    async def companion_save(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        cfg = _cfg()
        old = read_companion(cfg)
        new = {**old, **{k: v for k, v in body.items() if k not in ("key", "key_set", "key_clear")}}
        if str(body.get("key") or "").strip():
            new["key"] = str(body["key"]).strip()
        if body.get("key_clear"):
            new["key"] = ""
        cfg["companion"] = read_companion({"companion": new})
        if "moments_clips" in body:     # chat moments: also make a Twitch clip (core/chat_moments.py)
            cfg["moments"] = {**dict(cfg.get("moments") or {}), "twitch_clips": bool(body["moments_clips"])}
        core_state.config = cfg
        save_config(cfg)
        link = getattr(core_state, "companion", None)
        if link is not None:
            link.restart()
        return _companion_answer()

    @router.post("/api/admin/companion/test")
    async def companion_test(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        link = getattr(core_state, "companion", None)
        if link is None:
            raise HTTPException(503, "Companion link not ready")
        res = await link.test()
        return {**res, **_companion_answer()}

    return router
