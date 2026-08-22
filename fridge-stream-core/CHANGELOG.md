# Changelog

All notable changes to **Fridge Stream Core** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are when the work landed in this tree.

---

## [0.7.0] — 2026-08-22

### Added

- **Twitch adapter** (`adapters/twitch.py`)
  - Read-only anonymous IRC (`justinfan`) — no OAuth required to listen.
  - Config: `twitch.enabled`, `twitch.channel`.
- **YouTube adapter** (`adapters/youtube.py`) with two modes
  - `mode: innertube` — no API key, no Data API quota (web/InnerTube endpoint).
  - `mode: official` — Data API v3 `liveChatMessages.list` (needs `api_key`, uses quota).
  - `mode: auto` — official if `api_key` is set, otherwise innertube.
  - Config: `youtube.enabled`, `mode`, `video_id`, `api_key`, optional `live_chat_id` / `channel_id`.
- **Multi-platform chat overlay**
  - Combined: `http://127.0.0.1:3850/overlay/chat.html`
  - Filtered: `?platform=kick` | `?platform=twitch` | `?platform=youtube`
  - Multi: `?platforms=kick,twitch`
  - Platform letter badges (K / T / Y) in combined mode; hide with `?badges=0`.
- **Admin Config tab** fields for Twitch + YouTube mode / API key / live chat id.
- Wizard prompts for Kick / Twitch / YouTube enablement (all default off).

### Changed

- **All chat platforms default to disabled** (`kick.enabled`, `twitch.enabled`, `youtube.enabled` = false).
  Enable only what you use in `config.yaml` or the admin Config tab, then restart.
- `Platform` enum includes `TWITCH`.
- README overlay table and architecture diagram updated for multi-platform chat.

### Notes for users

1. Enable platforms in Config (or wizard) → set channel / video id → **restart Core**.
2. YouTube live `video_id` changes every stream (especially for innertube).
3. Overlay URLs above; Minecraft and points behaviour unchanged.

---

## [0.6.0] — 2026-08-22

### Added

- **Windows install / start scripts** (`install.bat`, `start.bat`, `run.bat`, `SCRIPTS.md`)
- **First-run wizard** (`wizard.py`)
- **Stronger Kick chatroom autodetection** with persist to config.yaml

See repo history for earlier 0.5.0 and below.
