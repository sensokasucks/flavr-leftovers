# Fridge Minecraft Mods

Fabric mods that plug into **[Fridge Stream Core](../fridge-stream-core/)**.

Chat, permissions, commands, metrics, and the overlay all live in Stream Core now.  
This folder only contains the game-side pieces.

## Components

| Piece | Port | Role |
|-------|------|------|
| **client-mod** | `3852` | Live player stats + inventory for the overlay |
| **server-mod** | `3853` | Runs chat commands + Chat Dynamo / Chat Kinetic blocks |

Stream Core talks to both over HTTP. You do **not** need the old Node bridge.

## Install (recommended — pre-built jars)

1. Build with **`BUILD.bat`** (or `./build.sh`), **or** obtain jars from whoever maintains this tree.
2. Finished jars land in **`jars/`**:
   - `fridge-minecraft-client-*.jar`
   - `fridge-minecraft-server-*.jar`
3. Copy **both** into `.minecraft/mods/` (BUILD.bat can do this for you).
4. Install **Fabric API** for 1.21.1 if missing.
5. Remove any old `xsplit-minecraft-*.jar` files.

See **[jars/README.md](jars/README.md)** for exact file names and notes.

## Features

### Client mod (stats)
- Health, hunger, XP/level, armor, active effects, death counter
- Optional inventory snapshot (`!inv` from chat, handled by Core)

### Server mod (commands + power)
- Executes commands Core forwards (`!spawn`, `!give`, `!heal`, etc.)
- **Chat Dynamo** – RF (Team Reborn Energy) + redstone 0–15 from stream metrics
- **Chat Kinetic** – Create-oriented kinetic source (same metrics)

## Build from source

**One command (preferred):**

| OS | Command |
|----|---------|
| Windows | Double-click **`BUILD.bat`** |
| Linux / macOS | `./build.sh` |

Builds client + server, copies jars into `jars/`, and on Windows can install into `%APPDATA%\.minecraft\mods`.

Details: **[COMPILE.md](COMPILE.md)**  
Minecraft **1.21.1** (Fabric). Bump both `gradle.properties` files the same way for other 1.21.x.

Block ids: `fridge_minecraft:chat_dynamo` / `chat_kinetic`. Worlds from the old `xsplit_*` ids need those blocks placed again.

## Run order

1. Start Minecraft with both mods loaded
2. Start **Stream Core** (`python main.py` or `START Stream Core.bat`)
3. Point XSplit / OBS Webpage source at `http://127.0.0.1:3850/` (or `/overlay/overlay.html`)

Configure Kick channel, player name, and permissions in Stream Core’s `config/config.yaml`.  
Commands live in Stream Core’s `config/commands.json`.  
Minecraft integration is **off by default** in Core — set `minecraft.enabled: true` when the mods are running.

## Architecture (current)

```
Kick ──► Stream Core ──HTTP──► client-mod (:3852)  stats
              │
              └──HTTP──► server-mod (:3853)  commands + Chat Dynamo
              │
              └── serves overlay on :3850
```

---

Legacy Node bridge and duplicate overlay were removed; use Stream Core instead.
