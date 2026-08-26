# Fridge Stream Core

Modular backbone for chat-driven stream integrations. See [CHANGELOG.md](CHANGELOG.md) for version history.

**Platforms** (adapters) feed normalized chat events into Core.  
**Games** (integrations) receive approved commands and live metrics.  
Everything shared (permissions, command parsing, CPM / power level, overlays) lives here once.

```
Kick / Twitch / YouTube adapters ──┐
                                   │  ChatEvent
                                   ▼
                            ┌──────────────┐
                            │  Stream Core │  ← this project (Python)
                            │              │
                            │  permissions │
                            │  commands    │
                            │  metrics     │
                            │  event bus   │
                            └──────┬───────┘
                                   │  ExecuteRequest + MetricsSnapshot
                                   ▼
                            Minecraft mods (and future games)
```

All **chat platforms default to off**. Enable Kick, Twitch, and/or YouTube in `config.yaml` (or the admin Config tab) and restart.

## Why this exists

The original Minecraft + Kick bridge mixed platform logic, command logic, and game logic in one Node process. Adding another platform or another game meant copying a lot of code.  

Stream Core separates the concerns so:

- New platforms only implement an adapter
- New games only implement a thin integration
- Shared features (permissions, `!permit`, CPM, power level, command templates) are written once

## Quick start (Windows – recommended)

