# Game plugins

Every game Stream Core talks to is a plugin: a folder in `fridge-stream-core/plugins/`.
Core runs fine with none. Each folder that is there adds a card under
**Settings → Game plugins**, its chat command group, its overlays, its Market listings and
(if it has market settings) a sub-page on the **Market** page.

Bundled: `minecraft`, `factorio`, `granvir`, `openttd`. They are also shipped on their own
as the **games pack** zip (`tools/pack_games.py`), for a Core install that came without them.

Plugins are ordinary Python running inside Core with no sandbox. Install only plugins you trust.

## Installing / removing

- Install: copy the plugin's folder into `plugins/` (so you get `plugins/<id>/plugin.json`), restart Core.
- Switch on: Settings → Game plugins → tick **Enabled** → **Save & apply** → restart Core.
- Remove: switch it off, delete its folder, restart Core. Its settings stay in `config.yaml`
  (harmless) in case you put it back.

Settings live at the top of `config.yaml` under the plugin's id (`minecraft:`, `openttd:` ...),
same as before games became plugins. Nothing moves when you install or remove one.

A plugin that can't load (bad `plugin.json`, Python error, made for a newer Core) shows its
error on its card and in the log; the rest of Core keeps running.

## Two kinds

| Kind | You write | Good for |
|------|-----------|----------|
| `http` | only `plugin.json` | A game that already has its own bridge program (a mod, a BepInEx plugin, a Node server) answering HTTP. Core's built-in client sends it chat commands and live metrics. Granvir works this way. |
| `python` | `plugin.json` + a class | Anything Core itself has to do: speak a game's own protocol (OpenTTD's Admin Port), market vaults (Minecraft, Factorio), own API routes. |

## Folder

```
plugins/<id>/
  plugin.json        manifest (required)
  plugin.py          python kind: the class named in "entry"
  commands.json      default chat commands (optional; group defaults to <id>)
  overlay/           pages served at http://127.0.0.1:3850/overlay/<file> (optional)
  README.md          notes for people installing it (optional)
  tests/             unit tests, picked up by pytest (optional)
```

`<id>`: 2-32 lowercase letters, digits or `_`, starting with a letter, same as the folder
name, and not one of Core's own config sections (`core`, `market`, `points` ...).

## plugin.json

```json
{
  "id": "mygame",
  "name": "My Game",
  "version": "1.0.0",
  "core_api": 1,
  "kind": "http",
  "description": "One or two sentences for the dashboard card.",
  "links": [{"name": "My Game bridge", "url": "https://example.com/bridge"}],
  "config_defaults": {"bridge_url": "http://127.0.0.1:3860"},
  "command_group": {"description": "My Game commands (!boost, !slow)"},
  "settings": [
    {"key": "bridge_url", "label": "Bridge URL", "type": "url", "placeholder": "http://127.0.0.1:3860"}
  ],
  "http": {
    "base_url_key": "bridge_url",
    "health": "/stats",
    "stats": "/stats",
    "execute": "/command",
    "metrics": "/api/metrics"
  },
  "bridge_overlays": [{"name": "Stats overlay", "path": "overlay.html", "notes": "What it shows"}]
}
```

| Key | Meaning |
|-----|---------|
| `core_api` | Plugin API version the plugin needs. This Core has **1**. A higher number is refused with "update Stream Core". |
| `kind` | `python` (default) or `http`. |
| `entry` | python kind: `"module:ClassName"`, e.g. `"plugin:MinecraftIntegration"` for `plugin.py`. |
| `config_defaults` | The plugin's block in `config.yaml`, filled in under whatever the user has. `enabled` is always forced to `false` by default (games are opt-in). |
| `command_group` | Its group in Settings → Command groups. Bound to the game running: the group's commands only work while the plugin is running. |
| `settings` | Fields on its card (see field types). |
| `market` | `{"title", "hint", "fields": [...]}`: a sub-page on the Market page. Saved through `PUT /api/admin/plugins/<id>/settings` and applied live (no restart). Fields may carry `"group"` to split them into boxes. |
| `market_books` | Listings to seed on the Market, e.g. `{"symbol": "MINECRAF", "name": "Minecraft", "price": 10}`. Book is `game:<id>`. |
| `overlays` | Pages in the plugin's `overlay/` folder: `{"name", "file", "notes"}`. Listed under Sources & overlays and Integrations. |
| `bridge_overlays` | Pages the bridge program serves itself: `{"name", "path", "notes"}`, joined to the bridge URL. |
| `http` | http kind only (below). |

