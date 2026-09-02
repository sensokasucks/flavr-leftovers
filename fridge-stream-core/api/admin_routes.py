"""
Admin API for users, points, account linking, chat history export,
and the hybrid config / commands editor.

Protected by a simple shared token from config (points.admin_token).
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
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
from core.command_groups import catalog_status
from core.models import ChatEvent, ChatUser, Platform
from core.alerts import (
    SKINS,
    build_alert,
    kind_catalog,
    read_alert_settings,
    read_custom_css,
    write_alert_settings,
    write_custom_css,
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


class CommandGroupsSaveBody(BaseModel):
    """Replace the command_groups section of config.yaml and hot-apply."""

    groups: Dict[str, Any]


class AlertTestBody(BaseModel):
    """Fire a test (or live-shaped) alert on the overlay."""

    kind: str = "follow"
    username: str = "TestViewer"
    display_name: str = ""
    platform: str = "kick"
    amount: Optional[float] = None
    currency: str = ""
    months: Optional[int] = None
    qty: Optional[int] = None
    viewers: Optional[int] = None
    message: str = ""
    duration_ms: Optional[int] = None


class AlertStyleBody(BaseModel):
    """Skin + optional custom CSS for the alerts overlay (no Core restart)."""

    skin: Optional[str] = None
    css: Optional[str] = None


class CommandTestBody(BaseModel):
    """Simulate a chat command through the real router (admin Integrations tab)."""

    message: str = Field(..., description="Full chat text, e.g. !spawn creeper 2")
    username: str = "TestAdmin"
    display_name: str = ""
    platform: str = "kick"
    is_mod: bool = False
    is_admin: bool = True
    is_subscriber: bool = False
    dry_run: bool = True


class MetricsTestBody(BaseModel):
    """Push synthetic metrics to game integrations + overlays."""

    viewers: int = 42
    cpm: float = 5.0
    command_rate: float = 1.0
    power_level: int = Field(8, ge=0, le=15)


class CreditsPlayBody(BaseModel):
    playing: Optional[bool] = None
    mode: Optional[str] = None
    freeze: Optional[bool] = None
    restart: bool = False


class CreditsSeedBody(BaseModel):
    username: str
    display_name: str = ""
    platform: str = "twitch"
    is_mod: bool = False
    message: str = "(seed)"


class CreditsEnableBody(BaseModel):
    enabled: bool


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

    @router.get("/status")
    async def runtime_status(x_admin_token: Optional[str] = Header(None)):
        """
        Hub status: which adapters/games are running, metrics snapshot,
        active command groups, and overlay / related tool URLs.
        """
        _auth(x_admin_token)
        cfg = getattr(core_state, "config", None) or load_config()
        metrics = {}
        if core_state.metrics:
            snap = core_state.metrics.snapshot()
            metrics = {
                "viewers": snap.viewers,
                "viewers_by_platform": getattr(snap, "viewers_by_platform", {}),
                "cpm": snap.cpm,
                "power_level": snap.power_level,
                "command_rate": snap.command_rate,
            }

        adapters_live = list((core_state.adapters or {}).keys())
        games_live = list((core_state.games or {}).keys())
        router = core_state.router
        groups = sorted(router.enabled_groups) if router else ["core"]

        # Config intent vs live
        platforms = {}
        for key in ("kick", "twitch", "youtube"):
            section = cfg.get(key) or {}
            platforms[key] = {
                "configured_enabled": bool(section.get("enabled")),
                "running": key in adapters_live,
                "detail": section.get("channel_slug")
                or section.get("channel")
                or section.get("video_id")
                or "",
            }
        games_cfg = {
            "minecraft": {
                "configured_enabled": bool((cfg.get("minecraft") or {}).get("enabled")),
                "running": "minecraft" in games_live,
                "player_name": (cfg.get("minecraft") or {}).get("player_name", ""),
            },
            "factorio": {
                "configured_enabled": bool((cfg.get("factorio") or {}).get("enabled")),
                "running": "factorio" in games_live,
                "player_name": "",
                "bridge_url": (cfg.get("factorio") or {}).get("bridge_url", "http://127.0.0.1:3847"),
            },
        }

        port = int((cfg.get("core") or {}).get("port", 3850))
        host = (cfg.get("core") or {}).get("host", "127.0.0.1")
        base = f"http://{host}:{port}"

        sources = [
            {
                "name": "Admin hub (this page)",
                "url": f"{base}/admin/",
                "notes": "Main control panel",
            },
            {
                "name": "Kick / live chat overlay",
                "url": f"{base}/overlay/chat.html",
                "notes": "Transparent Webpage source — chat with emotes",
            },
            {
                "name": "Minecraft / metrics overlay",
                "url": f"{base}/overlay/overlay.html",
                "notes": "HP, CPM, power level, inventory flash",
            },
            {
                "name": "Stream alerts overlay",
                "url": f"{base}/overlay/alerts.html",
                "notes": "Transparent Webpage source — follow / sub / raid / Super Chat. Test from the Alerts tab.",
            },
            {
                "name": "Chat Credits overlay",
                "url": f"{base}/overlay/credits.html",
                "notes": "Built-in unique-chatter end credits (Admin → Credits). Transparent Webpage source.",
            },
            {
                "name": "Chat Credits (standalone app)",
                "url": "http://127.0.0.1:3854/",
                "notes": "Optional separate process if you don't want credits inside Core",
            },
            {
                "name": "Factorio stats overlay",
                "url": "http://127.0.0.1:3847/overlay.html",
                "notes": "Fridge Factorio Stats bridge",
            },
            {
                "name": "Reactive Image HTTP",
                "url": "http://127.0.0.1:3851/status",
                "notes": "Audio-reactive avatar control API",
            },
        ]

        cmd_count = 0
        if router:
            cmd_count = len({c.name for c in router.commands.values() if c.enabled})

        return {
            "ok": True,
            "core": {
                "host": host,
                "port": port,
                "command_prefix": (cfg.get("core") or {}).get("command_prefix", "!"),
            },
            "platforms": platforms,
            "games": games_cfg,
            "adapters_running": adapters_live,
            "games_running": games_live,
            "command_groups_active": groups,
            "commands_loaded": cmd_count,
            "points_enabled": bool((cfg.get("points") or {}).get("enabled", False)),
            "chat_log_enabled": bool((cfg.get("chat_log") or {}).get("enabled", False)),
            "credits": {
                "configured_enabled": bool((cfg.get("credits") or {}).get("enabled")),
                "running": bool(getattr(getattr(core_state, "credits", None), "enabled", False)),
                "count": len(getattr(getattr(core_state, "credits", None), "chatters", {}) or {}),
            },
            "metrics": metrics,
            "sources": sources,
            "note": "Restart Stream Core after changing config for platform/game toggles to apply.",
        }

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
        incoming = dict(body.config)
        # Preserve command_groups unless the payload includes them
        if "command_groups" not in incoming:
            live = getattr(core_state, "config", None) or load_config()
            if isinstance(live.get("command_groups"), dict):
                incoming["command_groups"] = live["command_groups"]
        try:
            path = save_config(incoming)
        except Exception as e:
            log.exception("save_config failed")
            raise HTTPException(500, f"Failed to save config: {e}") from e
        # Update in-memory view so subsequent GETs match disk until restart
        # (runtime behaviour still requires restart for adapters/games)
        try:
            core_state.config = load_config()
        except Exception:
            pass
        groups_note = ""
        refresh = getattr(core_state, "refresh_command_groups", None)
        if callable(refresh):
            try:
                active = refresh()
                groups_note = f" Command groups hot-applied: {', '.join(active)}."
            except Exception:
                log.exception("refresh_command_groups after config save failed")
        credits_note = ""
        apply_credits = getattr(core_state, "apply_credits", None)
        if callable(apply_credits):
            try:
                info = apply_credits()
                credits_note = f" Credits {'on' if info.get('enabled') else 'off'}."
            except Exception:
                log.exception("apply_credits after config save failed")
        return {
            "ok": True,
            "path": str(path),
            "message": "Saved. Restart Stream Core for platform/game toggles."
            + groups_note
            + credits_note,
        }

    @router.get("/commands")
    async def get_commands(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        cmds = load_commands()
        _, cmd_path = config_file_info()
        router = getattr(core_state, "router", None)
        return {
            "commands": cmds,
            "commands_path": cmd_path,
            "conflicts": list(getattr(router, "conflicts", []) or []),
            "groups_active": sorted(getattr(router, "enabled_groups", {"core"})),
            "note": "Save hot-reloads commands into the running process.",
        }

    @router.put("/commands")
    async def put_commands(
        body: CommandsSaveBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Write commands.json and hot-reload the router."""
        _auth(x_admin_token)
        if not isinstance(body.commands, dict):
            raise HTTPException(400, "commands object required")
        for name, defn in body.commands.items():
            if not isinstance(defn, dict):
                raise HTTPException(400, f"Command '{name}' must be an object")
        try:
            path = save_commands(body.commands)
        except Exception as e:
            log.exception("save_commands failed")
            raise HTTPException(500, f"Failed to save commands: {e}") from e
        info = {}
        reload_fn = getattr(core_state, "reload_commands", None)
        if callable(reload_fn):
            try:
                info = reload_fn() or {}
            except Exception as e:
                log.exception("hot-reload commands failed")
                raise HTTPException(500, f"Saved but reload failed: {e}") from e
        conflicts = info.get("conflicts") or []
        msg = f"Saved and hot-reloaded {info.get('loaded', '?')} commands."
        if conflicts:
            msg += f" {len(conflicts)} name/alias conflict(s) — see details."
        return {
            "ok": True,
            "path": str(path),
            "message": msg,
            "conflicts": conflicts,
            "groups_active": info.get("groups_active") or [],
        }

    @router.get("/command-groups")
    async def get_command_groups(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        cfg = getattr(core_state, "config", None) or load_config()
        router = getattr(core_state, "router", None)
        extra = router.known_groups() if router else set()
        games = list((getattr(core_state, "games", None) or {}).keys())
        return {
            "groups": catalog_status(cfg, games, extra),
            "active": sorted(getattr(router, "enabled_groups", {"core"})),
            "conflicts": list(getattr(router, "conflicts", []) or []),
            "bind_options": ["", "points", "minecraft"],
        }

    @router.put("/command-groups")
    async def put_command_groups(
        body: CommandGroupsSaveBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Write command_groups into config.yaml and hot-apply enablement."""
        _auth(x_admin_token)
        if not isinstance(body.groups, dict):
            raise HTTPException(400, "groups object required")
        cleaned = {}
        for raw_name, spec in body.groups.items():
            name = str(raw_name or "").strip().lower()
            if not name:
                continue
            if not isinstance(spec, dict):
                raise HTTPException(400, f"Group '{name}' must be an object")
            cleaned[name] = spec
        if "core" not in cleaned:
            cleaned["core"] = {"enabled": True, "always": True, "bind": None}
        live = getattr(core_state, "config", None) or load_config()
        live = dict(live)
        live["command_groups"] = cleaned
        try:
            path = save_config(live)
            core_state.config = load_config()
        except Exception as e:
            log.exception("save command_groups failed")
            raise HTTPException(500, f"Failed to save groups: {e}") from e
        active = []
        refresh = getattr(core_state, "refresh_command_groups", None)
        if callable(refresh):
            active = refresh()
        cfg = core_state.config
        router = getattr(core_state, "router", None)
        extra = router.known_groups() if router else set()
        games = list((getattr(core_state, "games", None) or {}).keys())
        return {
            "ok": True,
            "path": str(path),
            "message": "Groups saved and hot-applied. No Core restart needed.",
            "groups": catalog_status(cfg, games, extra),
            "active": active,
        }

    @router.post("/command-groups/reload")
    async def reload_command_groups(x_admin_token: Optional[str] = Header(None)):
        """Recompute groups + optionally reload commands.json without a save."""
        _auth(x_admin_token)
        reload_fn = getattr(core_state, "reload_commands", None)
        info = {}
        if callable(reload_fn):
            info = reload_fn() or {}
        else:
            refresh = getattr(core_state, "refresh_command_groups", None)
            if callable(refresh):
                info["groups_active"] = refresh()
        return {"ok": True, **info}

    @router.get("/alerts/kinds")
    async def alert_kinds(x_admin_token: Optional[str] = Header(None)):
        """Catalog of overlay alert kinds for the test tab."""
        _auth(x_admin_token)
        ov = (getattr(core_state, "config", None) or {}).get("overlay") or {}
        return {
            "kinds": kind_catalog(),
            "platforms": ["kick", "twitch", "youtube"],
            "default_duration_ms": int(ov.get("alert_duration_ms") or 6000),
            "overlay_url": "/overlay/alerts.html",
            "skins": list(SKINS),
        }

    @router.post("/alerts/test")
    async def fire_test_alert(
        body: AlertTestBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Broadcast a test alert to every connected overlay (and the admin preview)."""
        _auth(x_admin_token)
        ov = (getattr(core_state, "config", None) or {}).get("overlay") or {}
        duration = body.duration_ms
        if duration is None:
            duration = int(ov.get("alert_duration_ms") or 6000)
        try:
            payload = build_alert(
                kind=body.kind,
                username=body.username,
                display_name=body.display_name,
                platform=body.platform,
                amount=body.amount,
                currency=body.currency or "",
                months=body.months,
                qty=body.qty,
                viewers=body.viewers,
                message=body.message,
                duration_ms=duration,
                is_test=True,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        fire = getattr(core_state, "fire_alert", None)
        if fire:
            await fire(payload)
        else:
            # Fallback: WS only (Core not fully wired)
            mgr = getattr(core_state, "ws_manager", None)
            if mgr:
                await mgr.broadcast({"type": "alert", "data": payload})
        return {"ok": True, "alert": payload}

    @router.get("/alerts/style")
    async def get_alert_style(x_admin_token: Optional[str] = Header(None)):
        """Live overlay skin + custom CSS (no restart)."""
        _auth(x_admin_token)
        settings = read_alert_settings()
        return {
            "skin": settings.get("skin") or "classic",
            "css_version": settings.get("css_version") or 0,
            "css": read_custom_css(),
            "skins": list(SKINS),
        }

    @router.put("/alerts/style")
    async def put_alert_style(
        body: AlertStyleBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Write overlay/alerts-custom.css and/or skin. Overlay picks this up live."""
        _auth(x_admin_token)
        settings = read_alert_settings()
        if body.skin is not None:
            skin = (body.skin or "").strip().lower()
            if skin not in SKINS:
                raise HTTPException(400, f"Unknown skin '{body.skin}'. Valid: {', '.join(SKINS)}")
            settings = write_alert_settings(skin=skin)
        if body.css is not None:
            try:
                settings = write_custom_css(body.css)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        return {
            "ok": True,
            "skin": settings.get("skin") or "classic",
            "css_version": settings.get("css_version") or 0,
            "message": "Saved — overlay reloads CSS on the next poll (a few seconds).",
        }

    # ------------------------------------------------------------------
    # Integrations test bench (per-game command / metrics / overlay)
    # ------------------------------------------------------------------

    @router.get("/integrations")
    async def list_integrations(x_admin_token: Optional[str] = Header(None)):
        """
        Catalog for the Integrations tab: running games, commands by group,
        health, and overlay URLs so the UI can build sub-panels.
        """
        _auth(x_admin_token)
        cfg = getattr(core_state, "config", None) or load_config()
        router = core_state.router
        games_live = list((core_state.games or {}).keys())
        groups = sorted(router.enabled_groups) if router else ["core"]
        prefix = (cfg.get("core") or {}).get("command_prefix", "!")
        port = int((cfg.get("core") or {}).get("port", 3850))
        host = (cfg.get("core") or {}).get("host", "127.0.0.1")
        base = f"http://{host}:{port}"

        # Commands grouped for sub-panels
        by_group: Dict[str, list] = {}
        if router:
            seen = set()
            for cmd in router.commands.values():
                if cmd.name in seen:
                    continue
                seen.add(cmd.name)
                g = (cmd.group or "core").lower()
                by_group.setdefault(g, []).append({
                    "name": cmd.name,
                    "aliases": list(cmd.aliases or []),
                    "permission": cmd.permission.value if cmd.permission else "public",
                    "description": cmd.description or "",
                    "args": list(cmd.args or []),
                    "examples": list(cmd.examples or []),
                    "template": cmd.template or "",
                    "special": cmd.special,
                    "handler": cmd.handler or "game",
                    "enabled": bool(cmd.enabled),
                    "cost": int(cmd.cost or 0),
                })
            for g in by_group:
                by_group[g].sort(key=lambda c: c["name"])

        # Known game slots (configured even if not running) + any live extras
        from games import KNOWN_GAMES

        known = list(KNOWN_GAMES)
        for g in games_live:
            if g not in known:
                known.append(g)

        game_panels = []
        for name in known:
            section = cfg.get(name) or {}
            running = name in games_live
            health = False
            health_detail = "not running"
            game_obj = (core_state.games or {}).get(name)
            if game_obj:
                try:
                    health = bool(await game_obj.health())
                    health_detail = "ok" if health else "unreachable"
                except Exception as e:
                    health = False
                    health_detail = str(e)

            overlays = []
            if name == "minecraft":
                overlays = [
                    {
                        "name": "Minecraft / metrics overlay",
                        "url": f"{base}/overlay/overlay.html",
                        "notes": "HP, CPM, power level, inventory flash",
                    },
                ]
            elif name == "factorio":
                if game_obj and hasattr(game_obj, "overlay_catalog"):
                    overlays = game_obj.overlay_catalog()
                else:
                    bridge = str(section.get("bridge_url") or "http://127.0.0.1:3847").rstrip("/")
                    overlays = [
                        {
                            "name": "Factorio stats overlay",
                            "url": f"{bridge}/overlay.html",
                            "notes": "Fridge Factorio Stats bridge — start that app separately",
                        },
                        {
                            "name": "Power",
                            "url": f"{bridge}/power.html",
                            "notes": "Production / consumption",
                        },
                        {
                            "name": "Research",
                            "url": f"{bridge}/research.html",
                            "notes": "Current tech + progress",
                        },
                    ]

            game_panels.append({
                "id": name,
                "label": "Factorio" if name == "factorio" else name.replace("_", " ").title(),
                "configured_enabled": bool(section.get("enabled")),
                "running": running,
                "health": health,
                "health_detail": health_detail,
                "player_name": section.get("player_name") or section.get("player") or "",
                "bridge_url": section.get("bridge_url", ""),
                "client_mod_url": section.get("client_mod_url", ""),
                "server_mod_url": section.get("server_mod_url", ""),
                "command_group": name,
                "commands": by_group.get(name, []),
                "overlays": overlays,
            })

        core_commands = by_group.get("core", []) + by_group.get("points", [])
        shared_overlays = [
            {
                "name": "Chat overlay",
                "url": f"{base}/overlay/chat.html",
                "notes": "Transparent Webpage — live chat + emotes",
            },
            {
                "name": "Alerts overlay",
                "url": f"{base}/overlay/alerts.html",
                "notes": "Transparent Webpage — use Alert test tab for presets",
            },
        ]

        return {
            "ok": True,
            "prefix": prefix,
            "command_groups_active": groups,
            "games": game_panels,
            "core_commands": core_commands,
            "shared_overlays": shared_overlays,
            "platforms": ["kick", "twitch", "youtube"],
        }

    @router.post("/commands/test")
    async def test_command(
        body: CommandTestBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """
        Run a chat command through the real CommandRouter.

        dry_run=true (default): parse + permission + template only.
        dry_run=false: execute against the live game integration (Minecraft mods, etc.).
        """
        _auth(x_admin_token)
        fn = getattr(core_state, "test_command", None)
        if not fn:
            raise HTTPException(503, "Core test_command not wired — restart Stream Core")
        msg = (body.message or "").strip()
        if not msg:
            raise HTTPException(400, "message is required")
        try:
            return await fn(
                msg,
                username=body.username or "TestAdmin",
                display_name=body.display_name or "",
                platform=body.platform or "kick",
                is_mod=bool(body.is_mod),
                is_admin=bool(body.is_admin),
                is_subscriber=bool(body.is_subscriber),
                dry_run=bool(body.dry_run),
            )
        except Exception as e:
            log.exception("commands/test failed")
            raise HTTPException(500, str(e)) from e

    @router.post("/games/{game_id}/metrics-test")
    async def test_game_metrics(
        game_id: str,
        body: MetricsTestBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """
        Push synthetic metrics (viewers / CPM / power level) to game integrations
        and connected overlays. game_id is recorded for the UI; metrics fan out
        to every running game the same way live chat does.
        """
        _auth(x_admin_token)
        fn = getattr(core_state, "test_metrics", None)
        if not fn:
            raise HTTPException(503, "Core test_metrics not wired — restart Stream Core")
        try:
            result = await fn(
                viewers=body.viewers,
                cpm=body.cpm,
                command_rate=body.command_rate,
                power_level=body.power_level,
            )
            result["requested_game"] = (game_id or "").lower().strip()
            return result
        except Exception as e:
            log.exception("metrics-test failed")
            raise HTTPException(500, str(e)) from e

    @router.get("/games/{game_id}/health")
    async def game_health(
        game_id: str,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Ping a single game integration's health endpoint."""
        _auth(x_admin_token)
        gid = (game_id or "").lower().strip()
        game = (core_state.games or {}).get(gid)
        if not game:
            return {
                "ok": False,
                "game": gid,
                "running": False,
                "health": False,
                "detail": "integration not running (enable in config and restart)",
            }
        try:
            healthy = bool(await game.health())
            return {
                "ok": True,
                "game": gid,
                "running": True,
                "health": healthy,
                "detail": "ok" if healthy else "unreachable",
            }
        except Exception as e:
            return {
                "ok": False,
                "game": gid,
                "running": True,
                "health": False,
                "detail": str(e),
            }

    # ------------------------------------------------------------------
    # Chat credits
    # ------------------------------------------------------------------

    def _credits():
        eng = getattr(core_state, "credits", None)
        if not eng:
            raise HTTPException(503, "Credits engine not ready")
        return eng

    async def _credits_broadcast(eng):
        mgr = getattr(core_state, "ws_manager", None)
        if not mgr:
            return
        await mgr.broadcast({"type": "credits_theme", "data": eng.theme})
        await mgr.broadcast({"type": "credits_play", "data": eng.public_play()})
        await mgr.broadcast({"type": "credits_roster", "data": eng.snapshot()})

    def _persist_credits_look(eng):
        cfg = getattr(core_state, "config", None) or load_config()
        section = dict(cfg.get("credits") or {})
        section["enabled"] = eng.enabled
        section.update(eng.theme)
        cfg["credits"] = section
        core_state.config = cfg
        save_config(cfg)

    @router.get("/credits")
    async def credits_status(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        eng = _credits()
        return {
            "ok": True,
            "enabled": eng.enabled,
            "theme": eng.theme,
            "play": eng.public_play(),
            "roster": eng.snapshot(),
            "overlay": "/overlay/credits.html",
            "cast": {
                "styles": eng.cast.list_styles(),
                "style_id": eng.cast.style_id,
                "style": eng.cast.get_style(),
                "overrides": list(eng.cast.overrides.values()),
                "command_permission": eng.command_permission,
                "job_max": 50,
                "allow_alert_groups": True,
            },
        }

    @router.put("/credits/enabled")
    async def credits_enable(
        body: CreditsEnableBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        eng = _credits()
        eng.enabled = bool(body.enabled)
        _persist_credits_look(eng)
        apply = getattr(core_state, "apply_credits", None)
        if callable(apply):
            apply()
        await _credits_broadcast(eng)
        return {"ok": True, "enabled": eng.enabled, "count": len(eng.chatters)}

    @router.put("/credits/theme")
    async def credits_theme(
        body: Dict[str, Any],
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        eng = _credits()
        persist = bool(body.pop("persist", True))
        eng.apply_theme(body)
        if persist:
            _persist_credits_look(eng)
        await _credits_broadcast(eng)
        return eng.theme

    @router.post("/credits/play")
    async def credits_play(
        body: CreditsPlayBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        eng = _credits()
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        public = eng.set_play(payload)
        await _credits_broadcast(eng)
        return public

    @router.post("/credits/reset")
    async def credits_reset(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        eng = _credits()
        eng.reset()
        await _credits_broadcast(eng)
        return {"ok": True, "count": 0}

    @router.post("/credits/seed")
    async def credits_seed(
        body: CreditsSeedBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        eng = _credits()
        name = (body.username or body.display_name or "").strip()
        if not name:
            raise HTTPException(400, "username required")
        try:
            plat = Platform(body.platform.lower())
        except ValueError:
            plat = Platform.TWITCH
        event = ChatEvent(
            platform=plat,
            user=ChatUser(
                platform=plat,
                id=name,
                username=name,
                display_name=body.display_name or name,
                is_mod=body.is_mod,
            ),
            message=body.message or "(seed)",
        )
        eng.ingest(event, force=True)
        await _credits_broadcast(eng)
        return {"ok": True, "count": len(eng.chatters)}

    @router.put("/credits/cast/style")
    async def credits_cast_style(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        eng = _credits()
        sid = eng.cast.set_style(str(body.get("style_id") or body.get("id") or "names"))
        eng.theme["style_id"] = sid
        eng.theme["style"] = eng.cast.get_style().get("style") or "names"
        _persist_credits_look(eng)
        await _credits_broadcast(eng)
        return {"ok": True, "style_id": sid, "style": eng.cast.get_style()}

    @router.put("/credits/cast/file")
    async def credits_cast_file(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        eng = _credits()
        try:
            saved = eng.cast.save_style(body)
        except ValueError as e:
            raise HTTPException(400, str(e))
        await _credits_broadcast(eng)
        return {"ok": True, "style": saved, "styles": eng.cast.list_styles()}

    @router.post("/credits/cast/pin")
    async def credits_cast_pin(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        eng = _credits()
        name = str(body.get("username") or "").strip().lstrip("@")
        plat = str(body.get("platform") or "twitch").lower()
        if body.get("clear") or str(body.get("job") or "").lower() == "clear":
            eng.cast.unpin(plat, name)
        else:
            try:
                eng.cast.pin(plat, name, body.get("job") or "", set_by="admin")
            except ValueError as e:
                raise HTTPException(400, str(e))
        await _credits_broadcast(eng)
        return {"ok": True, "overrides": list(eng.cast.overrides.values())}

    @router.put("/credits/command-permission")
    async def credits_cmd_perm(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        eng = _credits()
        perm = str(body.get("command_permission") or "mod").lower()
        if perm not in ("public", "mod", "admin"):
            perm = "mod"
        eng.command_permission = perm
        cfg = getattr(core_state, "config", None) or load_config()
        section = dict(cfg.get("credits") or {})
        section["command_permission"] = perm
        cfg["credits"] = section
        core_state.config = cfg
        save_config(cfg)
        return {"ok": True, "command_permission": perm}

    @router.get("/credits/roster.csv")
    async def credits_csv(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        eng = _credits()
        snap = eng.snapshot()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["platform", "username", "display_name", "messages", "first_seen", "mod", "vip", "sub", "job", "origin", "alert_note"])
        job_map = {}
        for c in snap.get("chatters") or []:
            job_map[f"{c.get('platform')}:{c.get('username')}"] = c.get("job") or ""
        for c in snap.get("chatters") or []:
            writer.writerow([
                c.get("platform"),
                c.get("username"),
                c.get("display_name"),
                c.get("messages"),
                c.get("first_seen"),
                int(bool(c.get("is_mod"))),
                int(bool(c.get("is_vip"))),
                int(bool(c.get("is_subscriber"))),
                c.get("job") or job_map.get(f"{c.get('platform')}:{c.get('username')}", ""),
                c.get("origin") or "chat",
                c.get("alert_note") or "",
            ])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=credits-roster.csv"},
        )

    return router