1. Install **Python 3.10+** from [python.org](https://www.python.org/downloads/)  
   (tick **Add python.exe to PATH** during setup).
2. Double-click **`install.bat`** once.  
   When asked, run the first-run wizard (Kick channel, admins, admin token).
3. Double-click **`start.bat`** (or **`run.bat`**) whenever you stream.

That is the whole install. Details and line-by-line script notes: **[SCRIPTS.md](SCRIPTS.md)**.

### Manual / macOS / Linux

```bash
cd fridge-stream-core
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml
python wizard.py                   # optional guided setup
python main.py
```

**Chat platforms and Minecraft are all off by default.** Enable what you need in config (wizard can do this too).

### Overlay URLs (XSplit / OBS Webpage sources)

| Overlay | URL | Purpose |
|---------|-----|---------|
| **Combined chat** | `http://127.0.0.1:3850/overlay/chat.html` | All enabled platforms (K/T/Y badges) |
| **Kick only** | `…/overlay/chat.html?platform=kick` | Filtered |
| **Twitch only** | `…/overlay/chat.html?platform=twitch` | Filtered |
| **YouTube only** | `…/overlay/chat.html?platform=youtube` | Filtered |
| **Multi filter** | `…/overlay/chat.html?platforms=kick,twitch` | Subset |
| **Minecraft stats** | `http://127.0.0.1:3850/overlay/overlay.html` | HP, CPM, power, inventory |
| **Stream alerts** | `http://127.0.0.1:3850/overlay/alerts.html` | Follow / sub / raid / Super Chat — Streamlabs/SE CSS compatible |
| **Chat credits** | `http://127.0.0.1:3850/overlay/credits.html` | Unique-chatter end credits (enable in Admin → Credits) |
| Root | `http://127.0.0.1:3850/` | Same as Minecraft stats |

Use a **transparent** Webpage source. Chat is a separate source so you can place and size it on its own. Add `?badges=0` to hide platform letters on combined chat. Alerts are a third source — test them from the admin **Alert test** tab. Paste existing Streamlabs / StreamElements CSS there (see [overlay/ALERTS.md](overlay/ALERTS.md)).

### Admin dashboard (chat log + points + config editor)

```
http://127.0.0.1:3850/admin/
```

- Optional **chat history log** (`chat_log.enabled`, **off by default**) → SQLite `data/stream_core.db`
- Optional **chat points** (`points.enabled`, **off by default**) — per-message awards + `!points`
- Link Kick / YouTube (etc.) identities so one person keeps one balance
- Give / take points, notes, merge accounts
- Download full chat history as CSV (all or per user) when logging is on
- **Integrations tab** — test chat commands (dry-run or live) and per-game features without going live in chat; Minecraft sub-panel for health, metrics push, overlay preview; modular for future games
- **Alert test tab** — fire follow / sub / raid / Super Chat without a live event; paste Streamlabs / StreamElements CSS; pick Classic / Card / Custom CSS only
- **Credits tab** — enable the built-in unique-chatter roll, restyle it, freeze/roll at stream end (hot-applied, uses Core chat adapters)
- **Config tab** — simple GUI for `config.yaml` + `commands.json`
  - Everyday settings on the main form; advanced metrics / YouTube / chatroom id behind an accordion
  - **Command groups** — enable/disable whole sets; optional bind to Minecraft / points; hot-applied
  - Commands list with edit / add / delete (group, priority, handler)
  - Duplicate name/alias conflicts shown in the UI; higher `priority` wins
  - Saves the same files tech users edit by hand (hybrid approach)
  - After save: **restart Stream Core** for platform/game toggles; groups + commands hot-reload

Set `points.admin_token` in `config.yaml` (or via the Config tab), paste it into the dashboard header, click **Save**.

## Ports (unchanged from the old Minecraft bridge)

| Service              | Port | Notes                                      |
|----------------------|------|--------------------------------------------|
| Stream Core HTTP/WS  | 3850 | Overlay + API + live metrics               |
| Minecraft client mod | 3852 | Player stats / inventory (unchanged)       |
| Minecraft server mod | 3853 | Command execution + Chat Dynamo (unchanged)|

Minecraft is **off by default**. Set `minecraft.enabled: true` in `config.yaml` (and `player_name`) when the Fabric mods are running. Core then talks to them over the same HTTP endpoints as the old Node bridge.

## Project layout

```
fridge-stream-core/
├── main.py                 # entry point
├── wizard.py               # first-run CLI setup
├── install.bat             # one-time Windows install
├── start.bat / run.bat     # start Core
├── SCRIPTS.md              # line-by-line batch / wizard notes
├── requirements.txt
├── config/
│   ├── config.example.yaml
│   ├── config.yaml         # your real config (git-ignored ideally)
│   ├── commands.example.json
│   └── commands.json
├── core/
│   ├── models.py           # ChatEvent, ChatUser, MetricsSnapshot, …
│   ├── permissions.py
│   ├── metrics.py
│   ├── command_router.py
│   ├── command_groups.py   # group catalog + bind / enablement
│   ├── event_bus.py
│   ├── store.py            # SQLite chat log + points
│   ├── alerts.py           # follow / sub / raid / Super Chat catalog
│   └── config.py           # load + save (GUI + CLI share paths)
├── adapters/
│   ├── base.py             # abstract adapter
│   ├── kick.py             # Kick Pusher listener
│   ├── twitch.py           # Twitch anonymous IRC
│   └── youtube.py          # YouTube official API + InnerTube
├── games/
│   ├── base.py             # abstract game integration
│   └── minecraft.py        # talks to existing Fabric mods
├── api/
│   ├── server.py           # FastAPI + WebSocket
│   └── admin_routes.py     # points, chat export, config/commands, alert + integrations test
├── admin/                  # dashboard UI (Status, Sources, Alert test, Users, Chat, Config)
└── overlay/                # HTML/CSS/JS Webpage sources (XSplit / OBS)
```

## Adding a new game later

1. Create `games/yourgame.py` that subclasses `BaseGameIntegration`
2. Implement `execute(self, req: ExecuteRequest) -> dict`
3. Optionally implement `on_metrics`
4. Register it in `main.py` the same way Minecraft is registered

Core will automatically route approved chat commands to every registered game.

## Chat platforms

| Platform | Config keys | Notes |
|----------|-------------|-------|
| **Kick** | `kick.enabled`, `channel_slug` | Pusher WebSocket; optional `chatroom_id` |
| **Twitch** | `twitch.enabled`, `channel` | Anonymous IRC (no OAuth to listen) |
| **YouTube** | `youtube.enabled`, `mode`, `video_id`, `api_key` | `innertube` (no quota) or `official` (Data API) |

YouTube `video_id` changes every live session. Prefer `mode: innertube` unless you need official Super Chat metadata via the Data API.

## Adding another platform later

1. Create `adapters/yourplatform.py` that subclasses `BaseAdapter`
2. Normalize messages into the same `ChatEvent` / `ChatUser` models
3. Call `await self._emit(event)` for every message
4. Report viewer count with `self.metrics.set_viewers(Platform.…, n)` when available
5. Register behind `enabled` in `main.py` and add config defaults + admin form fields

No changes to the command router, permissions, or Minecraft integration are required.

## Migration from the old Node bridge

1. Stop the old `bridge/server.js`
2. Start Stream Core (`python main.py`)
3. Keep the same Fabric mods and the same overlay URL
4. Point `config.yaml` at your Kick channel + Minecraft player name

The command list, permission model, and power-level math are intentionally identical so behavior stays the same while the architecture becomes modular.

## Development notes

- All platform usernames are lower-cased for permission checks so Kick and future YouTube share one admin/mod list.
- `!permit <user> [minutes]` still works (admin only) and is handled inside Core.
- Channel-point / Super-Chat cost fields already exist on commands; real deduction will live in the adapters when those APIs are wired up.
- The event bus is in-process for now. It can be swapped for Redis later without touching adapters or games.

---

Built to be the single backbone for every future Fridge chat ↔ game plugin.
