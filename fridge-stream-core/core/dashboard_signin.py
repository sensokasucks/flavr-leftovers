"""
Getting into the dashboard without handling the admin token by hand.

The admin token is the dashboard's password (points.admin_token, or the random one in
data/admin_token.txt, see core/local_guard.py). Beginners shouldn't have to find it, so Core
offers three easier ways in. All three are in checklists/admin-hub.md:

  1. Sign-in shortcuts. At every start main.announce_dashboard() writes the signed-in link
     (``/admin/#token=...``) to data/Open dashboard.url and, when this Core sits in the workshop
     folder (next to "START Stream Core.bat"), also to "Open Stream Core dashboard.url" beside that
     .bat, where people actually look. Both hold the token, so both are git-ignored.
  2. Opening the dashboard at start. main._run() opens the signed-in link when core.open_dashboard
     is on, and also, whatever that setting says, until a browser on this PC has signed in once
     (the marker file below). So the first start after the install wizard always lands signed in.
  3. "Sign in on this PC" on the token box (admin.js signInHere -> POST /api/admin/sign-in-here in
     api/admin_routes.py). It hands the token only to Core's own dashboard page on this PC; see
     sign_in_here_problem() for the checks. Anything that can make that request can already read
     data/admin_token.txt, so it opens no new door.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from core.local_guard import LOOPBACK_HOSTS, _host_only

log = logging.getLogger("core.dashboard_signin")

# The shortcut in Core's data folder (old name, kept so older notes and the wizard text still work).
DATA_SHORTCUT = "Open dashboard.url"
# The shortcut beside the workshop's start file. Its name must match .gitignore and the .bat texts.
WORKSHOP_SHORTCUT = "Open Stream Core dashboard.url"
# The workshop start file: when it sits in the folder above Core, that folder gets WORKSHOP_SHORTCUT.
WORKSHOP_START = "START Stream Core.bat"
# Written (empty) the first time any admin call succeeds: from then on core.open_dashboard decides.
SIGNED_IN_MARKER = "dashboard_signed_in"


def write_shortcuts(root: Path, link: str) -> list[Path]:
    """Write the signed-in link as Windows .url shortcuts; returns the files written.

    root: Core's folder (main.ROOT). Always data/Open dashboard.url; also the workshop one when
    "START Stream Core.bat" is in root's parent. A file that can't be written is logged and skipped.
    """
    body = f"[InternetShortcut]\r\nURL={link}\r\n"
    targets = [root / "data" / DATA_SHORTCUT]
    if (root.parent / WORKSHOP_START).is_file():
        targets.append(root.parent / WORKSHOP_SHORTCUT)
    written: list[Path] = []
    for path in targets:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            written.append(path)
        except OSError:
            log.warning("Could not write %s", path)
    return written


def _marker(root: Path) -> Path:
    return root / "data" / SIGNED_IN_MARKER


def has_signed_in(root: Path) -> bool:
    """True once a browser on this PC has used the dashboard (see mark_signed_in)."""
    return _marker(root).exists()


_marked = False


def mark_signed_in(root: Path) -> None:
    """Note that the dashboard has been used. Called by admin_routes._auth on every good token,
    so it only touches the disk the first time per run."""
    global _marked
    if _marked:
        return
    _marked = True
    path = _marker(root)
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("The dashboard has signed in on this PC. Delete this file to have Core open it at the next start.\n",
                        encoding="utf-8")
    except OSError:
        log.debug("Could not write %s", path, exc_info=True)


def should_open_at_start(config: dict, root: Path) -> bool:
    """main._run(): open the signed-in dashboard now? core.open_dashboard, or never signed in yet."""
    if bool((config.get("core") or {}).get("open_dashboard")):
        return True
    return not has_signed_in(root)


def sign_in_here_problem(client_host: str, headers) -> Optional[str]:
    """Why POST /api/admin/sign-in-here must not hand out the token, or None when it may.

    client_host: the connection's address (request.client.host). headers: the request headers.
    Rules: the connection comes from this PC; Origin is present and is exactly this server
    (scheme://Host) so only Core's own pages can read the answer (sibling apps on other loopback
    ports, which Core's CORS otherwise trusts, are refused); a browser that says the call is not
    same-origin (Sec-Fetch-Site) is refused. The local guard middleware already checked Host.
    """
    host = (client_host or "").strip().lower()
    if host not in LOOPBACK_HOSTS and host not in ("::ffff:127.0.0.1",):
        return "Only a browser on the PC that runs Stream Core can sign in this way."
    origin = (headers.get("origin") or "").strip().lower()
    own = (headers.get("host") or "").strip().lower()
    if not origin or not own:
        return "Open the dashboard page itself and press the button there."
    parts = urlsplit(origin)
    if parts.netloc != own or _host_only(own) not in LOOPBACK_HOSTS:
        return "Only Stream Core's own dashboard page can sign in this way."
    site = (headers.get("sec-fetch-site") or "").strip().lower()
    if site and site != "same-origin":
        return "Only Stream Core's own dashboard page can sign in this way."
    return None
