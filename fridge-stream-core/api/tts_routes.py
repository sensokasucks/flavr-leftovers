"""
Text-to-speech API: /api/admin/tts* (admin token, like every /api/admin route).

The dashboard's Setup -> Read aloud (TTS) page (admin/tts.js) and the Live controls card
("Read aloud") call these. They drive core/tts.py TtsEngine (core_state.tts, made by main.py).

Routes:
  GET  /api/admin/tts                 settings (API key hidden), status, missed list, recent lines
  PUT  /api/admin/tts/settings        the tts: block of config.yaml (merged; see below)
  POST /api/admin/tts/check           Check connection: one short line, timed, + the voice list
  GET  /api/admin/tts/voices          the server's voice list (servers with GET /v1/audio/voices)
  POST /api/admin/tts/test            {text, voice} -> the audio itself (plays in the dashboard)
  POST /api/admin/tts/say             {text, voice} -> through the filters + queue to the overlay
  POST /api/admin/tts/filter-test     {text, name} -> what would be read, or why not
  POST /api/admin/tts/fake            {kind: "command" | "chat", text, name, who} a pretend chatter
  POST /api/admin/tts/skip            stop the line playing now
  POST /api/admin/tts/clear           stop it and drop everything waiting (refunds !tts points)
  POST /api/admin/tts/pretend-down    {on} the "Pretend the server is down" test switch
  POST /api/admin/tts/missed/replay   {id} one missed line back in the queue (no id = all)
  POST /api/admin/tts/missed/remove   {id} drop one missed line (no id = all)

Mounted by api/server.py next to create_highlight_router.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

from core.config import load_config, save_config
from core.local_guard import resolve_admin_token, token_matches
from core.tts import TRIGGERS, TtsError, read_settings

log = logging.getLogger("api.tts")

# Longest line the test boxes accept (characters).
TEST_MAX = 1000


def public_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Settings for the dashboard: the API key itself never leaves Core, only whether one is set."""
    out = copy.deepcopy(settings)
    out["server"]["api_key_set"] = bool(out["server"].pop("api_key", ""))
    return out


