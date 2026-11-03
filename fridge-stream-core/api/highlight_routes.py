"""
Highlighted message API: /api/admin/highlight* (admin token, like every /api/admin route).

The dashboard's "Highlighted message" card (Live controls), the ★ buttons on Chat & flags
rows and the phone remote call these. They drive core/highlights.py HighlightBoard
(core_state.highlights, made by main.py) and broadcast {"type": "highlight"} on /ws so
/overlay/highlight.html and Stream Rooms follow at once.

Routes:
  GET  /api/admin/highlight                 on screen now, the queue, the settings
  GET  /api/admin/highlight/recent?after=N  recent chat lines to pick from (seq > N)
  POST /api/admin/highlight                 {platform, message_id} (+ message / user as a
                                            fallback for older saved lines) -> on screen or queued
  POST /api/admin/highlight/next            current off, next one waiting on
  POST /api/admin/highlight/clear           everything off (screen + queue)
  POST /api/admin/highlight/remove          {id} drop one waiting highlight
  PUT  /api/admin/highlight/settings        {hold_sec, show_avatar} -> config.yaml highlight:

Mounted by api/server.py next to create_admin_router.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from core.config import load_config, save_config
from core.local_guard import resolve_admin_token, token_matches

log = logging.getLogger("api.highlight")


def create_highlight_router(core_state, core_root) -> APIRouter:
    """Build the /api/admin/highlight routes around ``core_state`` (api/server.py calls this once).
    ``core_root`` is the Stream Core folder (for data/admin_token.txt)."""
    router = APIRouter(prefix="/api/admin/highlight", tags=["highlight"])

    def _auth(token: Optional[str]) -> None:
        """401 unless ``token`` is the admin token (same rule as api/admin_routes.py _auth)."""
        expected = resolve_admin_token(core_state.config or {}, core_root)
        if not token_matches(token, expected):
            raise HTTPException(401, "Invalid or missing X-Admin-Token")

    def _board():
        """The HighlightBoard, or 503 while Core is still starting."""
        board = getattr(core_state, "highlights", None)
        if board is None:
            raise HTTPException(503, "Highlights not ready")
        return board

    def _note(text: str, platform: str = "") -> None:
        """A line in the Live page's Stream events window (core/activity.py), kind "command"."""
        log_ = getattr(core_state, "activity", None)
        if log_ is not None:
            log_.add("command", text, platform)

    def _is_red_flagged(row: Dict[str, Any]) -> bool:
        """Red-flagged chatters never go on stream, highlighted or not (core/red_flags.py)."""
        if row.get("flagged"):
            return True
        rf = getattr(core_state, "red_flags", None)
        u = row.get("user") or {}
        if rf is None:
            return False
        return rf.is_flagged(str(row.get("platform") or ""), str(u.get("id") or ""),
                             str(u.get("username") or ""), str(u.get("display_name") or ""))

    @router.get("")
    async def highlight_state(x_admin_token: Optional[str] = Header(None)):
        """What is on the highlight overlay now, the queue behind it, and the settings."""
        _auth(x_admin_token)
        board = _board()
        return {**board.state(), "settings": dict(board.settings)}

    @router.get("/recent")
    async def highlight_recent(after: int = 0, limit: int = 60, x_admin_token: Optional[str] = Header(None)):
        """Recent chat lines (newest last) for the chat windows; ``last`` goes back as ``after``.
        ``reset`` true = start the window over (first call, or Core restarted)."""
        _auth(x_admin_token)
        return _board().recent_since(after, limit)

    @router.post("")
    async def highlight_push(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None),
                             x_fridge_from: Optional[str] = Header(None)):
        """Highlight one chat line. Found by ``platform`` + ``message_id`` among the recent lines
        (keeps the emotes); an older saved line (Chat & flags page) sends ``message`` and ``user``
        too. ``X-Fridge-From: phone`` marks phone presses in the Stream events window."""
        _auth(x_admin_token)
        board = _board()
        platform = str(body.get("platform") or "").lower()
        message_id = str(body.get("message_id") or "")
        row = board.find(platform, message_id)
        if row is None:
            if not body.get("message"):
                raise HTTPException(404, "That message isn't in the recent chat any more")
            user = body.get("user") if isinstance(body.get("user"), dict) else {}
            row = {"platform": platform, "message_id": message_id, "message": body.get("message"),
                   "user": user}
        if _is_red_flagged(row):
            raise HTTPException(409, "That chatter is red-flagged, so they stay off stream")
        by = "phone" if (x_fridge_from or "").lower() == "phone" else "dashboard"
        try:
            item = board.push(row, by=by)
        except ValueError as e:
            raise HTTPException(400, str(e))
        await board.changed()
        name = (item.get("user") or {}).get("display_name") or "someone"
        where = "on screen" if board.current is item else f"queued ({len(board.queue)} waiting)"
        _note(f"Highlighted {name}'s message{' from the phone' if by == 'phone' else ''}: {where}",
              item.get("platform") or "")
        return {"ok": True, "id": item["id"], "on_screen": board.current is item, **board.state()}

    @router.post("/next")
    async def highlight_next(x_admin_token: Optional[str] = Header(None)):
        """Take the current highlight off; the next one waiting goes on."""
        _auth(x_admin_token)
        board = _board()
        board.next()
        await board.changed()
        return {"ok": True, **board.state()}

    @router.post("/clear")
    async def highlight_clear(x_admin_token: Optional[str] = Header(None)):
        """Take the highlight off and empty the queue."""
        _auth(x_admin_token)
        board = _board()
        board.clear()
        await board.changed()
        return {"ok": True, **board.state()}

    @router.post("/remove")
    async def highlight_remove(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Drop one waiting highlight by ``id``."""
        _auth(x_admin_token)
        board = _board()
        try:
            item_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise HTTPException(400, "id must be a number")
        if not board.remove(item_id):
            raise HTTPException(404, "Not in the queue")
        await board.changed()
        return {"ok": True, **board.state()}

    @router.put("/settings")
    async def highlight_settings(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Save hold_sec / show_avatar into config.yaml's ``highlight:`` block (merged into the
        live config, other blocks untouched) and apply them at once."""
        _auth(x_admin_token)
        board = _board()
        cfg = getattr(core_state, "config", None) or load_config()
        section = dict(cfg.get("highlight") or {})
        for key in ("hold_sec", "show_avatar"):
            if key in body:
                section[key] = body[key]
        cfg["highlight"] = section
        board.configure(cfg)
        # store the cleaned values, not what was sent
        cfg["highlight"] = {**section, **{k: board.settings[k] for k in ("hold_sec", "show_avatar")}}
        core_state.config = cfg
        save_config(cfg)
        await board.changed()
        return {"ok": True, "settings": dict(board.settings)}

    return router
