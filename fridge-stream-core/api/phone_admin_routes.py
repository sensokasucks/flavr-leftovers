"""
Dashboard side of the phone remote: /api/admin/phone-remote* (admin token, PC only).

The Setup → Phone remote card (admin.js "Phone remote") uses these to switch the phone door on
and off (api/phone_server.py PhoneServer on core_state.phone_server), show the pairing QR code
and 6-digit code (core/phone_remote.py PhoneRemote on core_state.phone_remote), and list or
remove paired phones. None of these routes is on the phone's own list (phone_server.ALLOWED),
so a phone can never pair another phone or switch the door.

Routes:
  GET    /api/admin/phone-remote             settings, door status, phones, Windows network type
  PUT    /api/admin/phone-remote/enabled     {enabled} -> saved in config.yaml phone_remote.enabled
  PUT    /api/admin/phone-remote/settings    {stop_on_exit, host}
  POST   /api/admin/phone-remote/pair        a new pairing code + the QR link
  POST   /api/admin/phone-remote/pair/cancel
  DELETE /api/admin/phone-remote/phones/{id} unpair one phone
Mounted by api/server.py.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from core.config import load_config, save_config
from core.local_guard import resolve_admin_token, token_matches
from core.phone_remote import PHONE_PORT, find_home_address, windows_network_category

log = logging.getLogger("api.phone_admin")


def create_phone_admin_router(core_state, core_root) -> APIRouter:
    """Build the /api/admin/phone-remote routes (api/server.py calls this once)."""
    router = APIRouter(prefix="/api/admin/phone-remote", tags=["phone"])
    # Windows' network type, asked once a minute at most (PowerShell takes about a second)
    cache: Dict[str, Any] = {"category": "", "at": 0.0}

    def _auth(token: Optional[str]) -> None:
        expected = resolve_admin_token(core_state.config or {}, core_root)
        if not token_matches(token, expected):
            raise HTTPException(401, "Invalid or missing X-Admin-Token")

    def _remote():
        r = getattr(core_state, "phone_remote", None)
        if r is None:
            raise HTTPException(503, "Phone remote not ready")
        return r

    def _server():
        s = getattr(core_state, "phone_server", None)
        if s is None:
            raise HTTPException(503, "Phone remote not ready (Core is still starting)")
        return s

    def _save_block(**values) -> None:
        """Merge ``values`` into config.yaml's phone_remote: block (other blocks kept)."""
        cfg = getattr(core_state, "config", None) or load_config()
        cfg["phone_remote"] = {**(cfg.get("phone_remote") or {}), **values}
        core_state.config = cfg
        save_config(cfg)
        _remote().configure(cfg)

    async def _network() -> str:
        import time as _t
        if _t.time() - cache["at"] > 60:
            cache["category"] = await asyncio.to_thread(windows_network_category)
            cache["at"] = _t.time()
        return cache["category"]

    @router.get("")
    async def info(x_admin_token: Optional[str] = Header(None)):
        """The Phone remote card: on/off, address, phones, whether a code is waiting, network type."""
        _auth(x_admin_token)
        remote = _remote()
        server = getattr(core_state, "phone_server", None)
        return {
            "settings": dict(remote.settings),
            "status": server.status() if server else {"running": False, "error": "Core is still starting"},
            "phones": remote.public_list(),
            "pairing_open": remote.pairing_open(),
            "address_guess": remote.settings.get("host") or find_home_address(),
            "port": PHONE_PORT,
            "network": await _network(),
        }

    @router.put("/enabled")
    async def set_enabled(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Open or close the phone door now, and remember it."""
        _auth(x_admin_token)
        server = _server()
        on = bool(body.get("enabled"))
        if on:
            ok = await server.start()
            if not ok:
                raise HTTPException(409, server.error or "Couldn't switch the phone remote on")
        else:
            _remote().cancel_pairing()
            await server.stop()
        _save_block(enabled=on)
        activity = getattr(core_state, "activity", None)
        if activity is not None:
            activity.add("command", "Phone remote switched " + ("on" if on else "off"))
        return {"ok": True, "status": server.status()}

    @router.put("/settings")
    async def set_settings(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """stop_on_exit (switch off whenever Core starts) and host (a fixed home address, "" = find it)."""
        _auth(x_admin_token)
        values: Dict[str, Any] = {}
        if "stop_on_exit" in body:
            values["stop_on_exit"] = bool(body["stop_on_exit"])
        if "host" in body:
            from core.phone_remote import is_home_address
            host = str(body.get("host") or "").strip()
            if host and not is_home_address(host):
                raise HTTPException(400, "That isn't a home-network address (like 192.168.1.20)")
            values["host"] = host
        _save_block(**values)
        return {"ok": True, "settings": dict(_remote().settings)}

    @router.post("/pair")
    async def start_pair(x_admin_token: Optional[str] = Header(None)):
        """A new code for one phone, valid two minutes. The door must be on."""
        _auth(x_admin_token)
        server = _server()
        if not server.running:
            raise HTTPException(409, "Switch the phone remote on first")
        p = _remote().start_pairing()
        return {"ok": True, **p, "url": server.url(), "qr_url": server.url() + "#pair=" + p["token"]}

    @router.post("/pair/cancel")
    async def cancel_pair(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        _remote().cancel_pairing()
        return {"ok": True}

    @router.delete("/phones/{phone_id}")
    async def remove_phone(phone_id: str, x_admin_token: Optional[str] = Header(None)):
        """Unpair a phone; its key stops working at once."""
        _auth(x_admin_token)
        if not _remote().remove(phone_id):
            raise HTTPException(404, "No such phone")
        return {"ok": True, "phones": _remote().public_list()}

    return router
