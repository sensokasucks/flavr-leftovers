"""
Admin API for users, points, account linking, chat history export,
and the hybrid config / commands editor.

Protected by a simple shared token from config (points.admin_token).
"""

from __future__ import annotations

import copy
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from core import plugin_manifest
from core.command_groups import catalog_status
from core.local_guard import resolve_admin_token, token_matches
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

_CORE_ROOT = Path(__file__).resolve().parent.parent


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
    """Skin + optional custom CSS (+ options such as sound_volume) for the alerts overlay (no Core restart)."""

    skin: Optional[str] = None
    css: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class ChatStyleBody(BaseModel):
    """Skin, custom CSS and behaviour options for the chat overlay (no Core restart)."""

    skin: Optional[str] = None
    css: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


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


_SKIP = object()


def coerce_plugin_field(field: dict, raw: Any) -> Any:
    """A dashboard value -> what goes in config.yaml, by the manifest field type."""
    kind = str(field.get("type") or "text")
    if kind == "checkbox":
        return bool(raw)
    if kind == "number":
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None if field.get("nullable") else _SKIP
        try:
            num = float(raw)
        except (TypeError, ValueError):
            raise ValueError("needs a number")
        if "min" in field and num < float(field["min"]):
            raise ValueError(f"must be at least {field['min']}")
        return int(num) if num.is_integer() and float(field.get("step") or 1) >= 1 else num
    if kind in ("list", "lines"):
        if isinstance(raw, str):
            sep = "\n" if kind == "lines" else None
            parts = raw.split("\n") if sep else raw.replace("\n", ",").split(",")
        else:
            parts = list(raw or [])
        out = [str(x).strip() for x in parts if str(x).strip()]
        return [x.upper() for x in out] if field.get("upper") else out
    if kind == "map":
        if isinstance(raw, dict):
            items = list(raw.items())
        else:
            items = []
            for line in str(raw or "").replace(",", "\n").split("\n"):
                line = line.strip()
                if not line:
                    continue
                sep = "=" if "=" in line else ":"
                if sep not in line:
                    continue
                key, val = line.rsplit(sep, 1)      # keys may hold ':' (minecraft:diamond:2)
                items.append((key.strip(), val.strip()))
        out = {}
        for key, val in items:
            try:
                out[str(key)] = float(val)
            except (TypeError, ValueError):
                continue
        return out
    text = "" if raw is None else str(raw)
    if kind != "password":
        text = text.strip()
    if field.get("upper"):
        text = text.upper()
    if kind == "select" and field.get("options") and text not in [str(o) for o in field["options"]]:
        raise ValueError("not one of the choices")
    return text


