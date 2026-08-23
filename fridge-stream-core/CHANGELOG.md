# Changelog

All notable changes to **Fridge Stream Core** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are when the work landed in this tree.

---

## [0.7.1] — 2026-08-22

### Fixed

- **Tab in `config.example.yaml` crashed a fresh GitHub clone.** PyYAML rejects tab indent (`ScannerError` on `overlay:`). The example file is spaces-only again.
- **Config loader is tab-tolerant.** Existing `config.yaml` copies that still have a tab (from `install.bat` copying the old example, or a Windows editor) are rewritten to spaces on startup instead of crashing.
- UTF-8 BOM from Notepad no longer breaks YAML/JSON parse.
- First run of `python main.py` (without `install.bat`) now seeds `config/config.yaml`, `config/commands.json`, and `data/` from the examples.
- `core/store.py` no longer references a non-existent `users.username` column, which broke points + chat history on a chatter's **second** message.
- Permission lists accept a single YAML string as well as a list (hand-edited config).
- Invalid `commands.json` logs an error and continues instead of crashing startup.
- Missing pip packages print `install.bat` / `pip install -r requirements.txt` instead of a raw traceback.
- Python 3.10 is officially supported (was documented as 3.11+).

### Notes for users who already copied the broken example

Pull this update, then run `python main.py` (or `start.bat`) again. Core rewrites the tab in `config.yaml` automatically. You do not need to delete your settings.

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

- **Windows install / start scripts**
  - `install.bat` — finds Python, creates `.venv`, `pip install -r requirements.txt`, seeds `config.yaml` / `commands.json` if missing, offers the wizard.
  - `start.bat` / `run.bat` — launches Core with the venv; runs the wizard if config is still missing.
  - **[SCRIPTS.md](SCRIPTS.md)** — line-by-line explanation of every step for curious users.
- **First-run wizard** (`wizard.py`)
  - CLI prompts: Kick slug, admins/mods, admin token (auto-generated if still `change-me`), optional Minecraft.
  - Tries Kick chatroom autodetection and writes `config/config.yaml`.
- **Stronger Kick chatroom autodetection** (`adapters/kick.py`)
  - More endpoint variants (`v1`/`v2`, `/chat`, `/chatroom`) and header sets.
  - On success, **persists `kick.chatroom_id` into `config.yaml`** so later starts skip the API (survives intermittent Cloudflare 403s).
  - Clearer failure message with the browser fallback URL.

### Notes for users

1. Double-click `install.bat` once → answer the wizard.
2. Double-click `start.bat` to stream.
3. Admin dashboard and overlays are unchanged (`http://127.0.0.1:3850/...`).

---

## [0.5.0] — 2026-08-22

### Added

- **Hybrid config editor** in the admin dashboard (`/admin/` → **Config** tab).
  - Simple form for Core, Kick, Minecraft, Permissions, and Points.
  - Advanced accordion: Kick chatroom id, YouTube stubs, metrics weights, overlay timing.
  - Commands list: edit / add / delete, then save to `commands.json`.
  - Writes the same `config/config.yaml` and `config/commands.json` that power users edit by hand.
  - Save-then-restart model (no hot-reload) to keep behaviour predictable.
- `core/config.py`: `save_config()`, `save_commands()`, path helpers used by the API and future tools.
- Admin API: `GET/PUT /api/admin/config`, `GET/PUT /api/admin/commands` (token-protected).

### Notes for users

1. Open `http://127.0.0.1:3850/admin/`, paste your admin token, open the **Config** tab.
2. Change settings → **Save config.yaml** / **Save commands.json**.
3. Restart Stream Core so the process reloads the files.

Tech users can keep editing YAML/JSON directly; the GUI is optional.

---

## [0.4.0] — 2026-08-21

### Changed

- Workshop rebrand: project prefix `xsplit-` → `fridge-`. This folder is now `fridge-stream-core`.
- Display name **Fridge Stream Core**. API title/version bumped to `0.4.0`.
- Sibling trees renamed in the same pass (`fridge-chat-credits`, `fridge-minecraft`, `fridge-factorio-stats`, `fridge-reactive-image`).
- Removed stale Reactive Image zip snapshots and `__pycache__`.

Ports, overlay URLs, and config keys are unchanged. Only folder names, titles, and Minecraft/Factorio mod ids moved.

### Migration

1. Point scripts and shortcuts at `fridge-stream-core/` instead of `xsplit-stream-core/`.
2. Rebuild Fabric mods from `fridge-minecraft/` and drop the old `xsplit-minecraft-*.jar` files.
3. Factorio: install `fridge-factorio-stats_1.0.0`. `/xsplit-stats` still works as an alias.

---

## [0.3.0] — 2026-08-19

### Changed

- **Minecraft integration is now off by default.** Chat, Kick, overlays, points, and the admin dashboard still start; Core no longer opens HTTP clients to `:3852` / `:3853` or fans out commands/metrics to the Fabric mods unless you opt in.
- Code and config defaults now agree:
  - `config/config.yaml` and `config/config.example.yaml` — `minecraft.enabled: false`
  - `core/config.py` `DEFAULTS` — `enabled: False` (also used when no config file is found)
  - `main.py` — skips `MinecraftIntegration` when disabled and logs `Minecraft integration disabled`
  - `games/minecraft.py` — treats a missing `enabled` key as off
- README documents Minecraft as opt-in.

### Why

Running Core for Kick chat / points should not assume a Minecraft client and server are up. Turn it on when the Fabric mods are installed:

```yaml
minecraft:
  enabled: true
  player_name: "YourInGameName"
  client_mod_url: "http://127.0.0.1:3852"
  server_mod_url: "http://127.0.0.1:3853"
```

---

