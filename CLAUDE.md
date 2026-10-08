# Fridge Workshop — Claude Code

Streaming tools from Sensoka's Workshop. Modular local apps + OBS/XSplit Webpage overlays.

Read **[AGENTS.md](AGENTS.md)** and walk **[checklists/](checklists/)** before calling a change done. Start at [checklists/INDEX.md](checklists/INDEX.md).

Style: build streaming plugins based on user needs. Keep everything modular and documented.

## Layout

| Folder | Role | Port |
|--------|------|------|
| [fridge-stream-core](fridge-stream-core/) | Chat backbone: adapters → EventBus → commands / points / admin → game plugins (`plugins/`) | 3850 |
| [fridge-minecraft](fridge-minecraft/) | Fabric client + server mods (+ NeoForge). Mods only; Core is the bridge | 3852 / 3853 |
| [fridge-chat-credits](fridge-chat-credits/) | Standalone unique-chatter credits (skip if using Core Credits) | 3854 |
| [fridge-factorio-stats](fridge-factorio-stats/) | Factorio overlay + Chat Dynamo | 3847 |
| [fridge-granvir-stats](fridge-granvir-stats/) | Granvir BepInEx plugin + mock | 3855 |
| [fridge-reactive-image](fridge-reactive-image/) | Native audio-reactive avatar | 3851 |
| [fridge-reactive-image-legacy](fridge-reactive-image-legacy/) | Archived Node avatar | — |
| [checklists/](checklists/) | Feature contracts (`Must keep`) | — |

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
- Minecraft blocks, HTTP stats, redstone dynamo → `fridge-minecraft/` (then Core `plugins/minecraft/plugin.py` if the API changed)
- Factorio Lua / overlay → `fridge-factorio-stats/` plus Core `plugins/factorio/plugin.py` if the bridge contract changed
- Granvir plugin / mock → `fridge-granvir-stats/` plus Core `plugins/granvir/plugin.json` (http plugin, no Python)
- OpenTTD → Core `plugins/openttd/` (Admin Port client, Chat Fund, game script)
- A new game → a new `plugins/<id>/` folder; never game-specific code in Core itself
- Standalone credits movie → `fridge-chat-credits/` only when that app is in play; Core Credits is separate (`checklists/credits-core.md`)

After a change: update the matching checklist if an invariant moved, and note it in `fridge-stream-core/CHANGELOG.md` under Unreleased when the behavior is user-visible.
