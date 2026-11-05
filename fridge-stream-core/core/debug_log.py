"""
Troubleshooting log files: one cleaned log per Core run, safe to send to someone helping.

Where: ``data/logs_to_share/stream_core_<date>_<time>.log`` (inside the fridge-stream-core
folder, next to the rest of Core's files). The dashboard's Setup > Core > Advanced page has the
"Log files for troubleshooting" card (admin/admin.js renderLogFiles, api/log_routes.py): an on/off
tick, the list of files with Download buttons, and Open log folder. The same card also lists the
Stream Rooms logs on this PC (that app writes its own cleaned files, autoload/debug_log.gd there).

What goes in: a header (Python, Windows version, which platforms and plugins are on), then every
log line from every part of Core at DEBUG level (more than the console shows), except the
per-chat-message lines (CHAT_LINE_FORMATS: a busy chat would bury everything else) and the
noisiest library loggers (QUIET_LOGGERS). Uncaught errors in threads and a hard crash's
Python stack (faulthandler) end up in it too; the crash stack is written raw to
data/.crash_trace.txt and cleaned into the next run's log.

What is taken out (Cleaner.clean): IP addresses (numbered tags like <ip-home#1>, the same
address keeps its tag all run), the Windows user and computer name, user / Documents / Core
folders, every token, secret, key and password in config.yaml, keys and tokens in links,
Cloudflare tunnel names, e-mail addresses. Chatter names stay: they are needed to follow what
happened and are public on stream anyway. Stream Rooms' cleaner (autoload/debug_log.gd) uses the
same rules and tags: change both together.

Switched by ``core.log_files`` (default true, core/config.py DEFAULTS). main.py calls
``start(config, ROOT)`` right after logging.basicConfig and ``stop()`` when Core shuts down.
"""

from __future__ import annotations

import faulthandler
import ipaddress
import logging
import logging.handlers
import os
import platform
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("core.debug_log")

# Folder inside data/ (the dashboard card and README say this name).
FOLDER = "logs_to_share"
# How many runs' files are kept; older ones are deleted when Core starts.
KEEP_FILES = 15
# One run's file rolls over to "<name>.1" at this size (bytes), keeping one older part, so a
# runaway error loop can't fill the disk.
MAX_BYTES = 20 * 1024 * 1024
# The DEBUG lines each chat message makes (adapters/kick.py, twitch.py, youtube.py). Left out of
# the file: on a busy chat they'd be most of it, and the chat history is in the dashboard anyway.
CHAT_LINE_FORMATS = {"[Kick] %s: %s", "[Twitch] %s: %s", "[YouTube] %s: %s"}
# Library loggers that would flood the file at DEBUG; only their warnings and errors go in.
QUIET_LOGGERS = ("httpx", "httpcore", "websockets", "asyncio", "uvicorn.access", "multipart",
                 "PIL", "urllib3", "hpack", "charset_normalizer", "watchfiles")
# Config keys whose values are hidden wherever they turn up in a log line (matched as a part of
# the key name, so "client_secret", "admin_token", "api_key" all count).
SECRET_KEY_WORDS = ("token", "secret", "password", "api_key", "apikey", "key")
# Home-network address ranges (a router hands these out), tagged <ip-home#n>. Same as Stream
# Rooms' _ip4_tag.
HOME_NETWORKS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
# Values shorter than this aren't treated as secrets (a 2-letter value would hide ordinary words).
MIN_SECRET_LEN = 6

_handler: Optional[logging.Handler] = None
_marker: Optional[Path] = None
_crash_file = None             # the open file faulthandler writes a hard crash's stack into
_path: Optional[Path] = None   # this run's log file