### Field types

`text`, `url`, `password`, `number` (`min`, `max`, `step`, `nullable`), `checkbox`,
`list` (comma separated, `upper: true` to upper-case), `lines` (one per line),
`map` (`key: value` per line, numbers as values), `select` (`options`).
Every field has `key` (dotted for nested keys: `market.vault_symbol`), `label`, and optional
`help` and `placeholder`.

### http block

All paths are relative to the address in the setting named by `base_url_key`.
Each request carries the header `X-Fridge-Core: 1`, which Fridge bridges require for writes.

| Key | Request | |
|-----|---------|---|
| `health` | `GET` | 200 = healthy. A JSON body is kept as the latest stats. |
| `stats` | `GET` | Stats for overlays that ask Core (optional). |
| `execute` | `POST {"command", "args", "qty", "user", "platform"}` | Approved chat command of the plugin's group. Answer `{"success": true}` or `{"success": false, "error": "..."}`; a `"reply"` is said back in chat. |
| `metrics` | `POST {"viewers", "cpm", "commands", "powerLevel"}` | Every 2 s while running (powerLevel 0-15). |
| `execute_error_hint` | | Shown when the bridge can't be reached. |

## Python plugins

```python
from core.plugin_api import BasePlugin
from core.models import ExecuteRequest

class MyGame(BasePlugin):
    name = "mygame"

    async def start(self):
        s = self.ctx.section                      # this plugin's config block, live
        self.enabled = bool(s.get("enabled"))

    async def stop(self):
        ...

    async def execute(self, req: ExecuteRequest) -> dict:
        return {"success": True, "reply": f"{req.command_name} done"}
```

`self.config` is Core's whole live config (a dashboard save is seen at once), `self.ctx` a
`PluginContext`:

| | |
|-|-|
| `ctx.section` | this plugin's config block |
| `ctx.data_dir` | `data/plugins/<id>/` for files the plugin keeps (create it on first use) |
| `ctx.folder` | the plugin's own folder |
| `ctx.market` | the Fridge Market tape (`quote`, `upsert`, `apply_return`, `try_signal`) |
| `ctx.store` | points / users (`get_or_create_user`, `pay_dividend` ...) |
| `ctx.core_url()` | `http://127.0.0.1:3850` (or the configured address) for overlay links |
| `await ctx.reply(platform, text, to_user)` | say something in chat as Core |
| `await ctx.alert(payload)` | send an alert to the alerts overlay |
| `ctx.broadcast` | send a WebSocket message to every overlay |

Optional methods Core uses when they exist:

| Method | Used for |
|--------|----------|
| `on_metrics(snap)` | live viewers / CPM / power level every 2 s |
| `health()` | Integrations → Recheck health |
| `overlay_catalog()` | overlay links built at run time |
| `status()` | extra fields on the Status page (`detail`, `error`) |
| `async state_fragment()` | keys merged into the overlay `update` payload (Minecraft: `stats`, `inventory`) |
| `market_status()` | lines of live numbers on its Market sub-page |
| `apply_config(config)` | after a dashboard save |
| `@classmethod routes(cls, router, get_running)` | own API routes; they exist even while the game is off, `get_running()` returns the running instance or `None` |
| `@staticmethod dividend_defaults(body, market_cfg)` | symbol / rates for `POST /api/market/dividend` from a bridge that sends none |

Import the plugin's own modules relatively (`from .admin import Client`): the folder is loaded
as the package `plugins.<id>`.

## Rules the bundled plugins keep

- Old addresses keep working: `/api/stats`, `/api/openttd/state`, `/overlay/openttd.html` and
  the other moved pages answer at the same URLs. Core's own `overlay/` wins on a name clash.
- The user's `config/commands.json` wins over a plugin's `commands.json` for the same name;
  plugin commands only fill in what the file doesn't have. Commands left at their plugin
  default aren't written back into the file when the dashboard saves.
- Turning a plugin on or off, or changing its address, needs a Core restart. Market fields don't.

## Tests

`python -m pytest -q` from `fridge-stream-core` runs Core's tests and every `plugins/*/tests`
(without pytest: `python -m unittest discover -s tests` and `python -m unittest discover -s plugins -t .`).
Plugin loading itself: `tests/test_plugins.py`. `STREAM_CORE_PLUGINS_DIR` points Core at
another plugins folder (used by the tests for an empty one).
