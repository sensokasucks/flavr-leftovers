"""YouTube author photos for chat (``ChatUser.profile_image_url``).

InnerTube renderers carry ``authorPhoto.thumbnails`` (32/64 px); the official API
carries ``authorDetails.profileImageUrl``. Google photo URLs take a size suffix
(``=s64-...``), so we ask for 128 px, which stays sharp in overlays and Stream Rooms.
"""

from __future__ import annotations

import re
from typing import Any

_SIZE_RE = re.compile(r"=s\d+(-|$)")


def best_photo(node: Any, size: int = 128) -> str:
    """``authorPhoto`` dict (or a plain URL) -> one https URL, "" if none."""
    url = ""
    if isinstance(node, str):
        url = node
    elif isinstance(node, dict):
        thumbs = [t for t in node.get("thumbnails") or [] if isinstance(t, dict) and t.get("url")]
        if thumbs:
            url = max(thumbs, key=lambda t: int(t.get("width") or 0))["url"]
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if "ggpht.com" in url or "googleusercontent.com" in url:
        url = _SIZE_RE.sub(lambda m: f"=s{size}{m.group(1)}", url, count=1)
    return url
