"""
Troubleshooting log files: /api/admin/logs* (admin token, like every /api/admin route).

The dashboard's Setup > Core > Advanced card "Log files for troubleshooting" (admin/admin.js
renderLogFiles) calls these. The files themselves are written by core/debug_log.py (Core) and by
Stream Rooms (its autoload/debug_log.gd, in %APPDATA%\\Redot\\app_userdata\\Stream Rooms\\logs_to_share).
Both are cleaned as they are written, so they are safe to hand out.

Routes:
  GET  /api/admin/logs                     {enabled, current, core: [files], rooms: [files], rooms_found}
                                           files = [{name, size (bytes), modified (unix s)}], newest first
  GET  /api/admin/logs/file?app=&name=     one file as a download (app = "core" | "rooms")
  POST /api/admin/logs/open {app}          opens that folder in Windows Explorer on the PC Core runs on

Only plain file names that match the log naming (NAME_RE) are served, from those two folders.

Mounted by api/server.py next to create_tts_router.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import FileResponse

from core import debug_log
from core.local_guard import resolve_admin_token, token_matches

log = logging.getLogger("api.logs")

# stream_core_2026-11-05_18-12-09.log (+ ".1" for a run's older part), stream_rooms_<same>.log
NAME_RE = re.compile(r"^stream_(core|rooms)_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}\.log(\.1)?$")


def create_log_router(core_state, core_root) -> APIRouter:
    """Build the /api/admin/logs routes (api/server.py calls this once). ``core_root`` is the
    fridge-stream-core folder (data/logs_to_share and data/admin_token.txt live under it)."""
    router = APIRouter(prefix="/api/admin/logs", tags=["logs"])
    root = Path(core_root)

    def _auth(token: Optional[str]) -> None:
        """401 unless ``token`` is the admin token (same rule as api/admin_routes.py _auth)."""
        expected = resolve_admin_token(core_state.config or {}, root)
        if not token_matches(token, expected):
            raise HTTPException(401, "Invalid or missing X-Admin-Token")

    def _dir(app: str) -> Optional[Path]:
        """The folder for ``app`` ("core" or "rooms"); None when Stream Rooms' isn't on this PC."""
        if app == "core":
            return debug_log.folder(root)
        if app == "rooms":
            return debug_log.rooms_folder()
        raise HTTPException(400, "app must be core or rooms")

    @router.get("")
    async def list_logs(x_admin_token: Optional[str] = Header(None)) -> Dict[str, Any]:
        _auth(x_admin_token)
        rooms = debug_log.rooms_folder()
        current = debug_log.current_path()
        return {
            "enabled": bool(((core_state.config or {}).get("core") or {}).get("log_files", True)),
            "current": current.name if current else "",
            "core": debug_log.list_files(debug_log.folder(root), "stream_core_"),
            "rooms": debug_log.list_files(rooms, "stream_rooms_"),
            "rooms_found": rooms is not None,
        }

    @router.get("/file")
    async def get_log(app: str = Query(...), name: str = Query(...),
                      x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        if not NAME_RE.match(name) or NAME_RE.match(name).group(1) != app:
            raise HTTPException(400, "Not a log file name")
        directory = _dir(app)
        path = (directory / name) if directory else None
        if path is None or not path.is_file():
            raise HTTPException(404, "That log file isn't there any more")
        return FileResponse(path, media_type="text/plain; charset=utf-8", filename=name)

    @router.post("/open")
    async def open_folder(body: Dict[str, Any] = Body(default={}),
                          x_admin_token: Optional[str] = Header(None)) -> Dict[str, Any]:
        _auth(x_admin_token)
        directory = _dir(str(body.get("app") or "core"))
        if directory is None:
            raise HTTPException(404, "Stream Rooms hasn't saved a log on this PC yet")
        try:
            if os.name == "nt":
                os.startfile(str(directory))  # noqa: S606 (a folder Core made; Explorer opens it)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(directory)])
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except Exception as e:
            log.warning("Could not open the log folder: %s", e)
            raise HTTPException(500, "Couldn't open the folder on this PC") from e
        return {"ok": True}

    return router
