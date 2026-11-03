"""
Phone remote: the streamer's own phones, paired once with a QR code, and the home-network
address they reach Core on.

This file only keeps the list of paired phones and the pairing codes; the web server the phones
talk to is api/phone_server.py (its own port, PHONE_PORT, on the PC's home-network address only,
never on the normal 127.0.0.1:3850 dashboard). Plan: the "Phone Live controls plan" doc.

How pairing works (Setup → Phone remote → Add a phone, admin.js "Phone remote"):
  1. The dashboard asks for a pairing code (``start_pairing``): a 6-digit code plus a long
     one-time link token, both valid for PAIR_SECONDS, for one phone.
  2. The phone scans the QR code (http://<PC address>:3860/phone/#pair=<token>) or types the
     6 digits on the phone page, and gives itself a name.
  3. ``pair`` checks the code and hands the phone its own key (KEY_BYTES of randomness). Only a
     hash of the key is saved (data/phone_remote.json), so the file is no use to anyone who copies it.
  4. The phone sends the key with every call (``X-Phone-Key``). ``check_key`` finds the phone and
     notes when it was last used. **Remove** on the dashboard (``remove``) stops it at once.
A phone key only opens the phone door and its fixed list of Live actions (api/phone_server.py
ALLOWED); it is never the admin token and can't be turned into it.

Wrong codes: each address gets MAX_TRIES wrong tries per pairing code, then waits LOCK_SECONDS;
MAX_CODE_TRIES wrong tries in total throw the code away, so 6 digits can't be guessed.

Settings (config.yaml ``phone_remote:``; Setup → Phone remote card):
  enabled      false by default; the door is closed until the streamer switches it on
  stop_on_exit true: switched off again whenever Core starts, so it never stays open by accident
  host         "" = find the PC's home-network address by itself; or a fixed address like 192.168.1.20
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("core.phone_remote")

# The phone door's port. Fixed like Core's other ports (CLAUDE.md "Ports above are fixed").
PHONE_PORT = 3860
# A pairing code lasts this long (seconds) and works for one phone.
PAIR_SECONDS = 120
# Wrong code tries: per address before a wait, the wait (seconds), and in total before the code is dropped.
MAX_TRIES = 5
LOCK_SECONDS = 300
MAX_CODE_TRIES = 15
# Length of a phone's key, in random bytes (the phone keeps it; Core keeps only its SHA-256).
KEY_BYTES = 32
# Most phones that can be paired at once, and the longest phone name.
MAX_PHONES = 10
NAME_MAX = 40

DEFAULTS: Dict[str, Any] = {"enabled": False, "stop_on_exit": True, "host": ""}


def _hash(key: str) -> str:
    """SHA-256 of a phone key, as hex (what data/phone_remote.json keeps)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def is_home_address(ip: str) -> bool:
    """True for a private home-network address (192.168.x.x, 10.x.x.x, 172.16-31.x.x) or an IPv6
    link-local / unique-local one. The phone door listens only on such an address and answers
    only callers from one, so it can't be reached from the internet even if a router forwards it."""
    try:
        addr = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return False
    if addr.is_loopback or addr.is_unspecified or addr.is_multicast:
        return False
    return addr.is_private or addr.is_link_local


def find_home_address() -> str:
    """The PC's address on the home network, or "" when it has none.

    Asks the system which address it would use to reach an outside address (a UDP "connect"
    sends nothing), then falls back to the PC's other addresses. Only private addresses count.
    """
    candidates: List[str] = []
    for probe in ("192.168.1.1", "10.255.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            candidates.append(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except OSError:
        pass
    for ip in candidates:
        if is_home_address(ip):
            return ip
    return ""


def windows_network_category() -> str:
    """"Private", "Public", "DomainAuthenticated", or "" (not Windows / couldn't tell).

    Windows' firewall lets the phone in only on a network marked Private (the box Windows shows
    the first time Core opens the door says the same). Uses PowerShell's Get-NetConnectionProfile;
    takes about a second, so the dashboard asks for it in a worker thread.
    """
    if sys.platform != "win32":
        return ""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetConnectionProfile | Select-Object -First 1).NetworkCategory"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


