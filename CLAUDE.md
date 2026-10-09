# Fridge Workshop — Claude Code

Streaming tools from Sensoka's Workshop. Modular local apps + OBS/XSplit Webpage overlays.

Read **[AGENTS.md](AGENTS.md)** and walk **[checklists/](checklists/)** before calling a change done. Start at [checklists/INDEX.md](checklists/INDEX.md).

Style: build streaming plugins based on user needs. Keep everything modular and documented.

## Layout

| Folder | Role | Port |
|--------|------|------|
| [fridge-stream-core](fridge-stream-core/) | Chat backbone: adapters → EventBus → commands / points / admin → game plugins (`plugins/`) | 3850 |
| [fridge-chat-credits](fridge-chat-credits/) | Standalone unique-chatter credits (skip if using Core Credits) | 3854 |
| [fridge-reactive-image](fridge-reactive-image/) | Native audio-reactive avatar | 3851 |
| [fridge-reactive-image-legacy](fridge-reactive-image-legacy/) | Archived Node avatar | — |
| [checklists/](checklists/) | Feature contracts (`Must keep`) | — |

The game plugins and game-side mods (Minecraft, Factorio, Granvir, OpenTTD; ports 3847 / 3852 / 3853 / 3855)
live in their own repo, [flavr-game-plugins](https://github.com/sensokasucks/flavr-game-plugins). Core's `plugins/` folder is empty in git
(installed game folders are git-ignored).

Changelog: [fridge-stream-core/CHANGELOG.md](fridge-stream-core/CHANGELOG.md). Map: [README.md](README.md). Git: [GIT.md](GIT.md).

## Hard rules

- One concern per folder. Platforms = adapters. Games = plugins. Overlays = dumb HTML.
- Prefix is `fridge-`. Do not create new `xsplit-*` folders.
- Bind `127.0.0.1` by default. Do not expose ports.
- Ports above are fixed. Do not renumber.
- Games are plugins (`fridge-stream-core/plugins/<id>/`, [docs/PLUGINS.md](fridge-stream-core/docs/PLUGINS.md)) and opt-in (`minecraft.enabled`, `factorio.enabled`, `granvir.enabled`, `openttd.enabled` default **false**). Core must run with `plugins/` empty. Chat platforms default **off**.
- Do not invent a second copy of a feature a checklist already places in another folder.
- Config admin save **merges** YAML. Never replace the whole file and drop `command_groups` / market blocks.
- Live secrets stay local: `config/config.yaml`, `.env`, `data/`, `*.db`, built jars, `.venv`. Keep `*.example.*`.

## Where to edit

- Chat / commands / points / admin / overlays that are shared → `fridge-stream-core/`
- Anything game-specific (Minecraft, Factorio, Granvir, OpenTTD, a new game) → the flavr-game-plugins repo; never game-specific code in Core itself
- A game needs something new from Core → a generic hook in `core/plugin_api.py`, documented in `docs/PLUGINS.md`
- Standalone credits movie → `fridge-chat-credits/` only when that app is in play; Core Credits is separate (`checklists/credits-core.md`)

After a change: update the matching checklist if an invariant moved, and note it in `fridge-stream-core/CHANGELOG.md` under Unreleased when the behavior is user-visible.
