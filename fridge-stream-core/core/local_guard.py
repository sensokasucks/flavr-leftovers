"""
Local-only request guard (CSRF + DNS-rebinding protection).

Binding to 127.0.0.1 keeps other machines out, but any web page open in the
streamer's browser can still send requests to http://127.0.0.1:<port>.
This module blocks that without needing extra config:

  * Host header must be a loopback name (defeats DNS rebinding).
  * State-changing requests (POST/PUT/PATCH/DELETE) that carry a browser
    Origin must come from a loopback origin (our own admin / overlays).
  * WebSocket upgrades with a foreign Origin are refused.

Server-to-server callers (game bridges, httpx, Node fetch) send no Origin
and pass. Extra names can be allowed with ``core.allowed_hosts`` /
``core.allowed_origins`` when someone deliberately runs Core on a LAN IP.

Also resolves the admin token: a placeholder like ``change-me`` is never
accepted — Core generates a random one in ``data/admin_token.txt``.
"""

from __future__ import annotations

import hmac
import logging
import re
import secrets
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlsplit

log = logging.getLogger("core.local_guard")

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PLACEHOLDER_TOKENS = {"", "change-me", "changeme", "your_admin_token", "YOUR_ADMIN_TOKEN"}

# CORS: only our own loopback pages (any port — sibling Fridge apps).
LOOPBACK_ORIGIN_REGEX = r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$"
_LOOPBACK_ORIGIN_RE = re.compile(LOOPBACK_ORIGIN_REGEX, re.IGNORECASE)


def _host_only(value: str) -> str:
    value = (value or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    return value.split(":", 1)[0]


def _norm_list(items: Optional[Iterable]) -> list[str]:
    if not items:
        return []
    if isinstance(items, str):
        items = [items]
    return [str(i).strip().lower().rstrip("/") for i in items if str(i).strip()]


class LocalGuard:
    def __init__(self, config: dict | None = None, section: str = "core"):
        self.section = section
        self.configure(config or {})

    def configure(self, config: dict) -> None:
        # Stream Core keeps host / allow-lists under ``core:``; Chat Credits under ``app:``.
        core = (config or {}).get(self.section) or {}
        extra_hosts = {_host_only(h) for h in _norm_list(core.get("allowed_hosts"))}
        bind = _host_only(str(core.get("host") or "127.0.0.1"))
        self.allowed_hosts = set(LOOPBACK_HOSTS) | extra_hosts
        if bind and bind not in ("0.0.0.0", "::"):
            self.allowed_hosts.add(bind)
        # Bound to all interfaces with no allow-list: we cannot know the LAN
        # name, so skip the Host check (the user opted into LAN exposure).
        self.check_host = not (bind in ("0.0.0.0", "::") and not extra_hosts)
        self.extra_origins = set(_norm_list(core.get("allowed_origins")))

    # ------------------------------------------------------------------
    def host_ok(self, host_header: Optional[str]) -> bool:
        if not self.check_host:
            return True
        return _host_only(host_header or "") in self.allowed_hosts

    def origin_ok(self, origin: Optional[str]) -> bool:
        if origin is None:
            return True  # not a browser (or same-origin GET)
        o = origin.strip().lower().rstrip("/")
        if o in self.extra_origins:
            return True
        if o == "null":
            return False
        if _LOOPBACK_ORIGIN_RE.match(o):
            return True
        parts = urlsplit(o)
        return bool(parts.hostname) and parts.hostname in self.allowed_hosts and self.check_host

    def check(self, method: str, headers) -> Optional[str]:
        """Return a rejection reason, or None when the request may proceed."""
        if not self.host_ok(headers.get("host")):
            return "host not allowed"
        if method.upper() in SAFE_METHODS:
            return None
        origin = headers.get("origin")
        if origin is not None:
            return None if self.origin_ok(origin) else "cross-origin request blocked"
        site = (headers.get("sec-fetch-site") or "").lower()
        if site in ("cross-site", "same-site"):
            return "cross-site request blocked"
        return None

    def check_ws(self, headers) -> Optional[str]:
        if not self.host_ok(headers.get("host")):
            return "host not allowed"
        if not self.origin_ok(headers.get("origin")):
            return "cross-origin websocket blocked"
        return None


class LocalGuardMiddleware:
    """Pure ASGI middleware: ``app.add_middleware(LocalGuardMiddleware, guard=g)``."""

    def __init__(self, app, guard: LocalGuard):
        self.app = app
        self.guard = guard

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers") or []
        }
        if scope["type"] == "websocket":
            reason = self.guard.check_ws(headers)
            if reason:
                log.warning("Refused WebSocket %s (origin=%s host=%s): %s",
                            scope.get("path"), headers.get("origin"), headers.get("host"), reason)
                await send({"type": "websocket.close", "code": 1008})
                return
            return await self.app(scope, receive, send)
        reason = self.guard.check(scope.get("method", "GET"), headers)
        if reason:
            log.warning("Refused %s %s (origin=%s host=%s): %s", scope.get("method"),
                        scope.get("path"), headers.get("origin"), headers.get("host"), reason)
            body = ('{"detail":"%s"}' % reason).encode()
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        return await self.app(scope, receive, send)


# ----------------------------------------------------------------------
# Admin token
# ----------------------------------------------------------------------

def is_placeholder_token(token: Optional[str]) -> bool:
    t = str(token or "").strip()
    return t in PLACEHOLDER_TOKENS or t.lower() in {p.lower() for p in PLACEHOLDER_TOKENS}


def generated_token_path(root: Path) -> Path:
    return Path(root) / "data" / "admin_token.txt"


def resolve_admin_token(config: dict, root: Path, *, create: bool = True) -> str:
    """Config token if it is real, else the generated one in data/admin_token.txt."""
    cfg_token = str(((config or {}).get("points") or {}).get("admin_token") or "").strip()
    if not is_placeholder_token(cfg_token):
        return cfg_token
    path = generated_token_path(root)
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing and not is_placeholder_token(existing):
            return existing
    except OSError:
        pass
    if not create:
        return ""
    token = secrets.token_urlsafe(18)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token + "\n", encoding="utf-8")
    except OSError:
        log.exception("Could not write %s — admin API stays locked", path)
        return ""
    return token


def token_matches(given: Optional[str], expected: str) -> bool:
    if not given or not expected or is_placeholder_token(expected):
        return False
    return hmac.compare_digest(str(given).encode("utf-8"), expected.encode("utf-8"))
