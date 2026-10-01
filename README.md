# Fridge Workshop

Streaming tools from Sensoka's Workshop. They started as XSplit Webpage sources and grew into standalone local apps that also work in OBS.

`fridge-` is the project prefix. Encoder mentions still say **XSplit / OBS** because that is where the overlays get captured.

## Start here (Windows)

| Double-click | What it does |
|--------------|--------------|
| **INSTALL Stream Core.bat** | One-time: Python venv + packages + optional setup wizard |
| **START Stream Core.bat** | Starts the chat backbone (leave the window open while streaming) |
| **INSTALL Chat Credits.bat** | One-time venv + packages for the standalone credits app |
| **START Chat Credits.bat** | Starts unique-chatter credits on :3854 (skip if you use Core Credits) |

Admin hub after start: [http://127.0.0.1:3850/admin/](http://127.0.0.1:3850/admin/)

## Changelog

Full release notes for Stream Core (and related workshop changes):

→ **[fridge-stream-core/CHANGELOG.md](fridge-stream-core/CHANGELOG.md)**

## Feature checklists

Invariants per feature live in **[checklists/](checklists/)**. Start at [checklists/INDEX.md](checklists/INDEX.md). Walk the relevant lists whenever something changes so ports, admin tabs, overlays, and opt-in defaults do not get dropped again. Agents are required to do this pass (`AGENTS.md`).

Claude Code: open this folder and it will load **[CLAUDE.md](CLAUDE.md)** (points at the same checklists).

## Projects

| Folder | What it is | Default port |
|--------|------------|--------------|
| [fridge-stream-core](fridge-stream-core/) | Chat backbone (Kick / Twitch / YouTube opt-in adapters) → event bus → commands / points / admin → games | 3850 |
| [fridge-minecraft](fridge-minecraft/) | Fabric client + server mods that Stream Core talks to | 3852 / 3853 |
| [fridge-chat-credits](fridge-chat-credits/) | Unique-chatter credits roll + control desk | 3854 |
| [fridge-factorio-stats](fridge-factorio-stats/) | Factorio overlays + Chat Dynamo (stream power) | 3847 |
| [fridge-granvir-stats](fridge-granvir-stats/) | Granvir BepInEx stats plugin + overlay + mock bridge | 3855 |
| [fridge-reactive-image](fridge-reactive-image/) | Native audio-reactive avatar (Python) | 3851 |
| [fridge-reactive-image-legacy](fridge-reactive-image-legacy/) | Archived Node avatar app | — |

## Ports (leave these alone)

| Port | Owner |
|------|--------|
| 3847 | Factorio bridge |
| 3850 | Stream Core HTTP / WS / overlays / admin |
| 3851 | Reactive Image HTTP control |
| 3852 | Minecraft client mod |
| 3853 | Minecraft server mod |
| 3854 | Chat Credits |
| 3855 | Granvir Stats |

## Conventions

- One concern per folder. Platforms are adapters. Games are integrations. Overlays stay dumb HTML.
- Bind loopback by default. Do not expose these ports to the internet.
- Local config lives in `config/config.yaml` (git-ignored where a `.gitignore` exists). Examples stay in `*.example.*`.
- Runtime state goes under `data/` (`stream_core.db`, credits session JSON).

## Rebrand note (2026-08-21)

Renamed from `xsplit-*`. Rebuild Minecraft and Factorio mods after pulling this tree. Overlay URLs and ports did not change.
