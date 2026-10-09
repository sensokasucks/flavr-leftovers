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
| [fridge-stream-core](fridge-stream-core/) | Chat backbone (Kick / Twitch / YouTube opt-in adapters) → event bus → commands / points / admin → game plugins (`plugins/`) | 3850 |
| [fridge-chat-credits](fridge-chat-credits/) | Unique-chatter credits roll + control desk | 3854 |

Game plugins (Minecraft, Factorio, Granvir, OpenTTD) and their mods / bridges (`fridge-minecraft`,
`fridge-factorio-stats`, `fridge-granvir-stats`, ports 3847 / 3852 / 3853 / 3855) live in their own
repository: **[flavr-game-plugins](https://github.com/sensokasucks/flavr-game-plugins)**. Copy a game's folder into
`fridge-stream-core/plugins/` to use it.

The audio-reactive avatar app (port 3851) lives in **[flavr-reactive-image](https://github.com/sensokasucks/flavr-reactive-image)**.

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