def _get_path(data: dict, key: str) -> Any:
    cur: Any = data
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_path(data: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _core_base(cfg: dict) -> str:
    core = cfg.get("core") or {}
    return f"http://{core.get('host', '127.0.0.1')}:{int(core.get('port', 3850))}"


def create_admin_router(core_state) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    def _store():
        store = getattr(core_state, "store", None)
        if not store:
            raise HTTPException(503, "Store not ready")
        return store

    def _plugin_rows(cfg: dict, base: str) -> list:
        mgr = getattr(core_state, "plugins", None)
        return mgr.info(cfg, base) if mgr is not None else []

    def _plugins_follow(cfg: dict) -> None:
        mgr = getattr(core_state, "plugins", None)
        if mgr is not None:
            mgr.apply_config(cfg)

    def _auth(token: Optional[str]):
        # Placeholder tokens ("change-me") are never accepted; Core falls back
        # to the random token it generated in data/admin_token.txt.
        expected = resolve_admin_token(core_state.config or {}, _CORE_ROOT)
        if not token_matches(token, expected):
            raise HTTPException(
                401,
                "Invalid or missing X-Admin-Token. Use points.admin_token from config.yaml, "
                "or the generated token in data/admin_token.txt (printed at startup).",
            )

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
        port = int((cfg.get("core") or {}).get("port", 3850))
        host = (cfg.get("core") or {}).get("host", "127.0.0.1")
        base = f"http://{host}:{port}"

        # Game plugins: config intent vs live (plugins/<id>/; none installed = empty)
        plugin_rows = _plugin_rows(cfg, base)
        games_cfg = {
            row["id"]: {
                "name": row["name"],
                "configured_enabled": row["configured_enabled"],
                "running": row["running"],
                "player_name": str(row["values"].get("player_name") or ""),
                "bridge_url": str(row["status"].get("bridge_url") or row["values"].get("bridge_url") or ""),
                "detail": str(row["status"].get("detail") or ""),
                "error": row["error"] or str(row["status"].get("error") or ""),
            }
            for row in plugin_rows
        }

        from core.overlay_catalog import sources as overlay_sources

        sources = overlay_sources(base)
        # Each installed game plugin's overlays (its own pages on 3850 + its bridge's pages)
        for row in plugin_rows:
            for o in row["overlays"]:
                name = str(o.get("name") or "")
                if not name.lower().startswith(str(row["name"]).lower()):
                    name = f'{row["name"]}: {name}'
                sources.append({**o, "name": name, "plugin": row["id"]})

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
            "reactions": (
                core_state.reactions.status() if getattr(core_state, "reactions", None) else {"enabled": False}
            ),
            "chat_games": (
                {k: v for k, v in core_state.chat_games.status().items() if k in ("enabled", "active", "boards", "stats")}
                if getattr(core_state, "chat_games", None) else {"enabled": False}
            ),
            "metrics": metrics,
            "sources": sources,
            "note": "Chat platforms apply live when config is saved. Restart Stream Core for game toggles.",
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
        flagged: bool = False,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Chat log rows, newest first; each says ``flagged`` (sender is red-flagged).
        ``flagged=1`` = only red-flagged chatters' lines."""
        _auth(x_admin_token)
        return await _store().search_chat(
            user_id=user_id, platform=platform, q=q, limit=limit, offset=offset, flagged_only=flagged
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
            "note": "Changes are written to disk. Chat platforms reconnect on save; "
            "restart Stream Core for game toggles and the port.",
        }

    @router.put("/config")
    async def put_config(
        body: ConfigSaveBody,
        x_admin_token: Optional[str] = Header(None),
    ):
        """Write config.yaml and hot-apply command groups, credits and chat platforms."""
        _auth(x_admin_token)
        if not isinstance(body.config, dict) or not body.config:
            raise HTTPException(400, "config object required")
        incoming = dict(body.config)
        # Preserve command_groups unless the payload includes them
        live = getattr(core_state, "config", None) or load_config()
        if "command_groups" not in incoming:
            if isinstance(live.get("command_groups"), dict):
                incoming["command_groups"] = live["command_groups"]
        # Reactions / chat games / picture settings are owned by their own pages; a stale form copy must not undo them
        for owned in ("reactions", "chat_games", "avatars", "red_flags"):
            if isinstance(live.get(owned), dict):
                incoming[owned] = live[owned]
        # Game plugins' market fields are owned by the Market page (saved there, applied live)
        for m in plugin_manifest.installed():
            section = incoming.get(m.id)
            if not isinstance(section, dict):
                continue
            section = copy.deepcopy(section)
            for field in (m.get("market") or {}).get("fields") or []:
                key = str(field.get("key") or "")
                current = _get_path(live.get(m.id) or {}, key)
                if key and current is not None:
                    _set_path(section, key, copy.deepcopy(current))
            incoming[m.id] = section
        try:
            path = save_config(incoming)
        except Exception as e:
            log.exception("save_config failed")
            raise HTTPException(500, f"Failed to save config: {e}") from e
        # Update in-memory view so subsequent GETs match disk
        # (game integrations and the port still need a restart)
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
        platforms_note = ""
        platforms_info = None
        apply_platforms = getattr(core_state, "apply_platforms", None)
        if callable(apply_platforms):
            try:
                platforms_info = await apply_platforms()
                changed = platforms_info.get("changed") or []
                if changed:
                    platforms_note = f" Reconnected {', '.join(changed)}."
            except Exception:
                log.exception("apply_platforms after config save failed")
                platforms_note = " Chat platforms could not be applied, see the Core log."
        return {
            "ok": True,
            "path": str(path),
            "message": "Saved. Chat platforms apply live; restart Stream Core for game toggles."
            + platforms_note
            + groups_note
            + credits_note,
            "platforms": platforms_info,
        }

    @router.post("/platforms/{name}/reconnect")
    async def reconnect_platform(name: str, x_admin_token: Optional[str] = Header(None)):
        """Stop and start one chat platform with the current config (no Core restart)."""
        _auth(x_admin_token)
        name = (name or "").lower().strip()
        if name not in ("kick", "twitch", "youtube"):
            raise HTTPException(404, f"Unknown platform '{name}'")
        apply_platforms = getattr(core_state, "apply_platforms", None)
        if not callable(apply_platforms):
            raise HTTPException(503, "Core apply_platforms not wired — restart Stream Core")
        info = await apply_platforms(force=(name,))
        running = name in (info.get("running") or [])
        enabled = bool(((core_state.config or {}).get(name) or {}).get("enabled"))
        if running:
            msg = f"{name} reconnected."
        elif enabled:
            msg = f"{name} is enabled but did not start. Check the channel settings and the Core log."
        else:
            msg = f"{name} is off (enable it in Config)."
        return {"ok": running or not enabled, "running": running, "message": msg, **info}

    # ------------------------------------------------------------------
    # Twitch sign-in (device code). Never returns the tokens themselves.
    # ------------------------------------------------------------------

    def _twitch_auth():
        from adapters.twitch_auth import get_auth

        return get_auth(getattr(core_state, "config", None) or load_config())

    @router.get("/twitch/auth")
    async def twitch_auth_status(x_admin_token: Optional[str] = Header(None)):
        """Connected? As whom? Is a sign-in code waiting to be entered?"""
        _auth(x_admin_token)
        return _twitch_auth().status()

    @router.post("/twitch/auth/start")
    async def twitch_auth_start(x_admin_token: Optional[str] = Header(None)):
        """Ask Twitch for a sign-in code; Core polls in the background until it is entered."""
        _auth(x_admin_token)
        return await _twitch_auth().start_login()

    @router.post("/twitch/auth/cancel")
    async def twitch_auth_cancel(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        auth = _twitch_auth()
        auth.cancel_login()
        return auth.status()

    @router.post("/twitch/auth/disconnect")
    async def twitch_auth_disconnect(x_admin_token: Optional[str] = Header(None)):
        """Revoke the token at Twitch and delete data/twitch_token.json."""
        _auth(x_admin_token)
        auth = _twitch_auth()
        await auth.disconnect()
        return auth.status()

    @router.get("/commands")
    async def get_commands(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        cmds = load_commands()
        # Game plugins' default commands show too (marked with "plugin"); editing one and saving
        # writes it into commands.json, which then wins over the plugin's copy
        for name, data in plugin_manifest.default_commands().items():
            if name not in cmds:
                cmds[name] = {**data, "plugin": str(data.get("group") or "")}
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
        # Unchanged game-plugin commands stay with their plugin (not copied into commands.json)
        plugin_defaults = plugin_manifest.default_commands()
        to_save = {}
        for name, defn in body.commands.items():
            clean = {k: v for k, v in defn.items() if k != "plugin"}
            if name in plugin_defaults and clean == plugin_defaults[name]:
                continue
            to_save[name] = clean
        try:
            path = save_commands(to_save)
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
            "bind_options": ["", "points"] + plugin_manifest.installed_ids(),
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

    # ------------------------------------------------------------------
    # Chat reactions (Config → Reactions)
    # ------------------------------------------------------------------

    def _reactions():
        eng = getattr(core_state, "reactions", None)
        if eng is None:
            raise HTTPException(503, "Reactions engine not ready")
        return eng

    def _reaction_conflicts(cfg: dict) -> list:
        """Reaction command tokens that a commands.json entry already owns (router wins)."""
        router = getattr(core_state, "router", None)
        out = []
        seen: Dict[str, str] = {}
        for e in cfg.get("entries") or []:
            for tok in e.get("commands") or []:
                if tok in seen:
                    out.append({"token": tok, "winner": seen[tok], "loser": e["id"], "reason": "used by two reactions"})
                    continue
                seen[tok] = e["id"]
                if tok == "permit" or (router and router.find(tok)):
                    owner = "permit" if tok == "permit" else router.find(tok).name
                    out.append({"token": tok, "winner": f"command {owner}", "loser": e["id"],
                                "reason": "chat command with this name wins"})
        for tok in (cfg.get("opt_out_command"), cfg.get("opt_in_command"), cfg.get("targets_command")):
            if tok and (tok == "permit" or (router and router.find(tok))):
                out.append({"token": tok, "winner": "chat command", "loser": "reactions built-in",
                            "reason": "rename the reactions command"})
        return out

    @router.get("/reactions")
    async def get_reactions(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        from core.reactions import normalize_config

        eng = _reactions()
        live = getattr(core_state, "config", None) or load_config()
        cfg = normalize_config(live.get("reactions"))
        return {
            "reactions": cfg,
            "effects": eng.known_effects(),
            "status": eng.status(),
            "conflicts": _reaction_conflicts(cfg),
            "prefix": getattr(getattr(core_state, "router", None), "prefix", "!"),
        }

    @router.put("/reactions")
    async def put_reactions(body: Dict[str, Any], x_admin_token: Optional[str] = Header(None)):
        """Write the reactions block into config.yaml (merge) and hot-apply."""
        _auth(x_admin_token)
        from core.reactions import normalize_config

        raw = body.get("reactions") if isinstance(body.get("reactions"), dict) else body
        if not isinstance(raw, dict):
            raise HTTPException(400, "reactions object required")
        cfg = normalize_config(raw)
        live = dict(getattr(core_state, "config", None) or load_config())
        live["reactions"] = cfg
        try:
            path = save_config(live)
            core_state.config = load_config()
        except Exception as e:
            log.exception("save reactions failed")
            raise HTTPException(500, f"Failed to save reactions: {e}") from e
        refresh = getattr(core_state, "refresh_command_groups", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                log.exception("refresh_command_groups after reactions save failed")
        eng = _reactions()
        warn = [s["id"] + ": " + s["why"] for s in eng.status()["entries"] if not s["usable"] and s["why"] != "disabled"]
        msg = f"Saved {len(cfg['entries'])} reactions — live now, no restart."
        if warn:
            msg += " Not usable: " + "; ".join(warn) + "."
        return {
            "ok": True,
            "path": str(path),
            "message": msg,
            "reactions": cfg,
            "status": eng.status(),
            "conflicts": _reaction_conflicts(cfg),
        }

    # Reaction pictures (objects "img:<name>"): list, upload (base64 JSON), delete uploads
    def _images():
        lib = getattr(_reactions(), "images", None)
        if lib is None:
            raise HTTPException(503, "Reaction images not available")
        return lib

    @router.get("/reactions/images")
    async def list_reaction_images(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        from core.reaction_images import MAX_BYTES

        return {"images": _images().list(), "max_bytes": MAX_BYTES}

    @router.post("/reactions/images")
    async def upload_reaction_image(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """{name, data} where data is the file as base64 (a data: URL is fine)."""
        _auth(x_admin_token)
        lib = _images()
        try:
            info = lib.save_base64(str(body.get("name") or ""), str(body.get("data") or ""))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "image": info, "images": lib.list()}

    @router.delete("/reactions/images/{name}")
    async def delete_reaction_image(name: str, x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        lib = _images()
        if not lib.delete(name):
            raise HTTPException(404, "Only uploaded images can be deleted (built-in ones stay).")
        return {"ok": True, "images": lib.list()}

    @router.post("/reactions/test")
    async def test_reaction(body: Dict[str, Any], x_admin_token: Optional[str] = Header(None)):
        """Fire one reaction as a fake chatter. Free, skips permissions; cooldowns still apply."""
        _auth(x_admin_token)
        eng = _reactions()
        rid = str(body.get("id") or "").strip().lower()
        entry = next((e for e in eng.cfg["entries"] if e["id"] == rid), None)
        if entry is None:
            raise HTTPException(404, f"No reaction '{rid}' (save first?)")
        entry = {**entry, "enabled": True, "permission": "public", "require": [], "cost": 0}
        plat = str(body.get("platform") or "twitch").lower()
        try:
            platform = Platform(plat)
        except ValueError:
            platform = Platform.TWITCH
        user = ChatUser(
            platform=platform,
            id=str(body.get("username") or "TestViewer").lower(),
            username=str(body.get("username") or "TestViewer"),
            display_name=str(body.get("username") or "TestViewer"),
            color="#ff8a3d",
        )
        target = str(body.get("target") or "").strip()
        event = ChatEvent(platform=platform, user=user, message=f"(admin test) {target}".strip())
        if bool(body.get("reset_cooldowns", True)):
            eng.gate.clear()
        from core.reactions import _uses_args
        if _uses_args(entry) and not entry["targets"]:
            # sign-style reactions: the Target box is the text
            result = await eng.fire(entry, event, target_words=[], count=1, via="admin", free=True,
                                    text=target or "Hello chat!")
        else:
            result = await eng.fire(entry, event, target_words=[target] if target else [],
                                    count=int(body.get("count") or 1), via="admin", free=True)
        return {**result, "status": eng.status()}

    # ------------------------------------------------------------------
    # Chat games + crowd moments (page: Chat games)
    # ------------------------------------------------------------------

    def _games():
        eng = getattr(core_state, "chat_games", None)
        if eng is None:
            raise HTTPException(503, "Chat games not ready")
        return eng

    def _games_conflicts(eng) -> list:
        """Game commands that a chat command or a reaction already owns (they win)."""
        router = getattr(core_state, "router", None)
        rx = getattr(core_state, "reactions", None)
        rx_tokens = rx.command_tokens() if rx is not None else {}
        out = []
        for name, (feature, _h) in sorted(eng.command_table().items()):
            if name == "permit" or (router and router.find(name)):
                out.append({"token": name, "feature": feature.KEY, "winner": "chat command"})
            elif name in rx_tokens:
                out.append({"token": name, "feature": feature.KEY, "winner": f"reaction {rx_tokens[name].lstrip('@')}"})
        return out

    @router.get("/chat_games")
    async def get_chat_games(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        from core.chat_games import FORM, normalize_config

        eng = _games()
        live = getattr(core_state, "config", None) or load_config()
        return {
            "chat_games": normalize_config(live.get("chat_games")),
            "form": FORM,
            "status": eng.status(),
            "conflicts": _games_conflicts(eng),
            "prefix": getattr(getattr(core_state, "router", None), "prefix", "!"),
        }

    @router.put("/chat_games")
    async def put_chat_games(body: Dict[str, Any], x_admin_token: Optional[str] = Header(None)):
        """Write the chat_games block into config.yaml (merge) and hot-apply."""
        _auth(x_admin_token)
        from core.chat_games import normalize_config

        raw = body.get("chat_games") if isinstance(body.get("chat_games"), dict) else body
        if not isinstance(raw, dict):
            raise HTTPException(400, "chat_games object required")
        cfg = normalize_config(raw)
        live = dict(getattr(core_state, "config", None) or load_config())
        live["chat_games"] = cfg
        try:
            path = save_config(live)
            core_state.config = load_config()
        except Exception as e:
            log.exception("save chat games failed")
            raise HTTPException(500, f"Failed to save chat games: {e}") from e
        refresh = getattr(core_state, "refresh_command_groups", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                log.exception("refresh_command_groups after chat games save failed")
        eng = _games()
        eng.invalidate()
        st = eng.status()
        msg = "Saved — live now, no restart."
        if cfg["enabled"] and not st["active"]:
            msg += " The chat_games command group is off (Settings → Command groups)."
        if cfg["enabled"] and not st["points_enabled"]:
            msg += " Points are off, so predictions, duels, slots, heists, !claim and bumps won't run."
        return {"ok": True, "path": str(path), "message": msg, "chat_games": cfg, "status": st,
                "conflicts": _games_conflicts(eng)}

    @router.post("/chat_games/action")
    async def chat_games_action(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Live buttons: {feature, action, ...} e.g. poll/open, predict/win, trivia/ask, stream/new."""
        _auth(x_admin_token)
        eng = _games()
        res = await eng.admin_action(str(body.get("feature") or ""), str(body.get("action") or ""), body)
        return {**res, "status": eng.status()}

    @router.post("/chat_games/simulate")
    async def chat_games_simulate(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """A test chat line through the whole live path (reactions, chat games, overlays)."""
        _auth(x_admin_token)
        core = getattr(core_state, "core", None)
        if core is None:
            raise HTTPException(503, "Core not ready")
        text = str(body.get("message") or "").strip()
        if not text:
            raise HTTPException(400, "message required")
        name = str(body.get("username") or "TestViewer").strip()[:25] or "TestViewer"
        try:
            platform = Platform(str(body.get("platform") or "kick").lower())
        except ValueError:
            platform = Platform.KICK
        user = ChatUser(platform=platform, id=f"test-{name.lower()}", username=name, display_name=name,
                        is_mod=bool(body.get("is_mod")), color="#8fd3ff")
        event = ChatEvent(platform=platform, user=user, message=text, message_id=f"test-{time.time()}")
        await core._on_chat(event)
        return {"ok": True, "status": _games().status()}

    @router.post("/stage")
    async def stage_command(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Stream Rooms' stage: {"action": "curtain", "value": "open" | "close" | "reveal" | "toggle"}."""
        _auth(x_admin_token)
        action = str(body.get("action") or "curtain")
        value = str(body.get("value") or "")
        if action != "curtain" or value not in ("open", "close", "reveal", "toggle"):
            raise HTTPException(400, "action curtain, value open / close / reveal / toggle")
        eng = _reactions()
        if not await eng.send_stage(action, value):
            raise HTTPException(409, "Stream Rooms isn't connected")
        return {"ok": True, "stage": eng.stage_state}

    @router.get("/chat_games/moments.csv")
    async def chat_games_moments_csv(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        stamp = time.strftime("%Y%m%d-%H%M", time.localtime())
        return Response(
            content=_games().moments.csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="moments-{stamp}.csv"'},
        )

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
            "options": settings.get("options") or {},
            "media": settings.get("media") or {},
            "sounds": settings.get("sounds") or {},
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
        if body.options:
            settings = write_alert_settings(options=body.options)
        if body.css is not None:
            try:
                settings = write_custom_css(body.css)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        return {
            "ok": True,
            "skin": settings.get("skin") or "classic",
            "css_version": settings.get("css_version") or 0,
            "options": settings.get("options") or {},
            "message": "Saved — overlay reloads CSS on the next poll (a few seconds).",
        }

    # ------------------------------------------------------------------
    # Chat overlay look (same idea as the alerts: skin + custom CSS + options)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Chatter profile pictures (core/avatar_store.py): save on/off + hide list
    # ------------------------------------------------------------------

    def _avatars_info() -> Dict[str, Any]:
        cfg = (getattr(core_state, "config", None) or {}).get("avatars") or {}
        store = getattr(core_state, "avatars", None)
        try:
            import PIL  # noqa: F401
            pillow = True
        except ImportError:
            pillow = False
        return {
            "save_local": bool(cfg.get("save_local", True)),
            "hide": [str(x) for x in (cfg.get("hide") or [])],
            "saved": len(store.known_users()) if store else 0,
            "png": pillow,
        }

    @router.get("/avatars")
    async def get_avatars(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _avatars_info()

    @router.put("/avatars")
    async def put_avatars(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Save ``avatars.save_local`` and/or ``avatars.hide`` (one name per entry). Merges config."""
        _auth(x_admin_token)
        cfg = load_config()
        section = dict(cfg.get("avatars") or {})
        if "save_local" in body:
            section["save_local"] = bool(body.get("save_local"))
        if "hide" in body:
            raw = body.get("hide")
            items = raw.splitlines() if isinstance(raw, str) else list(raw or [])
            out: List[str] = []
            for item in items:
                for part in str(item).split(","):
                    name = part.strip()[:80]
                    if name and name.lower() not in [o.lower() for o in out]:
                        out.append(name)
            section["hide"] = out[:1000]
        cfg["avatars"] = section
        save_config(cfg)
        core_state.config = cfg
        apply = getattr(core_state, "apply_avatar_settings", None)
        if apply is not None:
            await apply()
        return {"ok": True, **_avatars_info()}

    # ------------------------------------------------------------------
    # Red flags (core/red_flags.py): phrases + the flagged chatters (Chat history tab)
    # ------------------------------------------------------------------

    def _red_flags():
        rf = getattr(core_state, "red_flags", None)
        if rf is None:
            raise HTTPException(503, "Red flags not ready")
        rf.configure((getattr(core_state, "config", None) or {}).get("red_flags"))
        return rf

    async def _red_flags_info() -> Dict[str, Any]:
        rf = _red_flags()
        return {**rf.info(), "flagged": await rf.list()}

    @router.get("/red-flags")
    async def get_red_flags(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return await _red_flags_info()

    @router.put("/red-flags")
    async def put_red_flags(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Save ``red_flags.enabled`` / ``skip_mods`` / ``phrases`` (list or one per line). Merges config."""
        from core.red_flags import parse_phrases

        _auth(x_admin_token)
        cfg = load_config()
        section = dict(cfg.get("red_flags") or {})
        for key in ("enabled", "skip_mods"):
            if key in body:
                section[key] = bool(body.get(key))
        if "phrases" in body:
            section["phrases"] = parse_phrases(body.get("phrases"))
        cfg["red_flags"] = section
        save_config(cfg)
        core_state.config = cfg
        return {"ok": True, **(await _red_flags_info())}

    @router.post("/red-flags/flag")
    async def flag_by_hand(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Flag a name by hand: ``{"name": "someone", "platform": "kick"|""}`` (no platform = everywhere)."""
        _auth(x_admin_token)
        name = str(body.get("name") or "").strip().lstrip("@")[:80]
        platform = str(body.get("platform") or "").strip().lower()
        if ":" in name and not platform:
            platform, name = (x.strip() for x in name.split(":", 1))
        if not name:
            raise HTTPException(400, "name required")
        if platform and platform not in ("kick", "twitch", "youtube"):
            raise HTTPException(400, "platform must be kick, twitch or youtube")
        rf = _red_flags()
        await rf.flag(platform, "", name, name, source="manual")
        hide = getattr(core_state, "red_flag_hide", None)
        if hide is not None:
            await hide(platform, "", name.lower(), name)
        return {"ok": True, **(await _red_flags_info())}

    @router.delete("/red-flags/{flag_id}")
    async def unflag(flag_id: int, x_admin_token: Optional[str] = Header(None)):
        """Take someone off the list: their new chat shows again (lines already hidden stay hidden)."""
        _auth(x_admin_token)
        if await _red_flags().unflag(flag_id) is None:
            raise HTTPException(404, "Not on the red-flag list")
        return {"ok": True, **(await _red_flags_info())}

    @router.get("/chat/style")
    async def get_chat_style(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        from core.chat_style import CHAT_STYLE

        settings = CHAT_STYLE.read_settings()
        return {
            "skin": settings["skin"],
            "css_version": settings["css_version"],
            "css": CHAT_STYLE.read_css(),
            "skins": list(CHAT_STYLE.skins),
            "options": settings["options"],
            "media": settings["media"],
            "sounds": settings["sounds"],
        }

    @router.put("/chat/style")
    async def put_chat_style(body: ChatStyleBody, x_admin_token: Optional[str] = Header(None)):
        """Write overlay/chat-custom.css, the skin and/or options. The overlay picks it up live."""
        _auth(x_admin_token)
        from core.chat_style import CHAT_STYLE

        settings = CHAT_STYLE.read_settings()
        if body.skin is not None:
            skin = (body.skin or "").strip().lower()
            if skin not in CHAT_STYLE.skins:
                raise HTTPException(400, f"Unknown skin '{body.skin}'. Valid: {', '.join(CHAT_STYLE.skins)}")
            settings = CHAT_STYLE.write_settings(skin=skin)
        if body.options:
            settings = CHAT_STYLE.write_settings(options=body.options)
        if body.css is not None:
            try:
                settings = CHAT_STYLE.write_css(body.css)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        return {
            "ok": True,
            "skin": settings["skin"],
            "css_version": settings["css_version"],
            "options": settings["options"],
            "message": "Saved — overlay reloads on the next poll (a few seconds).",
        }

    # ------------------------------------------------------------------
    # Overlay pictures and sounds (alerts, chat): uploaded as base64 JSON, stored by slot
    # ------------------------------------------------------------------

    def _overlay_style(name: str):
        from core.alerts import ALERT_STYLE
        from core.chat_style import CHAT_STYLE

        styles = {"alerts": ALERT_STYLE, "chat": CHAT_STYLE}
        style = styles.get((name or "").lower().strip())
        if style is None:
            raise HTTPException(404, f"Unknown overlay '{name}'")
        return style

    def _assets_payload(style) -> Dict[str, Any]:
        from core.overlay_style import MAX_ASSET_BYTES

        media, sounds = style.list_assets()
        return {
            "media": media,
            "sounds": sounds,
            "image_slots": list(style.image_slots),
            "sound_slots": list(style.sound_slots),
            "max_bytes": MAX_ASSET_BYTES,
        }

    @router.get("/overlays/{name}/assets")
    async def list_overlay_assets(name: str, x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        return _assets_payload(_overlay_style(name))

    @router.post("/overlays/{name}/assets/{slot}")
    async def upload_overlay_asset(name: str, slot: str, body: Dict[str, Any] = Body(default={}),
                                   x_admin_token: Optional[str] = Header(None)):
        """{data}: the file as base64 (a data: URL is fine). Replaces the slot's old file."""
        _auth(x_admin_token)
        style = _overlay_style(name)
        try:
            url = style.save_asset_base64(slot, str(body.get("data") or ""))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        style.write_settings(bump_css=True)       # nudges open overlays to re-read the list
        return {"ok": True, "url": url, **_assets_payload(style)}

    @router.delete("/overlays/{name}/assets/{slot}")
    async def delete_overlay_asset(name: str, slot: str, kind: Optional[str] = None,
                                   x_admin_token: Optional[str] = Header(None)):
        """?kind=image|sound picks which file when a slot has both (the alert kinds)."""
        _auth(x_admin_token)
        style = _overlay_style(name)
        if not style.delete_asset(slot, kind=kind):
            raise HTTPException(404, "Nothing uploaded for that slot.")
        style.write_settings(bump_css=True)
        return {"ok": True, **_assets_payload(style)}

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

        # Installed game plugins (configured even if not running) + any live extras
        rows = {row["id"]: row for row in _plugin_rows(cfg, base)}
        known = list(rows)
        for g in games_live:
            if g not in known:
                known.append(g)

        game_panels = []
        for name in known:
            section = cfg.get(name) or {}
            row = rows.get(name) or {}
            running = name in games_live
            health = False
            health_detail = row.get("error") or "not running"
            game_obj = (core_state.games or {}).get(name)
            if game_obj:
                try:
                    health = bool(await game_obj.health())
                    health_detail = "ok" if health else "unreachable"
                except Exception as e:
                    health = False
                    health_detail = str(e)

            game_panels.append({
                "id": name,
                "label": row.get("name") or name.replace("_", " ").title(),
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
                "overlays": row.get("overlays") or [],
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
            },
        }

    @router.get("/credits/roster.csv")
    async def credits_roster_csv(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        eng = _credits()
        stamp = time.strftime("%Y%m%d-%H%M", time.localtime())
        return Response(
            content=eng.roster_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="chatters-{stamp}.csv"'},
        )

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

    @router.get("/market")
    async def market_admin(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        tape = getattr(core_state, "market", None)
        cfg = getattr(core_state, "config", None) or {}
        snap = tape.snapshot(include_hidden=True) if tape else {"instruments": [], "enabled": False}
        holdings = []
        store = _store()
        if store and hasattr(store, "list_holdings"):
            holdings = await store.list_holdings()
        base = _core_base(cfg)
        # Game plugins with market settings get their own sub-page (fields from plugin.json)
        plugins = [
            {k: row[k] for k in ("id", "name", "market", "market_status", "values", "running")}
            for row in _plugin_rows(cfg, base) if row.get("market")
        ]
        return {
            "tape": snap,
            "market": cfg.get("market") or {},
            "plugins": plugins,
            "books": ["core"] + [f"game:{pid}" for pid in plugin_manifest.installed_ids()],
            "holdings": holdings,
            "last_dividend": getattr(tape, "last_dividend", None) if tape else None,
            "last_event": getattr(tape, "last_event", None) if tape else None,
        }

    @router.put("/market/settings")
    async def market_settings(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        """Hot-save the market's own switches (on/off, hourly cap, Steam refresh, trade impact)."""
        _auth(x_admin_token)
        cfg = getattr(core_state, "config", None) or load_config()
        mkt = dict(cfg.get("market") or {})
        if "enabled" in body:
            mkt["enabled"] = bool(body["enabled"])
        if "hourly_cap_points" in body:
            mkt["hourly_cap_points"] = max(0, int(body["hourly_cap_points"]))
        if "steam_poll_sec" in body:
            mkt["steam_poll_sec"] = max(60, int(body["steam_poll_sec"]))
        if "trade_impact" in body:
            mkt["trade_impact"] = bool(body["trade_impact"])
        if "trade_impact_bps_per_100" in body:
            mkt["trade_impact_bps_per_100"] = float(body["trade_impact_bps_per_100"])
        cfg["market"] = mkt
        if getattr(core_state, "market", None):
            core_state.market.configure(cfg)
        core_state.config = cfg
        save_config(cfg)
        _plugins_follow(cfg)
        return {"ok": True, "market": mkt}

    # ------------------------------------------------------------------
    # Game plugins (plugins/<id>/plugin.json)
    # ------------------------------------------------------------------

    @router.get("/plugins")
    async def list_plugins(x_admin_token: Optional[str] = Header(None)):
        """Installed game plugins: manifest, settings fields, current values, running, errors."""
        _auth(x_admin_token)
        cfg = getattr(core_state, "config", None) or load_config()
        return {
            "plugins": _plugin_rows(cfg, _core_base(cfg)),
            "folder": str(plugin_manifest.plugins_dir()),
            "api_version": plugin_manifest.PLUGIN_API_VERSION,
        }

    @router.put("/plugins/{plugin_id}/settings")
    async def save_plugin_settings(
        plugin_id: str,
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        """
        Save one plugin's settings into config.yaml (merged, nothing else touched).
        Body: {"values": {"<key or dotted.key>": value, ...}}. Keys must be fields from the
        plugin's manifest (settings / market) or "enabled". Market fields apply live; the rest
        (addresses, passwords, on/off) need a Core restart, which the answer says.
        """
        _auth(x_admin_token)
        m = plugin_manifest.find(plugin_id)
        if m is None:
            raise HTTPException(404, f"No game plugin '{plugin_id}' installed")
        values = body.get("values")
        if not isinstance(values, dict):
            raise HTTPException(400, "values object required")
        fields = {str(f["key"]): ("settings", f) for f in m.get("settings") or []}
        fields.update({str(f["key"]): ("market", f) for f in (m.get("market") or {}).get("fields") or []})
        fields.setdefault("enabled", ("settings", {"key": "enabled", "type": "checkbox"}))
        cfg = getattr(core_state, "config", None) or load_config()
        section = copy.deepcopy(dict(cfg.get(plugin_id) or {}))
        restart = False
        for key, raw in values.items():
            spec = fields.get(str(key))
            if spec is None:
                raise HTTPException(400, f"'{key}' is not a setting of {m.name}")
            where, field = spec
            try:
                value = coerce_plugin_field(field, raw)
            except ValueError as exc:
                raise HTTPException(400, f"{field.get('label') or key}: {exc}") from exc
            if value is _SKIP:
                continue
            if _get_path(section, str(key)) != value and where == "settings":
                restart = True
            _set_path(section, str(key), value)
        cfg = dict(cfg)
        cfg[plugin_id] = section
        core_state.config = cfg
        save_config(cfg)
        _plugins_follow(cfg)
        return {"ok": True, "values": section, "restart_needed": restart}

    @router.post("/market/holding")
    async def market_grant_holding(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        store = _store()
        uid = int(body.get("user_id") or 0)
        symbol = str(body.get("symbol") or "FRG").upper()
        shares = float(body.get("shares") or 0)
        milli = int(round(shares * 1000))
        nxt = await store.adjust_holding(uid, symbol, milli)
        return {"ok": True, "user_id": uid, "symbol": symbol, "milli_shares": nxt}

    @router.post("/market/dividend")
    async def market_test_dividend(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        tape = getattr(core_state, "market", None)
        store = _store()
        symbol = str(body.get("symbol") or "FRG").upper()
        points = int(body.get("points") or 10)
        paid = await store.pay_dividend(symbol, points, "admin-test")
        if tape:
            bump = float((getattr(core_state, "config", {}) or {}).get("market", {}).get("dividend_price_bump", 0.01) or 0)
            tape.apply_return(symbol, bump, reason="admin-test")
            tape.last_dividend = {
                "symbol": symbol, "points": points, "reason": "admin-test",
                "holders": paid.get("holders"), "burned": paid.get("burned"),
            }
        return {"ok": True, "payout": paid}

    @router.post("/market/tickers")
    async def market_create_ticker(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        tape = getattr(core_state, "market", None)
        if tape is None:
            raise HTTPException(503, "Market tape not ready")
        try:
            inst = tape.upsert(
                symbol=str(body.get("symbol") or ""),
                name=str(body.get("name") or body.get("symbol") or ""),
                book=str(body.get("book") or "core"),
                role=str(body.get("role") or "plain"),
                price=float(body.get("price") or body.get("base_price") or 10),
                base_price=float(body.get("base_price") or body.get("price") or 10),
                status="listed",
                feed=body.get("feed"),
                steam_appid=body.get("steam_appid"),
                steam_mode=body.get("steam_mode"),
                chatter_user_id=body.get("chatter_user_id"),
                chatter_link_points=body.get("chatter_link_points"),
                chatter_streak_bonus=body.get("chatter_streak_bonus"),
                chatter_points_scale=body.get("chatter_points_scale"),
                persist=True,
            )
            if inst.get("chatter_user_id") and inst.get("chatter_listed_points") is None:
                store = _store()
                if store:
                    user = await store.get_user(int(inst["chatter_user_id"]))
                    if user:
                        inst["chatter_listed_points"] = int(user.get("points") or 0)
                        scale = float(inst.get("chatter_points_scale") or 10) or 10
                        inst["price"] = max(0.5, inst["chatter_listed_points"] / scale)
                        inst["base_price"] = inst["price"]
                        tape.save_listings()
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "ticker": inst}

    @router.patch("/market/tickers/{symbol}")
    async def market_edit_ticker(
        symbol: str,
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        tape = getattr(core_state, "market", None)
        if tape is None:
            raise HTTPException(503, "Market tape not ready")
        current = tape.quote(symbol)
        if not current:
            raise HTTPException(404, "unknown symbol")
        merged = dict(current)
        merged.update({k: v for k, v in body.items() if v is not None})
        try:
            inst = tape.upsert(
                symbol=current["symbol"],
                name=str(merged.get("name") or current["symbol"]),
                book=str(merged.get("book") or "core"),
                role=str(merged.get("role") or "plain"),
                price=float(current.get("price") or 10),
                base_price=float(merged.get("base_price") or current.get("base_price") or 10),
                min_price=float(merged.get("min_price") or current.get("min_price") or 0.5),
                max_price=float(merged.get("max_price") or current.get("max_price") or 500),
                status=str(merged.get("status") or current.get("status") or "listed"),
                feed=merged.get("feed"),
                steam_appid=merged.get("steam_appid"),
                steam_mode=merged.get("steam_mode"),
                persist=True,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if body.get("price") is not None:
            try:
                inst["price"] = float(body["price"])
            except (TypeError, ValueError):
                pass
        return {"ok": True, "ticker": inst}

    @router.delete("/market/tickers/{symbol}")
    async def market_delist_ticker(
        symbol: str,
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        tape = getattr(core_state, "market", None)
        if tape is None:
            raise HTTPException(503, "Market tape not ready")
        if not tape.delist(symbol):
            raise HTTPException(404, "unknown symbol")
        return {"ok": True, "symbol": symbol.upper(), "status": "delisted"}

    @router.post("/market/steam/poll")
    async def market_steam_poll(x_admin_token: Optional[str] = Header(None)):
        _auth(x_admin_token)
        tape = getattr(core_state, "market", None)
        if tape is None:
            raise HTTPException(503, "Market tape not ready")
        return await tape.poll_steam()

    @router.post("/market/steam/baseline")
    async def market_steam_baseline(
        body: Dict[str, Any] = Body(default={}),
        x_admin_token: Optional[str] = Header(None),
    ):
        _auth(x_admin_token)
        tape = getattr(core_state, "market", None)
        if tape is None:
            raise HTTPException(503, "Market tape not ready")
        inst = tape.quote(str(body.get("symbol") or ""))
        if not inst:
            raise HTTPException(404, "unknown symbol")
        ccu = inst.get("steam_ccu")
        if not ccu:
            raise HTTPException(400, "no CCU sample yet — poll Steam first")
        inst["steam_baseline"] = int(ccu)
        inst["steam_factor"] = 1.0
        tape.save_listings()
        return {"ok": True, "symbol": inst["symbol"], "baseline": int(ccu)}

    return router