class PhoneRemote:
    """Paired phones and pairing codes. One instance on core_state.phone_remote (main.py).

    ``root`` is the Stream Core folder; the list lives in <root>/data/phone_remote.json.
    Thread-safe (the dashboard and the phone door both call it).
    """

    def __init__(self, root: Path, config: Optional[dict] = None):
        self.path = root / "data" / "phone_remote.json"
        self.settings: Dict[str, Any] = dict(DEFAULTS)
        self.phones: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        # the open pairing code: {"code", "token", "until", "tries"} or None
        self._pairing: Optional[Dict[str, Any]] = None
        # address -> {"tries": n, "until": unix seconds locked until}
        self._fails: Dict[str, Dict[str, float]] = {}
        self.configure(config or {})
        self.load()

    # ── settings ──

    def configure(self, config: dict) -> None:
        """Read the ``phone_remote:`` block of the whole config."""
        cfg = (config or {}).get("phone_remote") or {}
        host = str(cfg.get("host") or "").strip()
        self.settings = {
            "enabled": bool(cfg.get("enabled", DEFAULTS["enabled"])),
            "stop_on_exit": bool(cfg.get("stop_on_exit", DEFAULTS["stop_on_exit"])),
            "host": host if (not host or is_home_address(host)) else "",
        }

    def address(self) -> str:
        """The home-network address the door listens on (the fixed ``host``, or found now)."""
        return self.settings.get("host") or find_home_address()

    # ── saved phones ──

    def load(self) -> None:
        """Read data/phone_remote.json; a missing or broken file means no phones."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception:
            log.exception("phone list unreadable: %s", self.path)
            return
        rows = data.get("phones") if isinstance(data, dict) else None
        self.phones = [p for p in (rows or []) if isinstance(p, dict) and p.get("key_hash") and p.get("id")]

    def _save(self) -> None:
        """Write the list (temporary file swapped in, so a crash never leaves half a file)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"phones": self.phones}, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def public_list(self) -> List[Dict[str, Any]]:
        """Phones for the dashboard: id, name, paired and last-used times (never the key hash)."""
        with self._lock:
            return [{"id": p["id"], "name": p.get("name") or "Phone", "created": p.get("created"),
                     "last_used": p.get("last_used"), "last_ip": p.get("last_ip") or ""} for p in self.phones]

    def remove(self, phone_id: str) -> bool:
        """Unpair one phone (its key stops working at once)."""
        with self._lock:
            before = len(self.phones)
            self.phones = [p for p in self.phones if p.get("id") != phone_id]
            if len(self.phones) == before:
                return False
            self._save()
            return True

    # ── pairing ──

    def start_pairing(self) -> Dict[str, Any]:
        """A new pairing code for one phone (any older unused code stops working)."""
        with self._lock:
            self._pairing = {
                "code": f"{secrets.randbelow(1_000_000):06d}",
                "token": secrets.token_urlsafe(18),
                "until": time.time() + PAIR_SECONDS,
                "tries": 0,
            }
            self._fails.clear()
            return {"code": self._pairing["code"], "token": self._pairing["token"],
                    "expires_in": PAIR_SECONDS}

    def cancel_pairing(self) -> None:
        """The dashboard closed the Add a phone box."""
        with self._lock:
            self._pairing = None

    def pairing_open(self) -> bool:
        """True while a pairing code is waiting for a phone."""
        with self._lock:
            return bool(self._pairing and self._pairing["until"] > time.time())

    def pair(self, code: str, token: str, name: str, ip: str) -> Dict[str, Any]:
        """A phone answers with the 6-digit ``code`` or the QR link's ``token``. Returns
        {"ok": True, "key", "id", "name"} or {"ok": False, "error", "wait"}."""
        now = time.time()
        with self._lock:
            f = self._fails.get(ip) or {"tries": 0, "until": 0.0}
            if f["until"] > now:
                return {"ok": False, "error": "Too many wrong codes. Wait a few minutes.", "wait": int(f["until"] - now)}
            p = self._pairing
            if not p or p["until"] <= now:
                return {"ok": False, "error": "No pairing code is open. Press Add a phone on the PC first."}
            good = bool(token) and hmac.compare_digest(str(token), p["token"])
            good = good or (bool(code) and hmac.compare_digest(str(code).strip(), p["code"]))
            if not good:
                p["tries"] += 1
                f["tries"] += 1
                if f["tries"] >= MAX_TRIES:
                    f = {"tries": 0, "until": now + LOCK_SECONDS}
                self._fails[ip] = f
                if p["tries"] >= MAX_CODE_TRIES:
                    self._pairing = None
                    log.warning("Phone pairing code dropped after %s wrong tries", MAX_CODE_TRIES)
                return {"ok": False, "error": "That code isn't right."}
            if len(self.phones) >= MAX_PHONES:
                return {"ok": False, "error": f"{MAX_PHONES} phones are paired already. Remove one on the PC first."}
            key = secrets.token_urlsafe(KEY_BYTES)
            phone = {
                "id": secrets.token_hex(6),
                "name": " ".join(str(name or "").split())[:NAME_MAX] or "Phone",
                "key_hash": _hash(key),
                "created": now,
                "last_used": now,
                "last_ip": ip,
            }
            self.phones.append(phone)
            self._pairing = None
            self._fails.pop(ip, None)
            self._save()
        log.info("Phone paired: %s (%s)", phone["name"], ip)
        return {"ok": True, "key": key, "id": phone["id"], "name": phone["name"]}

    def check_key(self, key: Optional[str], ip: str = "") -> Optional[Dict[str, Any]]:
        """The paired phone that owns ``key``, or None. Notes when it was last used (saved at most
        once a minute, so a phone polling every 2 s doesn't write the file every time)."""
        if not key:
            return None
        h = _hash(str(key))
        with self._lock:
            for p in self.phones:
                if hmac.compare_digest(p["key_hash"], h):
                    now = time.time()
                    stale = now - float(p.get("last_used") or 0) > 60
                    p["last_used"] = now
                    if ip:
                        p["last_ip"] = ip
                    if stale:
                        try:
                            self._save()
                        except Exception:
                            log.exception("phone list save failed")
                    return p
        return None
