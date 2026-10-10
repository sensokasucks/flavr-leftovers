# Fridge Stream Core

Modular backbone for chat-driven stream integrations. See [CHANGELOG.md](CHANGELOG.md) for version history. Fridge Market (points book) is specified in [docs/MARKET.md](docs/MARKET.md) — not shipped yet.

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
                            Minecraft / Factorio / Granvir / OpenTTD
```

All **chat platforms default to off**. Enable Kick, Twitch, and/or YouTube in `config.yaml` (or the admin Config tab); Core connects them without a restart.

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
| **Combined chat** | `http://127.0.0.1:3850/overlay/chat.html` | All enabled platforms (K/T/Y badges). Skins, custom CSS (Streamlabs / StreamElements chat CSS drops in), pictures and sounds: Admin → Chat overlay, notes in [overlay/CHAT.md](overlay/CHAT.md) |
| **Kick only** | `…/overlay/chat.html?platform=kick` | Filtered |
| **Twitch only** | `…/overlay/chat.html?platform=twitch` | Filtered |
| **YouTube only** | `…/overlay/chat.html?platform=youtube` | Filtered |
| **Multi filter** | `…/overlay/chat.html?platforms=kick,twitch` | Subset |
| **Minecraft stats** | `http://127.0.0.1:3850/overlay/overlay.html` | HP, CPM, power, inventory |
| **Stream alerts** | `http://127.0.0.1:3850/overlay/alerts.html` | Follow / sub / raid / Super Chat — Streamlabs/SE CSS compatible; pictures and sounds per kind uploaded in Admin → Alerts |
| **Chat credits** | `http://127.0.0.1:3850/overlay/credits.html` | Unique-chatter end credits (enable in Admin → Credits). Style editor + keys: [overlay/CREDITS.md](overlay/CREDITS.md), motions: [overlay/MOTIONS.md](overlay/MOTIONS.md) |
| **OpenTTD companies** | `http://127.0.0.1:3850/overlay/openttd.html` | Companies + Chat Fund (OpenTTD plugin, `openttd.enabled`) |
| **OpenTTD ticker** | `http://127.0.0.1:3850/overlay/openttd-ticker.html` | Thin company tape |
| **Market ticker** | `http://127.0.0.1:3850/overlay/market.html` | Scrolling Fridge Market tape |
| **Market board** | `http://127.0.0.1:3850/overlay/market-board.html` | Quote cards + sparklines |
| **Market chart** | `http://127.0.0.1:3850/overlay/market-chart.html?symbol=FACT` | TV-style line graph |
| **Market cycle** | `http://127.0.0.1:3850/overlay/market-cycle.html?symbols=FRG,FACT,STEVE` | Playlist of line charts (`dwell=8`) |
| **Chat reactions** | `http://127.0.0.1:3850/overlay/reactions.html` | Fallback for 🍅 / !tomato reactions when Stream Rooms isn't connected. Full canvas, transparent. Setup: Admin → Config → Reactions, spec [docs/REACTIONS.md](docs/REACTIONS.md) |
| Root | `http://127.0.0.1:3850/` | Same as Minecraft stats |

Use a **transparent** Webpage source. Chat is a separate source so you can place and size it on its own. Every switch an overlay takes on its address (platform filter, `?badges=0`, skin, hide-after, chart ticker, …) is in the dashboard's **Sources & overlays → Customise** panel, which writes the address for you; the list behind it is `core/overlay_catalog.py`. Alerts are a third source — test them from the admin **Alerts** tab. Both chat and alerts take the CSS you already have from Streamlabs / StreamElements / OBS Custom CSS (their ids and classes are the same), plus uploaded pictures and sounds: see [overlay/CHAT.md](overlay/CHAT.md) and [overlay/ALERTS.md](overlay/ALERTS.md).

### Admin dashboard (chat log + points + config editor)

```
http://127.0.0.1:3850/admin/
```

