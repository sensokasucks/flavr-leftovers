"""Turn whatever the streamer pasted into the id / name a chat adapter needs.

People copy the whole link from the browser: https://www.youtube.com/watch?v=…,
youtu.be/…, youtube.com/live/…, a YouTube Studio link, https://kick.com/name or
https://www.twitch.tv/name. Each helper also accepts the bare id / name.
The dashboard does the same in admin.js (cleanYouTube / cleanKick / cleanTwitch).
"""

from __future__ import annotations

import re
import urllib.parse

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# path forms: /live/ID, /shorts/ID, /embed/ID, /v/ID, studio /video/ID/livestreaming, youtu.be/ID
_YT_PATH = re.compile(r"/(?:live|shorts|embed|v|video)/([A-Za-z0-9_-]{11})(?:[/?#]|$)")


def youtube_video_id(raw: str) -> str:
    """Video id from a YouTube link or a bare id; "" when there is none to find."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if _YT_ID.match(text):
        return text
    if "://" not in text and ("youtu" in text or "/" in text):
        text = "https://" + text
    try:
        url = urllib.parse.urlparse(text)
    except ValueError:
        return ""
    host = (url.hostname or "").lower()
    if not host.endswith(("youtube.com", "youtu.be", "youtube-nocookie.com")):
        return ""
    v = urllib.parse.parse_qs(url.query).get("v", [""])[0]
    if _YT_ID.match(v):
        return v
    if host.endswith("youtu.be"):
        first = url.path.strip("/").split("/")[0]
        return first if _YT_ID.match(first) else ""
    m = _YT_PATH.search(url.path)
    return m.group(1) if m else ""


def _channel_name(raw: str, hosts: tuple[str, ...]) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    low = text.lower()
    if any(h in low for h in hosts):
        if "://" not in text:
            text = "https://" + text
        try:
            path = urllib.parse.urlparse(text).path
        except ValueError:
            return ""
        parts = [p for p in path.split("/") if p]
        # twitch.tv/popout/name/chat, kick.com/popout/name/chat
        if parts and parts[0].lower() == "popout" and len(parts) > 1:
            parts = parts[1:]
        text = parts[0] if parts else ""
    return text.strip().lstrip("@#").strip()


def kick_slug(raw: str) -> str:
    """kick.com/THIS_PART from a link, @name or name."""
    return _channel_name(raw, ("kick.com",))


def twitch_channel(raw: str) -> str:
    """twitch.tv/THIS_PART from a link, #name or name (lower case)."""
    return _channel_name(raw, ("twitch.tv",)).lower()
