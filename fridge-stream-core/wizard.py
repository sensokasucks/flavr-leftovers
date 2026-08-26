#!/usr/bin/env python3
"""
Fridge Stream Core – first-run setup wizard (CLI).

Asks a few plain questions and writes config/config.yaml.
Optionally tries to auto-resolve the Kick chatroom id.

Safe to re-run: existing values are shown as defaults; press Enter to keep them.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import ConfigError, DEFAULTS, load_config, save_config  # noqa: E402


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{label}{suffix}: ").strip()
    return raw if raw else default


def _prompt_yes_no(label: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{label} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def _split_usernames(raw: str) -> list[str]:
    parts = []
    for chunk in raw.replace(";", ",").split(","):
        name = chunk.strip().lstrip("@")
        if name:
            parts.append(name)
    return parts


async def _try_resolve_chatroom(slug: str) -> int | None:
    """Reuse the Kick adapter resolver without starting the full Core."""
    if not slug or slug.startswith("YOUR_"):
        return None
    try:
        from adapters.kick import KickAdapter
        from core.event_bus import EventBus
        from core.metrics import MetricsAggregator

        # Minimal stubs — resolver only needs the slug
        fake_cfg = {"kick": {"channel_slug": slug}}
        adapter = KickAdapter(fake_cfg, EventBus(), MetricsAggregator(fake_cfg))
        return await adapter._resolve_chatroom_id(slug)
    except Exception as e:
        print(f"  (auto-resolve skipped: {e})")
        return None


def main() -> int:
    print()
    print("=== Fridge Stream Core – first-run wizard ===")
    print("Press Enter to keep the value in [brackets].")
    print()

    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1

    # --- Chat platforms (all opt-in) ---
    print("Chat platforms default OFF. Enable only what you use.")
    print()

    # Kick
    kick = dict(cfg.get("kick") or {})
    use_kick = _prompt_yes_no("Enable Kick chat?", default=bool(kick.get("enabled")))
    kick["enabled"] = use_kick
    if use_kick:
        slug = _prompt(
            "  Kick channel slug (kick.com/THIS_PART)",
            str(kick.get("channel_slug") or ""),
        ).lstrip("@").strip()
        if not slug:
            slug = kick.get("channel_slug") or DEFAULTS["kick"]["channel_slug"]
        kick["channel_slug"] = slug

        existing_id = kick.get("chatroom_id")
        if existing_id not in (None, "", 0, "0"):
            print(f"  Existing chatroom_id: {existing_id}")
            if not _prompt_yes_no("  Keep this chatroom_id?", default=True):
                kick.pop("chatroom_id", None)
                existing_id = None
        else:
            existing_id = None

        if existing_id in (None, "", 0, "0") and slug and not str(slug).startswith("YOUR_"):
            print("  Looking up Kick chatroom id…")
            cid = asyncio.run(_try_resolve_chatroom(slug))
            if cid:
                kick["chatroom_id"] = int(cid)
                print(f"  Found chatroom_id: {cid} (will be saved)")
            else:
                print(
                    "  Could not auto-resolve (Kick may block server requests).\n"
                    f"  Optional: open https://kick.com/api/v2/channels/{slug} in a browser,\n"
                    "  copy the number next to \"id\" under \"chatroom\", then paste it below."
                )
                manual = _prompt("  chatroom_id (leave blank to skip)", "")
                if manual.isdigit():
                    kick["chatroom_id"] = int(manual)
    cfg["kick"] = kick

    # Twitch
    tw = dict(cfg.get("twitch") or {})
    use_tw = _prompt_yes_no("Enable Twitch chat?", default=bool(tw.get("enabled")))
    tw["enabled"] = use_tw
    if use_tw:
        tw["channel"] = _prompt(
            "  Twitch channel (twitch.tv/THIS_PART)",
            str(tw.get("channel") or "").lstrip("#"),
        ).lstrip("#").strip() or "YOUR_TWITCH_CHANNEL"
    cfg["twitch"] = tw

    # YouTube
    yt = dict(cfg.get("youtube") or {})
    use_yt = _prompt_yes_no("Enable YouTube chat?", default=bool(yt.get("enabled")))
    yt["enabled"] = use_yt
    if use_yt:
        mode = _prompt(
            "  YouTube mode (innertube / official / auto)",
            str(yt.get("mode") or "innertube"),
        ).strip().lower() or "innertube"
        yt["mode"] = mode if mode in ("innertube", "official", "auto") else "innertube"
        yt["video_id"] = _prompt(
            "  Live video ID (changes every stream)",
            str(yt.get("video_id") or ""),
        ).strip()
        if yt["mode"] in ("official", "auto"):
            yt["api_key"] = _prompt(
                "  YouTube Data API key (official mode)",
                str(yt.get("api_key") or ""),
            ).strip()
        yt.setdefault("channel_id", "")
        yt.setdefault("live_chat_id", "")
    cfg["youtube"] = yt


    # --- Permissions ---
    perms = dict(cfg.get("permissions") or {})
    admins = perms.get("admin") or []
    if isinstance(admins, str):
        admins = [admins]
    admin_default = ", ".join(str(a) for a in admins) if admins else ""
    admin_raw = _prompt(
        "Admin usernames (comma-separated, case-insensitive)",
        admin_default,
    )
    perms["admin"] = _split_usernames(admin_raw) or ["YOUR_USERNAME"]
    mods = perms.get("mod") or []
    if isinstance(mods, str):
        mods = [mods]
    mod_default = ", ".join(str(m) for m in mods) if mods else ""
    mod_raw = _prompt("Mod usernames (optional, comma-separated)", mod_default)
    perms["mod"] = _split_usernames(mod_raw)
    cfg["permissions"] = perms

    # --- Points / admin token ---
    points = dict(cfg.get("points") or {})
    token = str(points.get("admin_token") or "")
    if not token or token in ("change-me", "YOUR_ADMIN_TOKEN"):
        token = secrets.token_urlsafe(16)
        print(f"  Generated admin token for /admin dashboard: {token}")
        print("  (copy this – you will paste it into the dashboard header)")
    else:
        print(f"  Existing admin token kept (starts with {token[:4]}…)")
        if _prompt_yes_no("  Generate a new admin token?", default=False):
            token = secrets.token_urlsafe(16)
            print(f"  New token: {token}")
    points["admin_token"] = token
    points["enabled"] = _prompt_yes_no(
        "Enable chat points? (!points / per-message awards)",
        default=bool(points.get("enabled")),
    )
    points.setdefault("per_message", 1)
    points.setdefault("cooldown_sec", 30)
    cfg["points"] = points

    # --- Chat history log (off by default) ---
    clog = dict(cfg.get("chat_log") or {})
    clog["enabled"] = _prompt_yes_no(
        "Save chat history to disk? (admin Chat History tab / CSV export)",
        default=bool(clog.get("enabled")),
    )
    cfg["chat_log"] = clog

    # --- Minecraft (opt-in) ---
    mc = dict(cfg.get("minecraft") or {})
    use_mc = _prompt_yes_no(
        "Enable Minecraft integration? (needs Fabric mods running)",
        default=bool(mc.get("enabled")),
    )
    mc["enabled"] = use_mc
    if use_mc:
        mc["player_name"] = _prompt(
            "Minecraft player name (exact in-game name)",
            str(mc.get("player_name") or "YourInGameName"),
        )
        mc.setdefault("client_mod_url", "http://127.0.0.1:3852")
        mc.setdefault("server_mod_url", "http://127.0.0.1:3853")
    cfg["minecraft"] = mc

    # --- Core host/port (rarely changed) ---
    core = dict(cfg.get("core") or {})
    core.setdefault("host", "127.0.0.1")
    core.setdefault("port", 3850)
    core.setdefault("command_prefix", "!")
    core.setdefault("log_level", "INFO")
    cfg["core"] = core

    path = save_config(cfg)
    print()
    print(f"Saved configuration to:\n  {path}")
    print()
    print("Next steps:")
    print("  1. Double-click start.bat  (or run.bat)")
    print("  2. Open http://127.0.0.1:3850/admin/ and paste your admin token")
    print("  3. Add overlay Webpage sources in XSplit / OBS (see README)")
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        raise SystemExit(1)