## [0.2.0] — 2026-08-10

### Added

- SQLite store at `data/stream_core.db` (`core/store.py`):
  - `users` — unified person + points balance + notes
  - `identities` — platform accounts (`kick`, future `youtube`, …) mapped to one user
  - `chat_messages` — full chat history (command flag included)
  - `points_ledger` — every award / adjustment with reason and source
- In-house chat points (config under `points:`):
  - `enabled`, `per_message` (default 1), `cooldown_sec` (default 30)
  - Awarded on inbound chat after command-parse so history knows `is_command`
- Admin dashboard at `/admin/`
  - Token via `points.admin_token` and header `X-Admin-Token`
  - Search users, give/take points, notes, merge accounts
  - Link / unlink cross-platform identities so one person keeps one balance
  - Export chat history as CSV (all or per user)
- Admin HTTP API under `/api/admin/*` (`api/admin_routes.py`)

### Changed

- `main.py` wires `Store.process_chat` on every chat event
- `config.example.yaml` documents the `points:` block
- `.gitignore` covers `data/` and local config so the live DB is not committed

---

## [0.1.1] — 2026-08-06

### Added

- Kick chat overlay: `http://127.0.0.1:3850/overlay/chat.html`
  - Live WebSocket messages (`type: chat`)
  - Kick emotes: `[emote:id:name]` → `files.kick.com`
  - Badges (mod / VIP / subscriber) from the normalized `ChatUser`
  - `chat_history` snapshot so overlays that connect mid-stream catch up (last ~40 messages)
- Transparent Webpage source so chat can be placed independently of the Minecraft stats overlay

### Changed

- Event bus / API broadcast chat independently of command execution
- Kick adapter still uses the public Pusher socket + `/api/v2/channels/{slug}` viewer poll; optional `kick.chatroom_id` override if the REST lookup 403s

---

## [0.1.0] — 2026-08-04

Initial modular rewrite. Replaces the Node Minecraft + Kick bridge.

### Added

- Python asyncio + FastAPI backbone on **port 3850** (same as the old bridge)
- **Adapters** — platform → `ChatEvent`
  - Kick (Pusher chat + viewer poll)
  - YouTube stub in config (`enabled: false`) — architecture ready, adapter deferred
- **Event bus** — in-process pub/sub for chat, execute, metrics
- **Command router** (`config/commands.json`)
  - Prefix `!`, aliases, args, optional qty / seconds, `allowedValues`
  - Permission tiers: `public` / `mod` / `admin`
  - `!permit <user> [minutes]` handled in Core
  - Special action `show_inventory` for the client mod
  - `cost` field reserved for Channel Points / Super Chat later
- **Permissions** — case-insensitive usernames shared across platforms
- **Metrics aggregator** — viewers, CPM, command rate, weighted `powerLevel` (same math as the Node bridge)
- **Minecraft integration** (`games/minecraft.py`) talking to existing Fabric mods:
  - Client mod `:3852` — stats + inventory
  - Server mod `:3853` — command execute + Chat Dynamo / Chat Kinetic
- Overlay: `overlay/overlay.html` (HP, CPM, power, inventory)
- `config/config.yaml` + `config/config.example.yaml`

### Ports (unchanged from the Node bridge)

| Service | Port |
|---------|------|
| Stream Core HTTP / WS | 3850 |
| Minecraft client mod | 3852 |
| Minecraft server mod | 3853 |

---

## Related workshop history

These landed in sibling folders and are not versioned as Stream Core, but they are why Core exists.

### XSplit Minecraft + Kick — 2026-08-04 / 2026-08-05

- Original stack: Fabric client-mod + server-mod + Node Kick/Pusher bridge + HTML overlay
- Commands config-driven, permission tiers, quantity support
- Chat Dynamo: redstone 0–15 from viewers / CPM / commands
- **2026-08-05:** Node bridge, duplicate overlay, caches, and leftover `node_modules` removed. `fridge-minecraft/` is mods-only and points at Stream Core.

### XSplit Reactive Image (Python) — 2026-08-01 / 2026-08-03

- Native app: tkinter + sounddevice + Pillow + pynput + pyserial
- Scrollable settings, custom hold/toggle states + hotkeys
- HTTP `:3851` + optional serial for tablet/Arduino
- `build.bat` → `ReactiveImage.exe`

### Fridge Factorio Stats — 2026-07-30 / 2026-08-04

- Factorio mod + Node RCON/Wiretap bridge + HTML overlay
- Power (Wiretap), research, kills, deaths, alerts, evolution
- Overlay `http://localhost:3847/overlay.html` plus per-stat pages

---

## Upgrade notes

### 0.3.x → 0.4.0

Folder and display names only, plus Minecraft / Factorio mod ids.

1. `cd fridge-stream-core` (was `xsplit-stream-core`)
2. Rebuild `fridge-minecraft` jars; delete old `xsplit-minecraft-*.jar`
3. Factorio mod folder is now `fridge-factorio-stats_1.0.0` — `/xsplit-stats` still aliases `/fridge-stats`

Ports 3850 / 3852 / 3853 / overlay URLs stay the same.

### 0.2.x → 0.3.0

If you stream Minecraft and previously relied on the default:

1. Set `minecraft.enabled: true` in `config/config.yaml`
2. Confirm `player_name` and the mod URLs
3. Restart Core — you should see `Minecraft integration ready (...)` instead of the disabled log line

Chat, Kick, points, `/admin/`, and `/overlay/chat.html` do not require that flag.

### Node bridge → Stream Core (0.1.0)

1. Stop `bridge/server.js`
2. Start `python main.py` in this folder
3. Keep the same Fabric mods and overlay URL
4. Move Kick slug, player name, and admin list into `config.yaml`