- Optional **chat history log** (`chat_log.enabled`, **off by default**) → SQLite `data/stream_core.db`
- Optional **chat points** (`points.enabled`, **off by default**) — per-message awards + `!points`
- Link Kick / YouTube (etc.) identities so one person keeps one balance
- Give / take points, notes, merge accounts
- Download full chat history as CSV (all or per user) when logging is on
- **🚩 Red flags** (Chat history page): phrases that red-flag whoever says them; flagged chatters are kept off every overlay and out of Stream Rooms but their lines are still logged and marked. List with **Unflag**, flag a name by hand (`red_flags` in config, `core/red_flags.py`)
- **Live controls** is the landing page: what's running, credits roll buttons, one-click test alerts and a dry-run command box — everything you need mid-stream on one screen.
- Flat left menu (On stream / Overlays / Games / People / Settings), every page one click away. **Settings** lists each config section as its own page. Busy pages show one section at a time via tabs along the top; Credits and Alerts keep their preview on the right. Pages have addresses (`/admin/#credits/style`), so Back works and you can bookmark a section.
- **Search** (press `/`) finds pages and individual settings and jumps to the field.
- **Integrations tab** — test chat commands (dry-run or live) and per-game features without going live in chat; Minecraft sub-panel for health, metrics push, overlay preview; modular for future games
- **Alert test tab** — fire follow / sub / raid / Super Chat without a live event; paste Streamlabs / StreamElements CSS; pick Classic / Card / Custom CSS only
- **Credits tab** — enable the built-in unique-chatter roll, restyle it (9 motions incl. Star Wars, Teletype and Matrix; letterbox / grain), freeze/roll at stream end, play once then clear, download the roster as CSV (hot-applied, uses Core chat adapters)
- **Config tab** — simple GUI for `config.yaml` + `commands.json`
  - Everyday settings on the main pages; advanced metrics / YouTube / chatroom id on **Settings → Advanced**
  - **Command groups** — enable/disable whole sets; optional bind to Minecraft / points; hot-applied
  - Commands list with edit / add / delete (group, priority, handler)
  - Duplicate name/alias conflicts shown in the UI; higher `priority` wins
  - Saves the same files tech users edit by hand (hybrid approach)
  - After save: chat platforms reconnect live (only the ones that changed); groups + commands hot-reload; **restart Stream Core** for game toggles

Set `points.admin_token` in `config.yaml` (or via the Config tab), paste it into the dashboard header, click **Save**.
If you leave it as `change-me`, Core refuses that value and generates a random token in `data/admin_token.txt`. The console shows only its first characters; double-click `data/Open dashboard.url` to open the dashboard signed in (`core.open_dashboard: true` opens it at every start). Saving the Config form with an empty token keeps the current one.

### Security

- Core binds `127.0.0.1`, **and** refuses requests that come from other web sites (foreign `Origin`) or a non-loopback `Host` (DNS rebinding). Game bridges and scripts that send no `Origin` are unaffected. See `core.allowed_hosts` / `core.allowed_origins` if you serve Core on a LAN IP on purpose.
- Permissions: plain names in `permissions.admin` / `mod` match Kick + Twitch only. YouTube admins/mods need `youtube:<channel id>` — Core logs the id the first time a YouTube user with a matching display name chats.
- Game bridges (Minecraft mods, Factorio bridge) only accept calls that carry Core's `X-Fridge-Core: 1` header.

## Ports (unchanged from the old Minecraft bridge)

| Service              | Port | Notes                                      |
|----------------------|------|--------------------------------------------|
| Stream Core HTTP/WS  | 3850 | Overlay + API + live metrics               |
| Minecraft client mod | 3852 | Player stats / inventory (unchanged)       |
| Minecraft server mod | 3853 | Command execution + Chat Dynamo (unchanged)|
| Granvir Stats        | 3855 | BepInEx plugin or mock/mock_server.py      |

Minecraft and Granvir are **off by default**. Set `minecraft.enabled` / `granvir.enabled` in `config.yaml` when those bridges are running.

## Project layout

```
fridge-stream-core/
├── main.py                 # entry point
├── wizard.py               # first-run CLI setup
├── install.bat             # one-time Windows install
├── start.bat / run.bat     # start Core
├── SCRIPTS.md              # line-by-line batch / wizard notes
├── docs/MARKET.md          # Fridge Market design (not shipped)
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
├── plugins/                # game plugins, one folder each; empty in git (games come from flavr-game-plugins)
├── api/
│   ├── server.py           # FastAPI + WebSocket
│   └── admin_routes.py     # points, chat export, config/commands, alert + integrations test
├── admin/                  # dashboard UI (Status, Sources, Alert test, Users, Chat, Config)
└── overlay/                # HTML/CSS/JS Webpage sources (XSplit / OBS)
```