# ── Cleaning ────────────────────────────────────────────────────────────────
class Cleaner:
    """Swaps private details in a line of text for <tags>. One per run (the IP tags are numbered
    in the order addresses first appear). Thread-safe."""

    def __init__(self, root: Path, secrets: List[str] = ()):
        self._lock = threading.Lock()
        self._ip_tags: Dict[str, str] = {}
        known: Dict[str, str] = {}

        def add(text: str, tag: str) -> None:
            text = (text or "").strip().rstrip("\\/")
            if len(text) < 4:
                return
            for variant in (text, text.replace("\\", "/"), text.replace("/", "\\")):
                known[variant] = tag

        add(str(root), "<core folder>")
        add(str(Path(root).parent), "<workshop folder>")
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())
        add(os.path.join(home, "Documents"), "<documents>")
        add(os.path.join(home, "Desktop"), "<desktop>")
        add(os.path.join(home, "Downloads"), "<downloads>")
        add(os.environ.get("OneDrive", ""), "<onedrive>")
        add(os.environ.get("APPDATA", ""), "<appdata>")
        add(os.environ.get("LOCALAPPDATA", ""), "<localappdata>")
        add(home, "<home>")
        # longest first, so C:\Users\me\Documents wins over C:\Users\me
        self._known: List[Tuple[re.Pattern, str]] = [
            (re.compile(re.escape(k), re.IGNORECASE), v)
            for k, v in sorted(known.items(), key=lambda kv: -len(kv[0]))
        ]
        self._secrets: List[Tuple[re.Pattern, str]] = [
            (re.compile(re.escape(s)), "<hidden>")
            for s in sorted({s for s in secrets if s and len(s) >= MIN_SECRET_LEN}, key=len, reverse=True)
        ]
        words = []
        for env in ("USERNAME", "USER", "COMPUTERNAME", "USERDOMAIN"):
            w = (os.environ.get(env) or "").strip()
            if len(w) >= 3:
                words.append((re.compile(r"(?<!\w)" + re.escape(w) + r"(?!\w)", re.IGNORECASE),
                              "<pc>" if env in ("COMPUTERNAME", "USERDOMAIN") else "<user>"))
        self._patterns: List[Tuple[re.Pattern, str]] = words + [
            # any Windows / Mac / Linux user folder (a name may have spaces when a folder follows)
            (re.compile(r"(?i)([A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+)(?:[^\\/\"'<>|\r\n]+(?=[\\/])|[^\\/\s\"'<>|]+)"), r"\1<user>"),
            (re.compile(r"(/(?:home|Users)/)[^/\s\"'<>]+"), r"\1<user>"),
            # secrets in links and text: key=..., token=..., oauth:..., Bearer ...
            (re.compile(r"(?i)\b((?:access_|refresh_|id_|run_|ws_|client_)?(?:token|key|password|passwd|pwd|pass|secret|auth|code|sig|signature|nonce|proof)=)[^&\s\"'<>]+"), r"\1<hidden>"),
            (re.compile(r"(?i)\b(oauth:)[a-z0-9]+"), r"\1<hidden>"),
            (re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1<hidden>"),
            (re.compile(r"(?i)\b(X-Admin-Token[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"), r"\1<hidden>"),
            (re.compile(r"(?i)\b(#token=)[^\s\"'&]+"), r"\1<hidden>"),
            (re.compile(r"(?i)\b[a-z0-9-]+\.trycloudflare\.com"), "<tunnel>.trycloudflare.com"),
            (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "<email>"),
        ]
        self._ip4 = re.compile(r"(?<![\w.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\w.]*\d)")
        self._ip6 = re.compile(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?:%\w+)?(?![\w:])")

    def clean(self, text: str) -> str:
        """``text`` with the private details replaced (see the module comment)."""
        out = str(text)
        for pat, tag in self._secrets:
            out = pat.sub(tag, out)
        for pat, tag in self._known:
            out = pat.sub(lambda _m, t=tag: t, out)
        for pat, tag in self._patterns:
            out = pat.sub(tag, out)
        out = self._ip4.sub(self._ip4_tag, out)
        return self._ip6.sub(self._ip6_tag, out)

    def _ip4_tag(self, m: re.Match) -> str:
        """IPv4: this PC (127.x) and "any" (0.0.0.0) stay; others get a tag saying what kind."""
        parts = [int(p) for p in m.groups()]
        if any(p > 255 for p in parts):
            return m.group(0)
        if parts[0] == 127 or m.group(0) in ("0.0.0.0", "255.255.255.255"):
            return m.group(0)
        addr = ipaddress.ip_address(m.group(0))
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            kind = "ip-tailscale"
        elif any(addr in ipaddress.ip_network(n) for n in HOME_NETWORKS):
            kind = "ip-home"
        else:
            kind = "ip"
        return self._tag(m.group(0), kind)

    def _ip6_tag(self, m: re.Match) -> str:
        """IPv6 (and MAC-style) addresses: "::1" stays; anything with "::", 5+ colons or a hex
        letter gets a tag. A clock time (18:12:09) has none of those."""
        s = m.group(0)
        if s in ("::1", "::") or len(s) < 5:
            return s
        bare = s.split("%")[0]
        colons = s.count(":")
        has_letter = any(c in "abcdefABCDEF" for c in bare)
        if not ("::" in s or colons >= 5 or (has_letter and colons >= 2)):
            return s
        return self._tag(bare.lower(), "ip6")

    def _tag(self, address: str, kind: str) -> str:
        with self._lock:
            if address not in self._ip_tags:
                self._ip_tags[address] = f"<{kind}#{len(self._ip_tags) + 1}>"
            return self._ip_tags[address]


def secrets_in(config: Any) -> List[str]:
    """Every string value in ``config`` whose key looks secret (SECRET_KEY_WORDS), at any depth."""
    out: List[str] = []

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k).lower())
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and any(w in key for w in SECRET_KEY_WORDS):
            out.append(node.strip())

    walk(config)
    return out


