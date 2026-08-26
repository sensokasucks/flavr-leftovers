# Fridge Minecraft

Fabric client + server mods for Stream Core integration.

| Mod | Port | Role |
|-----|------|------|
| Client | 3852 | Stats HTTP (health, inventory, deaths) |
| Server | 3853 | Commands + Chat Dynamo / Kinetic redstone |

## Build

- Windows: double-click `BUILD.bat` or see `COMPILE.md`
- Requires JDK 21+

JARs are **not** committed. Build locally and place in your Minecraft mods folder (or `jars/` for reference).

## Config

Stream Core: set `minecraft.enabled: true` and `player_name` in `config/config.yaml` (or use the wizard).