## Game plugins

Minecraft, Factorio, Granvir and OpenTTD are plugins: folders in `plugins/`. They live in their
own repository, **[flavr-game-plugins](https://github.com/sensokasucks/flavr-game-plugins)**, and don't ship with Core. Copy the folder
of each game you want into `plugins/` (for example `plugins/minecraft/plugin.json`) and restart
Core. Each one adds a card under **Settings → Game plugins** (switch it on there, then restart
Core), its command group, its overlays and its Market listings. Core runs fine with the folder empty.

Adding a game: a new `plugins/<id>/` folder. If the game already has a bridge program that
speaks HTTP, a `plugin.json` is all it takes; otherwise a small Python class. See
[docs/PLUGINS.md](docs/PLUGINS.md).

## Chat platforms

| Platform | Config keys | Notes |
|----------|-------------|-------|
| **Kick** | `kick.enabled`, `channel_slug` | Pusher WebSocket; optional `chatroom_id` |
| **Chat replies** | (none) | A message sent with the platform's reply button (Kick, Twitch) carries `reply_to` (`user`, a shortened `message`, `message_id`) in the `/ws` chat payload; the chat overlay and Stream Rooms show "Replying to Name: ...". YouTube live chat has no reply button |
| **Kick pictures** | `kick.avatars` | Chatter profile pictures, looked up once per chatter and cached (`data/kick_avatars.json`). YouTube pictures come with chat |
| **Twitch** | `twitch.enabled`, `channel`, `third_party_emotes` | Chat over anonymous IRC (no login to listen). Emotes (native + BetterTTV / FrankerFaceZ / 7TV) ride along in the chat payload |
| **Twitch sign-in** | `twitch.avatars`, `twitch.client_id`, `twitch.client_secret` | **Connect Twitch** in the dashboard (Settings → Core + chat platforms → Twitch): Core shows a code, you enter it at twitch.tv/activate, done. Uses Stream Core's built-in public Twitch app (device code flow; the exchange is between your PC and Twitch, nothing passes through a third party). The token lives in `data/twitch_token.json`, is refreshed by Core and sent nowhere but Twitch; **Disconnect** revokes it. With it, chatter profile pictures come from the Twitch API (`data/twitch_avatars.json`, up to 100 chatters per request). Advanced: your own app's Client ID (and, for a confidential app, Client Secret) instead of the built-in one; a secret alone is enough for pictures without a sign-in |
| **YouTube** | `youtube.enabled`, `mode`, `video_id`, `api_key` | `innertube` (no quota) or `official` (Data API) |
| **Saved pictures** | `avatars.save_local`, `avatars.hide` | Core downloads each chatter's picture once (any platform), turns it into a 128 px PNG (with Pillow) and serves it at `/avatars/<platform>/<file>`; the chat payload and `user_update` carry it as `user.avatar_local` next to the platform link. `GET /api/chatters/avatar?name=…[&platform=…][&redirect=1]` finds a picture by chatter name for other overlays. **Never show a picture for** (Settings → Core + chat platforms → Chatter profile pictures) hides names everywhere; Stream Rooms adds its own list there when it connects |

YouTube `video_id` changes every live session. Prefer `mode: innertube` unless you need official Super Chat metadata via the Data API.

## Adding another platform later

1. Create `adapters/yourplatform.py` that subclasses `BaseAdapter`
2. Normalize messages into the same `ChatEvent` / `ChatUser` models
3. Call `await self._emit(event)` for every message
4. Report viewer count with `self.metrics.set_viewers(Platform.…, n)` when available
5. Register behind `enabled` in `main.py` and add config defaults + admin form fields

No changes to the command router, permissions, or game plugins are required.

## Development notes

- All platform usernames are lower-cased for permission checks so Kick and future YouTube share one admin/mod list.
- `!permit <user> [minutes]` still works (admin only) and is handled inside Core.
- Channel-point / Super-Chat cost fields already exist on commands; real deduction will live in the adapters when those APIs are wired up.
- The event bus is in-process for now. It can be swapped for Redis later without touching adapters or games.

---

Built to be the single backbone for every future Fridge chat ↔ game plugin.