class CleanFormatter(logging.Formatter):
    """The usual "time [LEVEL] name: message" (with the date: logs are compared across days),
    tracebacks included, then cleaned."""

    def __init__(self, cleaner: Cleaner):
        super().__init__("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
        self.cleaner = cleaner

    def format(self, record: logging.LogRecord) -> str:
        return self.cleaner.clean(super().format(record))


class FileFilter(logging.Filter):
    """Keeps per-chat-message lines and library chatter (below WARNING) out of the file."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            if record.msg in CHAT_LINE_FORMATS:
                return False
            if record.name.startswith(QUIET_LOGGERS):
                return False
        return True


# ── Files ───────────────────────────────────────────────────────────────────
def folder(root: Path) -> Path:
    """data/logs_to_share under the fridge-stream-core folder (made if missing)."""
    path = Path(root) / "data" / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def rooms_folder() -> Optional[Path]:
    """Stream Rooms' own logs_to_share folder on this PC, or None. Redot keeps a project's files
    in %APPDATA%\\Redot\\app_userdata\\<project name>; the editor and the exported app share it."""
    appdata = os.environ.get("APPDATA")
    candidates = []
    if appdata:
        candidates.append(Path(appdata) / "Redot" / "app_userdata" / "Stream Rooms" / FOLDER)
    candidates.append(Path.home() / ".local" / "share" / "redot" / "app_userdata" / "Stream Rooms" / FOLDER)
    for c in candidates:
        if c.is_dir():
            return c
    return None


def list_files(directory: Optional[Path], prefix: str) -> List[Dict[str, Any]]:
    """The log files in ``directory`` (names starting with ``prefix``), newest first:
    [{name, size (bytes), modified (unix seconds)}]."""
    if directory is None or not directory.is_dir():
        return []
    out = []
    for p in directory.iterdir():
        if p.is_file() and p.name.startswith(prefix) and (p.name.endswith(".log") or p.name.endswith(".log.1")):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "modified": int(st.st_mtime)})
    out.sort(key=lambda f: f["name"], reverse=True)
    return out


def _prune(directory: Path) -> None:
    """Deletes the oldest runs so at most KEEP_FILES - 1 remain (this run makes the next one)."""
    runs = sorted(p for p in directory.glob("stream_core_*.log"))
    for old in runs[: max(0, len(runs) - (KEEP_FILES - 1))]:
        for p in (old, old.with_name(old.name + ".1")):
            try:
                p.unlink()
            except OSError:
                pass


def _version(root: Path) -> str:
    """The newest released version named in CHANGELOG.md ("## [2026.11.4] ..."), or "?"."""
    try:
        for line in (Path(root) / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
            m = re.match(r"##\s*\[([^\]]+)\]", line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return "?"


def _header(config: Dict[str, Any], root: Path) -> List[str]:
    """What someone helping asks first: versions, system, what's switched on."""
    on = [p for p in ("kick", "twitch", "youtube") if (config.get(p) or {}).get("enabled")]
    plugins_dir = Path(root) / "plugins"
    plugins = sorted(p.name for p in plugins_dir.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))) \
        if plugins_dir.is_dir() else []
    core = config.get("core") or {}
    return [
        "=== Stream Core log for troubleshooting ===",
        f"Started:    {time.strftime('%Y-%m-%d %H:%M:%S')} (local time), UTC{time.strftime('%z')}",
        f"Core:       {_version(root)} (newest version in CHANGELOG.md)",
        f"Python:     {platform.python_version()} ({platform.architecture()[0]})",
        f"System:     {platform.platform()}, {os.cpu_count()} threads",
        f"Chat:       {', '.join(on) if on else 'no platform on'}",
        f"Plugins:    {', '.join(plugins) if plugins else 'none installed'}",
        f"Server:     {core.get('host', '127.0.0.1')}:{core.get('port', 3850)}, console log level {core.get('log_level', 'INFO')}, "
        f"phone remote {'on' if (config.get('phone_remote') or {}).get('enabled') else 'off'}",
        "(IP addresses, user and computer names, personal folders, tokens and keys are replaced with <tags>.)",
        "",
    ]


