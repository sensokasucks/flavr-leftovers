# Fridge Stream Core

Modular backbone for chat-driven stream integrations. See [CHANGELOG.md](CHANGELOG.md) for version history (current **0.11.0**).

**Platforms** (adapters) feed normalized chat events into Core.  
**Games** (integrations) receive approved commands and live metrics.  
Everything shared (permissions, command parsing, CPM / power level, overlays, alerts) lives here once.

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
                            │  alerts      │
                            └──────┬───────┘
                                   │  ExecuteRequest + MetricsSnapshot
                                   ▼
                            Minecraft mods (and future games)
```

All **chat platforms default to off**. Enable Kick, Twitch, and/or YouTube in `config.yaml` (or the admin Config tab) and restart.

## Quick start (Windows – recommended)

1. Install **Python 3.10+** from [python.org](https://www.python.org/downloads/) (tick **Add python.exe to PATH**).
2. From the workshop root, double-click **INSTALL Stream Core.bat** (or `fridge-stream-core/install.bat`).
3. Double-click **START Stream Core.bat** (or `start.bat`) whenever you stream.

Admin hub: [http://127.0.0.1:3850/admin/](http://127.0.0.1:3850/admin/)

Details: **[SCRIPTS.md](SCRIPTS.md)**.

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

## Overlay URLs (XSplit / OBS Webpage sources)

| Overlay | URL | Purpose |
|---------|-----|---------|
| **Combined chat** | `http://127.0.0.1:3850/overlay/chat.html` | All platforms (K/T/Y badges) |
| **Kick / Twitch / YT only** | `…/chat.html?platform=kick` (etc.) | Filtered |
| **Stream alerts** | `http://127.0.0.1:3850/overlay/alerts.html` | Follow/sub/bits/Super Chat (transparent) |
| **Minecraft stats** | `http://127.0.0.1:3850/overlay/overlay.html` | HP, CPM, power, inventory |

Use **transparent** Webpage sources. Alerts preview: `?preview=1`. See [overlay/ALERTS.md](overlay/ALERTS.md).

## Admin dashboard

```
http://127.0.0.1:3850/admin/
```

Tabs include Status, Users / points, Chat history, **Config** (YAML + commands + command groups, hot-reload), **Alert test**, and **Integrations** (command tester + per-game panels).

Set `points.admin_token` in config, paste into the dashboard header.

## Ports

| Service | Port |
|---------|------|
| Stream Core HTTP/WS | 3850 |
| Minecraft client mod | 3852 |
| Minecraft server mod | 3853 |

Minecraft is **off by default** (`minecraft.enabled: true` when mods are running).

## Project layout (high level)

- `main.py` / `wizard.py` / install scripts
- `core/` — models, permissions, metrics, command router + groups, store, **alerts**
- `adapters/` — Kick, Twitch, YouTube
- `games/` — Minecraft integration
- `api/` + `admin/` — FastAPI + dashboard
- `overlay/` — chat, stats, **alerts** HTML/CSS/JS
- `tests/`

## Adding a game or platform

Subclass `BaseGameIntegration` or `BaseAdapter`, register in `main.py`, add config defaults. Command router and permissions stay shared.

---

Built as the single backbone for Fridge / FlaVR Leftovers chat ↔ game plugins.
