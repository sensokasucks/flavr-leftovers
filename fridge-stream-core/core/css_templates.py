"""
Fill in the settings placeholders that free chat / alert CSS templates carry.

Streamlabs widgets replace ``{font_size}``, ``{text_color}``, ``{message_hide_delay}`` ... in a
template's CSS with the widget's settings; StreamElements does the same with ``{{fontSize}}``,
``{{fontName}}``. Pasted into Core as-is, every rule with one of those is thrown away by the
browser. ``fill_placeholders`` swaps the common ones for Core's own CSS variables (so the
dashboard and URL options still drive them) or a plain default, when the CSS is saved.
Placeholders it doesn't know stay as they are (the browser skips only that one line).
"""

from __future__ import annotations

import re

# value used for both "{name}" and "{{name}}", matched without regard to case and _ / -
# A length placeholder written as "{{fontSize}}px" takes the "px" with it.
VALUES: dict[str, str] = {
    # sizes
    "fontsize": "var(--chat-size, 16px)",
    "emotesize": "var(--chat-emote-size, 28px)",
    "badgesize": "var(--chat-badge-size, 16px)",
    "avatarsize": "var(--chat-avatar-size, 26px)",
    "nicknameleft": "0px",
    "nicknameright": "4px",
    "messageandusernamespace": "4px",
    "backgroundradius": "8px",
    "borderradius": "8px",
    "padding": "6px",
    # colours
    "textcolor": "var(--chat-text, #f5f7fa)",
    "fontcolor": "var(--chat-text, #f5f7fa)",
    "messagecolor": "var(--chat-text, #f5f7fa)",
    "namecolor": "inherit",
    "backgroundcolor": "rgba(0, 0, 0, 0.55)",
    "userbackgroundcolor": "rgba(0, 0, 0, 0.55)",
    "messagebackgroundcolor": "rgba(0, 0, 0, 0.55)",
    "highlightcolor": "var(--alert-accent, #53fc18)",
    "textshadow": "var(--chat-shadow, 0 1px 2px #000)",
    # fonts
    "fontname": "Roboto",
    "fontfamily": "Roboto",
    "fontweight": "600",
    # layout switches
    "displaybadges": "inline-block",
    "badgesvisibility": "inline-block",
    "alignhorizontal": "flex-start",
    "alignmessages": "flex",
    # timing: the chat overlay sets --chat-hide-delay from "hide messages after" (never = a day)
    "messagehidedelay": "var(--chat-hide-delay, 86400s)",
    "hidedelay": "var(--chat-hide-delay, 86400s)",
}

# Streamlabs' single-brace names that mean something else there: {background_color} is the
# whole widget's background, which Core leaves see-through
STREAMLABS_VALUES: dict[str, str] = {
    "backgroundcolor": "transparent",
}

# {{name}} or {name} (letters, digits, _ and -), with an optional "px" straight after
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z][\w-]*)\s*\}\}(px)?|\{([A-Za-z][\w-]*)\}(px)?")


def _key(name: str) -> str:
    return re.sub(r"[_-]", "", name).lower()


def fill_placeholders(css: str) -> tuple[str, int]:
    """(css with known placeholders filled, how many were filled)."""
    count = 0

    def sub(m: re.Match) -> str:
        nonlocal count
        name = m.group(1) or m.group(3)
        px = m.group(2) or m.group(4) or ""
        single = m.group(3) is not None
        value = (STREAMLABS_VALUES.get(_key(name)) if single else None) or VALUES.get(_key(name))
        if value is None:
            return m.group(0)
        count += 1
        # "{{fontSize}}px" -> the variable already carries its unit; a bare number default gets px
        return value if px and not value[-1:].isdigit() else value + px

    return _PLACEHOLDER.sub(sub, css), count