def start(config: Dict[str, Any], root: Path) -> Optional[Path]:
    """Starts this run's log file (if core.log_files is on). Returns its path, or None.

    Called once by main.py's _run() right after logging.basicConfig. Lowers the root logger to
    DEBUG so the file gets the detail, and keeps the console at core.log_level by setting that
    level on the console handlers basicConfig made."""
    global _handler, _marker, _crash_file, _path
    if _handler is not None:
        return _path
    root = Path(root)
    directory = folder(root)
    _marker = directory.parent / ".core_running"
    crashed = _marker.exists()
    crash_trace = directory.parent / ".crash_trace.txt"
    old_trace = ""
    try:
        old_trace = crash_trace.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pass
    if not (config.get("core") or {}).get("log_files", True):
        _clear_marker()
        return None

    _prune(directory)
    _path = directory / time.strftime("stream_core_%Y-%m-%d_%H-%M-%S.log")
    cleaner = Cleaner(root, secrets_in(config) + _token_files(root))
    root_log = logging.getLogger()
    console_level = root_log.level
    for h in root_log.handlers:
        if h.level == logging.NOTSET:
            h.setLevel(console_level)   # the console keeps the configured level
    root_log.setLevel(logging.DEBUG)
    for name in QUIET_LOGGERS:
        lg = logging.getLogger(name)
        if lg.level == logging.NOTSET:
            lg.setLevel(logging.INFO)
    with open(_path, "w", encoding="utf-8") as f:
        f.write(cleaner.clean("\n".join(_header(config, root))) + "\n")
        if crashed:
            f.write("!!! The last run didn't close normally (a crash, or its window was closed with X).\n")
        if crashed and old_trace:
            f.write("!!! Python's crash report from the last run:\n")
            for line in old_trace.splitlines()[-200:]:
                f.write("  |  " + cleaner.clean(line) + "\n")
    # (made after the header is written, so the handler appends below it)
    handler = logging.handlers.RotatingFileHandler(_path, maxBytes=MAX_BYTES, backupCount=1, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(CleanFormatter(cleaner))
    handler.addFilter(FileFilter())
    handler.cleaner = cleaner  # (tests read it)
    root_log.addHandler(handler)
    _handler = handler

    try:
        _marker.write_text(_path.name, encoding="utf-8")
    except OSError:
        pass
    # a hard crash (inside a C library) skips Python's logging: faulthandler writes the stack
    # raw into crash_trace, and the next start cleans it into its log (above)
    try:
        _crash_file = open(crash_trace, "w", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        _crash_file = None
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    log.info("Troubleshooting log: %s", _path.name)
    return _path


def attach(logger_name: str) -> None:
    """Also send a logger that doesn't pass its lines up to the root logger into the file.
    main.py calls it for "uvicorn" (uvicorn sets up its own console handlers, propagate off), so
    a "port already in use" at start-up lands in the log too."""
    if _handler is not None:
        lg = logging.getLogger(logger_name)
        if _handler not in lg.handlers:
            lg.addHandler(_handler)


def _token_files(root: Path) -> List[str]:
    """Tokens Core keeps outside config.yaml (generated admin token, sign-in files)."""
    out: List[str] = []
    data = Path(root) / "data"
    try:
        out.append((data / "admin_token.txt").read_text(encoding="utf-8").strip())
    except OSError:
        pass
    import json
    for name in ("twitch_auth.json", "kick_auth.json", "youtube_auth.json"):
        try:
            out.extend(secrets_in(json.loads((data / name).read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            pass
    return out


def _excepthook(kind, value, tb) -> None:
    """An error nothing caught on the main thread: into the log (cleaned), then the usual print."""
    logging.getLogger("core").critical("Uncaught error", exc_info=(kind, value, tb))
    sys.__excepthook__(kind, value, tb)


def _thread_excepthook(args) -> None:
    """The same for other threads (threading.excepthook)."""
    if args.exc_type is SystemExit:
        return
    logging.getLogger("core").critical("Uncaught error in thread %s", getattr(args.thread, "name", "?"),
                                       exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _clear_marker() -> None:
    if _marker is not None:
        try:
            _marker.unlink()
        except OSError:
            pass


def stop() -> None:
    """Core is closing normally (or restarting): last line, crash catcher off, marker removed.
    main.py calls this at the end of _run(); a restart re-starts Python (os.execv), which skips
    atexit, so it can't wait for that."""
    global _handler, _crash_file
    _clear_marker()
    if _crash_file is not None:
        try:
            faulthandler.disable()
            _crash_file.close()
            Path(_crash_file.name).unlink()
        except Exception:
            pass
        _crash_file = None
    if _handler is not None:
        log.info("Core closing normally")
        logging.getLogger().removeHandler(_handler)
        logging.getLogger("uvicorn").removeHandler(_handler)
        _handler.close()
        _handler = None


def current_path() -> Optional[Path]:
    """This run's log file, or None while the log is off."""
    return _path if _handler is not None else None