def merge_settings(old: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """The saved ``tts:`` block after a dashboard save: ``body`` laid over ``old`` key by key.
    The API key is only changed when ``server.api_key`` is sent (typed in), and cleared with
    ``server.api_key_clear``; ``api_key_set`` (what GET sends) is never stored."""
    out = copy.deepcopy(old or {})
    for key, value in (body or {}).items():
        if key == "server" and isinstance(value, dict):
            srv = dict(out.get("server") or {})
            for k, v in value.items():
                if k in ("api_key_set", "api_key_clear"):
                    continue
                if k == "api_key" and not str(v or "").strip():
                    continue
                srv[k] = v
            if value.get("api_key_clear"):
                srv["api_key"] = ""
            out["server"] = srv
        elif key in ("filters", "triggers") and isinstance(value, dict):
            section = dict(out.get(key) or {})
            for k, v in value.items():
                section[k] = {**(section.get(k) or {}), **v} if isinstance(v, dict) and key == "triggers" else v
            out[key] = section
        else:
            out[key] = value
    return out


def create_tts_router(core_state, core_root) -> APIRouter:
    """Build the /api/admin/tts routes around ``core_state`` (api/server.py calls this once).
    ``core_root`` is the Stream Core folder (for data/admin_token.txt)."""
    router = APIRouter(prefix="/api/admin/tts", tags=["tts"])

    def _auth(token: Optional[str]) -> None:
        """401 unless ``token`` is the admin token (same rule as api/admin_routes.py _auth)."""
        expected = resolve_admin_token(core_state.config or {}, core_root)
        if not token_matches(token, expected):
            raise HTTPException(401, "Invalid or missing X-Admin-Token")

    def _tts():
        """The TtsEngine, or 503 while Core is still starting."""
        engine = getattr(core_state, "tts", None)
        if engine is None:
            raise HTTPException(503, "Text-to-speech not ready")
        return engine

    def _text(body: Dict[str, Any], key: str = "text") -> str:
        text = " ".join(str(body.get(key) or "").split())[:TEST_MAX]
        if not text:
            raise HTTPException(400, "Type something to read first")
        return text

    def _state(engine) -> Dict[str, Any]:
        return {"settings": public_settings(engine.settings), "status": engine.status(),
                "missed": list(reversed(engine.missed)), "recent": list(reversed(engine.recent))}

    @router.get("")
    async def tts_state(x_admin_token: Optional[str] = Header(None)):
        """Everything the settings page and the Live card show."""
        _auth(x_admin_token)
        return _state(_tts())

    @router.put("/settings")
    async def tts_save(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Save the tts: block (merged into the live config, other blocks untouched). The
        highlight trigger's switch is also written to highlight.read_aloud, its older home."""
        _auth(x_admin_token)
        engine = _tts()
        cfg = getattr(core_state, "config", None) or load_config()
        merged = merge_settings(cfg.get("tts") or {}, body)
        clean = read_settings({**cfg, "tts": merged})
        # store the cleaned values (unknown keys dropped), keeping the key only when one is set
        cfg["tts"] = clean
        hl = dict(cfg.get("highlight") or {})
        hl["read_aloud"] = clean["triggers"]["highlight"]["enabled"]
        cfg["highlight"] = hl
        core_state.config = cfg
        save_config(cfg)
        highlights = getattr(core_state, "highlights", None)
        if highlights is not None:
            highlights.configure(cfg)
        return _state(engine)

    @router.post("/check")
    async def tts_check(x_admin_token: Optional[str] = Header(None)):
        """Check connection: answered or not, seconds, format, voices."""
        _auth(x_admin_token)
        engine = _tts()
        result = await engine.check()
        return {**result, "status": engine.status()}

    @router.get("/voices")
    async def tts_voices(x_admin_token: Optional[str] = Header(None)):
        """The server's voice names ([] when it doesn't list them)."""
        _auth(x_admin_token)
        return {"voices": await _tts().list_voices()}

    @router.post("/test")
    async def tts_test(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Test voice: the audio straight back, so the dashboard plays it without OBS."""
        _auth(x_admin_token)
        try:
            audio, ctype = await _tts().test_audio(_text(body), str(body.get("voice") or "").strip()[:100])
        except TtsError as e:
            raise HTTPException(502, str(e))
        return Response(content=audio, media_type=ctype or "audio/mpeg", headers={"Cache-Control": "no-store"})

    @router.post("/say")
    async def tts_say(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Send to overlay: the line goes through the filters and the real queue."""
        _auth(x_admin_token)
        engine = _tts()
        ok, why = await engine.say_test(_text(body), str(body.get("voice") or "").strip()[:100])
        if not ok:
            raise HTTPException(400, why)
        return {"ok": True, "status": engine.status()}

    @router.post("/filter-test")
    async def tts_filter_test(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Blocked words test: what would be read aloud, or why the line is skipped."""
        _auth(x_admin_token)
        return _tts().filter_test(_text(body), " ".join(str(body.get("name") or "").split())[:60])

    @router.post("/fake")
    async def tts_fake(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """A pretend chatter's !tts or chat line, to check the who / cooldown / 1-in-N rules.
        Nothing reaches the platform's chat; a fake !tts costs no points (the answer says what
        it would cost). ``who`` = everyone | sub | vip | mod (what the pretend chatter is)."""
        _auth(x_admin_token)
        from core.models import ChatEvent, ChatUser, Platform

        engine = _tts()
        kind = str(body.get("kind") or "command")
        name = " ".join(str(body.get("name") or "TestViewer").split())[:40] or "TestViewer"
        rank = str(body.get("who") or "everyone").lower()
        user = ChatUser(platform=Platform.TWITCH, id="tts-test-" + name.lower(), username=name, display_name=name,
                        is_mod=rank == "mod", is_vip=rank == "vip", is_subscriber=rank == "sub")
        text = _text(body)
        if kind == "command":
            word = engine.settings["triggers"]["command"]["word"]
            prefix = engine.prefix() or "!"
            if not text.startswith(prefix):
                text = f"{prefix}{word} {text}"
            event = ChatEvent(platform=Platform.TWITCH, user=user, message=text)
            taken, answer = await engine.handle_command(event, dry_points=True)
            if not taken:
                return {"ok": False, "answer": "", "why": "The !tts command is off (or TTS is off)."}
            return {"ok": True, "answer": answer, "status": engine.status()}
        event = ChatEvent(platform=Platform.TWITCH, user=user, message=text)
        read = engine.on_chat(event)
        why = "" if read else "Not read: the chat trigger is off, the chatter isn't in its group, it isn't their turn (1 in N), it's too soon after the last one, or the line was filtered."
        return {"ok": read, "answer": "", "why": why, "status": engine.status()}

    @router.post("/skip")
    async def tts_skip(x_admin_token: Optional[str] = Header(None)):
        """Stop the line playing now; the next one goes on."""
        _auth(x_admin_token)
        engine = _tts()
        await engine.skip()
        return {"ok": True, "status": engine.status()}

    @router.post("/clear")
    async def tts_clear(x_admin_token: Optional[str] = Header(None)):
        """Stop the line playing and drop everything waiting."""
        _auth(x_admin_token)
        engine = _tts()
        dropped = await engine.clear()
        return {"ok": True, "dropped": dropped, "status": engine.status()}

    @router.post("/pretend-down")
    async def tts_pretend(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """The test switch: Core acts as if every server call failed (not saved)."""
        _auth(x_admin_token)
        engine = _tts()
        engine.set_pretend_down(bool(body.get("on")))
        return {"ok": True, "status": engine.status()}

    def _missed_id(body: Dict[str, Any]) -> Optional[int]:
        if body.get("id") in (None, ""):
            return None
        try:
            return int(body["id"])
        except (TypeError, ValueError):
            raise HTTPException(400, "id must be a number")

    @router.post("/missed/replay")
    async def tts_replay(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Missed lines back in the queue (one by id, or all)."""
        _auth(x_admin_token)
        engine = _tts()
        if not engine.settings["enabled"]:
            raise HTTPException(400, "Text-to-speech is off: switch it on first.")
        n = await engine.replay(_missed_id(body))
        return {"ok": True, "replayed": n, **_state(engine)}

    @router.post("/missed/remove")
    async def tts_missed_remove(body: Dict[str, Any] = Body(default={}), x_admin_token: Optional[str] = Header(None)):
        """Drop missed lines (one by id, or all)."""
        _auth(x_admin_token)
        engine = _tts()
        n = engine.forget_missed(_missed_id(body))
        return {"ok": True, "removed": n, **_state(engine)}

    return router


__all__ = ["create_tts_router", "merge_settings", "public_settings", "TRIGGERS"]
