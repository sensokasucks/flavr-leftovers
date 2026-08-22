"""
Admin API for users, points, account linking, chat history export,
and the hybrid config / commands editor.

Protected by a simple shared token from config (points.admin_token).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.config import (
    DEFAULTS,
    config_file_info,
    load_commands,
    load_config,
    save_commands,
    save_config,
)

log = logging.getLogger("api.admin")


class PointsBody(BaseModel):
    delta: int
    reason: str = "admin adjust"


class LinkBody(BaseModel):
    platform: str
    platform_user_id: str
    username: str = ""
    display_name: str = ""


class MergeBody(BaseModel):
    absorb_user_id: int = Field(..., description="User id to merge INTO the path user")


class NotesBody(BaseModel):
    notes: str = ""


class ConfigSaveBody(BaseModel):
    """Full config dict as edited by the GUI. Written to config.yaml."""

    config: Dict[str, Any]


class CommandsSaveBody(BaseModel):
    """Full commands map as edited by the GUI. Written to commands.json."""

    commands: Dict[str, Any]


def create_admin_router(core_state) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    def _store():
        store = getattr(core_state, "store", None)
        if not store:
            raise HTTPException(503, "Store not ready")
        return store

    def _auth(token: Optional[str]):
        cfg = (core_state.config or {}).get("points", {})
        expected = str(cfg.get("admin_token") or "")
        if not expected or expected in ("change-me", "YOUR_ADMIN_TOKEN", ""):
            if not expected:
                expected = "change-me"
        if not token or token != expected:
            raise HTTPException(401, "Invalid or missing X-Admin-Token")

    # ------------------------------------------------------------------
    # Existing: stats / users / chat
    # ------------------------------------------------------------------

    @router.get("/stats")
    async def stats(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return await _store().stats()

    @router.get("/users")
    async def list_users(
        q: str = "",
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        return await _store().list_users(q=q, limit=limit, offset=offset)

    @router.get("/users/{user_id}")
    async def get_user(user_id: int, x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        u = await _store().get_user(user_id)
        if not u:
            raise HTTPException(404, "User not found")
        return u

    @router.post("/users/{user_id}/points")
    async def adjust_points(
        user_id: int,
        body: PointsBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        if not await _store().get_user(user_id):
            raise HTTPException(404, "User not found")
        return await _store().adjust_points(user_id, body.delta, body.reason, "admin")

    @router.post("/users/{user_id}/link")
    async def link_identity(
        user_id: int,
        body: LinkBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        if not await _store().get_user(user_id):
            raise HTTPException(404, "User not found")
        return await _store().link_identity(
            user_id,
            body.platform.lower().strip(),
            body.platform_user_id.strip(),
            body.username.strip(),
            body.display_name.strip(),
        )

    @router.post("/users/{user_id}/merge")
    async def merge_users(
        user_id: int,
        body: MergeBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        result = await _store().merge_users(user_id, body.absorb_user_id)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "merge failed"))
        return result

    @router.post("/users/{user_id}/notes")
    async def set_notes(
        user_id: int,
        body: NotesBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        if not await _store().get_user(user_id):
            raise HTTPException(404, "User not found")
        await _store().set_notes(user_id, body.notes)
        return {"ok": True}

    @router.get("/chat")
    async def search_chat(
        user_id: Optional[int] = None,
        platform: str = "",
        q: str = "",
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        return await _store().search_chat(
            user_id=user_id, platform=platform, q=q, limit=limit, offset=offset
        )

    @router.get("/chat/export")
    async def export_chat(
        user_id: Optional[int] = None,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        csv_text = await _store().export_chat_csv(user_id=user_id)
        filename = f"chat_user_{user_id}.csv" if user_id else "chat_all.csv"
        return Response(
            content=csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ------------------------------------------------------------------
    # Config + commands editor (hybrid GUI)
    # ------------------------------------------------------------------

    @router.get("/config")
    async def get_config(x_admin_token: Optional[str] = Header(None)):
        """
        Return the effective config (defaults merged with file) plus
        file paths so the UI can show where it will save.
        """
        _auth(x_admin_token)
        # Prefer live in-memory config so the form matches the running process
        live = getattr(core_state, "config", None) or load_config()
        cfg_path, cmd_path = config_file_info()
        return {
            "config": live,
            "defaults": DEFAULTS,
            "config_path": cfg_path,
            "commands_path": cmd_path,
            "note": "Changes are written to disk. Restart Stream Core to apply.",
        }

    @router.put("/config")
    async def put_config(
        body: ConfigSaveBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Write config.yaml. Does not hot-reload — restart Core to apply."""
        _auth(x_admin_token)
        if not isinstance(body.config, dict) or not body.config:
            raise HTTPException(400, "config object required")
        try:
            path = save_config(body.config)
        except Exception as e:
            log.exception("save_config failed")
            raise HTTPException(500, f"Failed to save config: {e}") from e
        # Update in-memory view so subsequent GETs match disk until restart
        # (runtime behaviour still requires restart)
        try:
            core_state.config = load_config()
        except Exception:
            pass
        return {
            "ok": True,
            "path": str(path),
            "message": "Saved. Restart Stream Core for changes to take effect.",
        }

    @router.get("/commands")
    async def get_commands(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        cmds = load_commands()
        _, cmd_path = config_file_info()
        return {
            "commands": cmds,
            "commands_path": cmd_path,
            "note": "Changes are written to disk. Restart Stream Core to apply.",
        }

    @router.put("/commands")
    async def put_commands(
        body: CommandsSaveBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Write commands.json. Restart Core to apply."""
        _auth(x_admin_token)
        if not isinstance(body.commands, dict):
            raise HTTPException(400, "commands object required")
        # Basic sanity: each command should be a dict
        for name, defn in body.commands.items():
            if not isinstance(defn, dict):
                raise HTTPException(400, f"Command '{name}' must be an object")
        try:
            path = save_commands(body.commands)
        except Exception as e:
            log.exception("save_commands failed")
            raise HTTPException(500, f"Failed to save commands: {e}") from e
        return {
            "ok": True,
            "path": str(path),
            "message": "Saved. Restart Stream Core for changes to take effect.",
        }

    return router
