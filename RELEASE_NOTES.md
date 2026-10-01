# FlaVR Leftovers — Release 0.13.1

**2026-08-27**

First tagged snapshot of the Fridge Workshop monorepo: local streaming tools that started as XSplit Webpage sources and now run as standalone apps (OBS works the same).

Prefix is `fridge-`. Overlays are captured in **XSplit / OBS**. Bind loopback only; do not expose these ports.

**Repo:** https://github.com/sensokasucks/flavr-leftovers

---

## What’s in this release

| Package | Role | Port |
|---------|------|------|
| **fridge-stream-core** | Chat backbone, commands, points, alerts, credits, admin | 3850 |
| **fridge-minecraft** | Fabric client + server mods Core talks to | 3852 / 3853 |
| **fridge-factorio-stats** | Factorio RCON/Wiretap bridge + stat overlays | 3847 |
| **fridge-chat-credits** | Standalone unique-chatter credits desk | 3854 |
| **fridge-reactive-image** | Native audio-reactive avatar | 3851 |
| **fridge-reactive-image-legacy** | Archived Node avatar | — |

Windows entry points at repo root:

- `INSTALL Stream Core.bat` — venv + packages + optional wizard
- `START Stream Core.bat` — leave the window open while streaming

Admin: http://127.0.0.1:3850/admin/

---

## fridge-stream-core (0.13.1)

Python asyncio + FastAPI. Adapters normalize chat; games receive commands and metrics.

### Platforms (all off by default)

- **Kick** — Pusher chat, emotes, badges, chatroom id autodetection
- **Twitch** — anonymous IRC listen (no OAuth required to read chat)
- **YouTube** — innertube / official / auto

Enable in `config.yaml` or Admin → Config, then restart.

### Shared core

- Event bus, permissions (`admin` / `mod` / `public`, `!permit`)
- Command router: prefix `!`, aliases, quantity, templates, groups
- **Command groups** — `enabled`, optional `bind` to minecraft / points / credits / factorio, hot-reload
- Name/alias conflicts: higher `priority` wins
- Metrics: viewers, CPM, command rate, power level 0–15
- SQLite chat log + in-house points (`data/stream_core.db`)
- Cross-platform identity linking, points adjust, CSV export

### Admin hub (`/admin/`)

- Status + Sources (overlay URLs and descriptions)
- Config editor (writes `config.yaml` + `commands.json`; advanced accordion)
- Command group table; save / hot-reload
- Integrations: command tester (dry-run / live), per-game panels, metrics test, overlay previews
- Alert test + style (Streamlabs / StreamElements CSS compatible)
- Credits tab: enable, roll/loop/once/hold, cast style, pins, preview
- Users / points / links

### Overlays (Webpage sources, transparent)

| URL | What |
|-----|------|
| `/overlay/chat.html` | Multi-platform chat (`?platform=` / `?platforms=`) |
| `/overlay/overlay.html` | Stats (HP, CPM, power, inventory when Minecraft is up) |
| `/overlay/alerts.html` | Follow / sub / raid / bits / Super Chat / donation |
| `/overlay/credits.html` | End-credits crawl (unique chatters + movie cast) |

### Chat credits (built-in, opt-in)

- Unique chatters from the same adapters as live chat
- Pixel `requestAnimationFrame` crawl (works in XSplit/OBS CEF)
- Movie-style **cast** (`config/cast/*.json`, shipped `movie.json`)
- Persistent job pins (`data/cast_overrides.json`)
- Commands (group `credits`): `!credit "name" "job"`, `!credit "name" clear`, `!credits`
- `credits.command_permission`: `mod` (default), `admin`, `public`

### Games

- **Minecraft** — opt-in; HTTP to client :3852 and server :3853
- **Factorio** — opt-in slot; health-checks the :3847 bridge (`GET /stats`). Overlay/stats only; no factory chat commands yet

### Also

- Wizard + `install.bat` / `start.bat` / `SCRIPTS.md`
- Tests: boot + command groups
- Fix in 0.13.1: Credits admin API (cast fields + write routes)
- Fix: missing `Body` import on one admin route (startup crash)

---

## fridge-minecraft

Fabric mods only. Chat/commands live in Stream Core.

- **Client mod** — local stats HTTP on **3852** (HP, inventory, etc.)
- **Server mod** — command execute + Chat Dynamo redstone 0–15 on **3853**
- Config-driven commands, permission tiers, quantity
- `jars/` is for pre-built Fabric jars you add yourself (not in git)
- `BUILD.bat` / per-mod Gradle + `COMPILE.md` if you build on PC

Enable `minecraft.enabled` in Core after the mods are loaded.

---

## fridge-factorio-stats

Standalone Factorio overlay stack (also listed as a Core game slot).

- Lua mod (`mod/`) + Node RCON/Wiretap bridge (`server/`)
- Full overlay + split sources: power, research, kills, deaths, evolution, combat, alerts
- Default: http://localhost:3847/overlay.html
- Core Factorio integration points at `factorio.bridge_url` (default that bridge)

---

## fridge-chat-credits

Standalone credits app if you do not want Core’s built-in roll.

- Unique chatters per platform
- Adapters: Twitch IRC, Kick Pusher, optional YouTube + Stream Core ingest
- Overlay: http://127.0.0.1:3854/overlay/credits.html
- Control desk: http://127.0.0.1:3854/
- Same movie-cast module (`core/cast.py`) as Core
- Session JSON under `data/`

---

## fridge-reactive-image

Native Python avatar (tkinter + sounddevice + Pillow + pynput + optional serial).

- Scrollable settings, hold/toggle states, hotkeys
- HTTP control on **3851**
- Optional serial for tablet / Arduino
- `build.bat` → `ReactiveImage.exe`

**fridge-reactive-image-legacy** is the old Node renderer, kept for reference only.

---

## What is not in the repo / release zip

- Live `config/config.yaml`, `.env`, `data/`, `*.db`
- Built `.jar` / `.exe` outputs (add jars under `fridge-minecraft/jars/` yourself)
- `.venv`, `node_modules`, `__pycache__`

Copy `*.example.*` → local config after clone.

---

## First-run

1. Python 3.10+ on PATH (3.14 is fine).
2. `INSTALL Stream Core.bat` → wizard (channels, admin name, token).
3. `START Stream Core.bat`.
4. Open http://127.0.0.1:3850/admin/ — enable platforms, Minecraft/Factorio/credits as needed.
5. Add overlay URLs as transparent Webpage sources.

If GitHub Desktop dies on `execvpe(/bin/bash)` while committing, unset hooks:

```bat
git config --unset core.hooksPath
```

Then commit and push. Hooks in `githooks/` are optional.

---

## Ports (do not collide)

| Port | Owner |
|------|--------|
| 3847 | Factorio bridge |
| 3850 | Stream Core |
| 3851 | Reactive Image |
| 3852 | Minecraft client mod |
| 3853 | Minecraft server mod |
| 3854 | Chat Credits standalone |
