# Fridge Workshop

Streaming tools from Sensoka's Workshop. They started as XSplit Webpage sources and grew into standalone local apps that also work in OBS.

`fridge-` is the project prefix. Encoder mentions still say **XSplit / OBS** because that is where the overlays get captured.

## Start here (Windows)

| Double-click | What it does |
|--------------|--------------|
| **INSTALL Stream Core.bat** | One-time: Python venv + packages + optional setup wizard |
| **START Stream Core.bat** | Starts the chat backbone (leave the window open while streaming) |

Admin hub after start: [http://127.0.0.1:3850/admin/](http://127.0.0.1:3850/admin/)

## Projects

| Folder | What it is | Default port |
|--------|------------|--------------|
| [fridge-stream-core](fridge-stream-core/) | Chat backbone (Kick / Twitch / YouTube opt-in adapters) → event bus → commands / points / admin → games | 3850 |
| [fridge-minecraft](fridge-minecraft/) | Fabric client + server mods that Stream Core talks to | 3852 / 3853 |
| [fridge-chat-credits](fridge-chat-credits/) | Unique-chatter credits roll + control desk | 3854 |
| [fridge-factorio-stats](fridge-factorio-stats/) | Factorio RCON/Wiretap bridge + stat overlays | 3847 |
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

## Conventions

- One concern per folder. Platforms are adapters. Games are integrations. Overlays stay dumb HTML.
- Bind loopback by default. Do not expose these ports to the internet.
- Local config lives in `config/config.yaml` (git-ignored where a `.gitignore` exists). Examples stay in `*.example.*`.
- Runtime state goes under `data/` (`stream_core.db`, credits session JSON).

## Rebrand note (2026-08-21)

Renamed from `xsplit-*`. Rebuild Minecraft and Factorio mods after pulling this tree. Overlay URLs and ports did not change.
