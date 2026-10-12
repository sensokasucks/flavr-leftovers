# Plugins

Every game Stream Core talks to is a plugin: a folder in `fridge-stream-core/plugins/`.
A plugin can also add a feature to Core itself (`"category": "feature"`), such as the
**Gamer Stonks** market (`plugins/stonks` in flavr-game-plugins; it used to be built into Core).
Core runs fine with none. Each folder that is there adds a card under
**Settings → Plugins**, its chat command group, its overlays, and (if it has `pages`) its
own pages in the dashboard menu.

Minecraft, Factorio, Granvir and OpenTTD don't ship with Core. They live in their own repository,
**[flavr-game-plugins](https://github.com/sensokasucks/flavr-game-plugins)** (its Releases page has a zip), together with the
game-side mods and bridges (Fabric / NeoForge mods, Factorio Lua + bridge, Granvir BepInEx plugin).

Plugins are ordinary Python running inside Core with no sandbox. Install only plugins you trust.

## Installing / removing

- Install: copy the plugin's folder into `plugins/` (so you get `plugins/<id>/plugin.json`), restart Core.
  Or keep a clone of flavr-game-plugins somewhere and start Core with `STREAM_CORE_PLUGINS_DIR`
  set to its `plugins` folder; `git pull` there then updates the games.
- Switch on: Settings → Plugins → tick **Enabled** → **Save & apply** → restart Core.
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
| `python` | `plugin.json` + a class | Anything Core itself has to do: speak a game's own protocol (OpenTTD's Admin Port), own API routes, own database, a whole feature (Gamer Stonks). |

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
| `core_api` | Plugin API version the plugin needs. This Core has **2**. A higher number is refused with "update Stream Core". Ask for 2 when you use anything marked *(2)*. |
| `kind` | `python` (default) or `http`. |
| `category` *(2)* | `game` (default) or `feature` (adds something to Core, e.g. a market). Features get their own heading on Settings → Plugins. Both are opt-in. |
| `provides` *(2)* | Names other plugins can ask for: `["market"]`. See *Plugins using each other*. |
| `after` *(2)* | Plugin ids or `provides` names to start after, when installed: `["market"]`. They also stop before them. |
| `pages` *(2)* | Its own dashboard pages: `{"id", "title", "file", "nav", "keywords"}`. See *Dashboard pages*. |
| `config_moved_from` *(2)* | Old config sections this plugin's settings used to live in: `["market"]`. See *Moving settings*. |
| `entry` | python kind: `"module:ClassName"`, e.g. `"plugin:MinecraftIntegration"` for `plugin.py`. |
| `config_defaults` | The plugin's block in `config.yaml`, filled in under whatever the user has. `enabled` is always forced to `false` by default (games are opt-in). |
| `command_group` | Its group in Settings → Command groups. Bound to the game running: the group's commands only work while the plugin is running. `"aliases": ["market"]` *(2)* also binds an older group name to this plugin (commands.json files that still say `"group": "market"`). |
| `specials` *(2)* | Command specials this plugin answers: `["market_buy", "market_sell"]`. A `commands.json` command with `"handler": "core"` and one of these `special`s is passed to the plugin's `execute(req)` (`req.special` is set) and its `{"reply": ...}` is said in chat. This is how a plugin takes over commands Core used to answer without the user editing their commands file. |
| `settings` | Fields on its card (see field types). |
| `market` | `{"title", "hint", "fields": [...]}`: a tab on the Gamer Stonks page (Gamer Stonks reads it with `ctx.plugins.manifest(id)`; Core itself no longer does). Saved through `PUT /api/admin/plugins/<id>/settings` and applied live (no restart). Fields may carry `"group"` to split them into boxes. |
| `market_books` | Listings Gamer Stonks seeds, e.g. `{"symbol": "MINECRAF", "name": "Minecraft", "price": 10}`. Book is `game:<id>`. Read by Gamer Stonks, not Core. |
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
| `ctx.market` | always `None` since the market became the Gamer Stonks plugin. Use `ctx.service("market")` with `"after": ["market"]` (below). |
| `ctx.store` | points / users (`get_or_create_user`, `adjust_points`, `pay_dividend` ...) |
| `ctx.db` *(2)* | the plugin's own SQLite file, `data/plugins/<id>/<id>.db` (below) |
| `ctx.plugins` *(2)* | the other plugins: `running(id)`, `installed(id)`, `ids()`, `service(name)`, `class_hook(id, name)`, `manifest(id)` |
| `ctx.service(name)` *(2)* | same as `ctx.plugins.service(name)` |
| `ctx.require_admin(token)` *(2)* | in a plugin route: 401 unless it is Core's admin token (the dashboard sends it as `X-Admin-Token`) |
| `ctx.require_game(request)` *(2)* | in a plugin route only games / bridges may call (it spends or mints points): 403 for web pages, and from another device without the admin token. Same check as the game WebSocket `hello`. |
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
| `market_status()` | lines of live numbers on its Gamer Stonks tab |
| `service(name)` *(2)* | what another plugin gets from `ctx.plugins.service(name)` for each name in `provides` (without it, the plugin itself) |
| `apply_config(config)` | after a dashboard save |
| `async on_flag(payload)` | a chatter set off one of the streamer's custom flags (Red flags page) that has **Tell game plugins and overlays** on: `{flag: {id, name}, first, phrase, platform, message, message_id, user: {id, username, display_name, is_mod, is_subscriber}, hidden, timestamp}`. `first` = they just got the flag; `hidden` = they are red-flagged (show nothing of theirs). `ctx.bus.on_flag(handler)` gets the same. |
| `@classmethod routes(cls, router, get_running)` | own API routes; they exist even while the game is off, `get_running()` returns the running instance or `None` |
| `@staticmethod dividend_defaults(body, market_cfg)` | symbol / rates for Gamer Stonks' `POST /api/market/dividend` from a bridge that sends none |

## Plugins using each other *(2)*

A plugin that offers something to others lists it under `provides` and may write `service(name)`:

```python
class Market(BasePlugin):          # plugin.json: "provides": ["market"]
    def service(self, name):
        return self.tape if name == "market" else None
```

Another plugin asks for it when it starts (put `"after": ["market"]` in its manifest so the
market is running by then) and copes with `None`: the other plugin may not be installed or on.

```python
async def start(self):
    self.market = self.ctx.service("market")     # None when there is no market
```

`ctx.plugins.class_hook(id, name)` reaches a class-level hook (a `@staticmethod`) of an installed
plugin, running or not; `ctx.plugins.manifest(id)` reads another plugin's `plugin.json`, so a
feature can use keys it defines itself (the way Gamer Stonks reads every game's `market` block).

## Own database *(2)*

`ctx.db` is the plugin's own SQLite file, so removing the plugin never touches Core's
`stream_core.db`. Calls run off the event loop; rows come back as dicts.

```python
await self.ctx.db.script("CREATE TABLE IF NOT EXISTS holdings (user_id INTEGER, symbol TEXT, qty INTEGER)")
await self.ctx.db.execute("INSERT INTO holdings VALUES (?, ?, ?)", (uid, "FRG", 5))
rows = await self.ctx.db.fetchall("SELECT * FROM holdings WHERE user_id = ?", (uid,))
row = await self.ctx.db.fetchone("SELECT qty FROM holdings WHERE user_id = ? AND symbol = ?", (uid, "FRG"))
await self.ctx.db.transaction(lambda conn: ...)   # plain sqlite3 inside one transaction
```

Points stay in Core: use `ctx.store` (`get_or_create_user`, `get_user`, `adjust_points`).

## Dashboard pages *(2)*

```json
"pages": [{"id": "main", "title": "Gamer Stonks", "file": "pages/index.html", "nav": "On stream",
           "keywords": "market stocks tickers"}]
```

Each page gets an entry in the dashboard menu under `nav` (`On stream`, `Overlays`, `Games`,
`People` or `Settings`; default `Games` for games, `On stream` for features) while the plugin is
running. The file must be in the plugin's `pages/` folder; everything in that folder is served at
`/plugin-pages/<id>/...` (so `pages/app.js` is `app.js` next to the page). The dashboard shows the
page in a frame at `#plg-<id>-<page id>`. Start the page with:

```html
<link rel="stylesheet" href="/admin/admin.css" />
<script src="/admin/plugin-page.js"></script>
```

`plugin-page.js` gives the page the dashboard's look (high contrast too), keeps the frame as tall
as the page, and offers `StreamCore.api(path, opts)` (fetch with this browser's admin token, JSON
back, errors thrown), `StreamCore.token()`, `StreamCore.escapeHtml(text)`,
`StreamCore.go(tab, sub)` (open another dashboard page) and `StreamCore.resize()`.
The page talks to the plugin's own routes; protect them with `ctx.require_admin`.

## Moving settings *(2)*

A plugin that takes over something Core used to do can keep the user's settings:
`"config_moved_from": ["market"]` copies the `market:` block of `config.yaml` into the plugin's
own block (under its id): anything the plugin's block doesn't set yet comes from the old one, so
turning the plugin on keeps the user's settings. The old block stays in the file, so an older
Core still finds it. The plugin's `config_defaults` fill in anything missing.

Import the plugin's own modules relatively (`from .admin import Client`): the folder is loaded
as the package `plugins.<id>`.

## Rules the bundled plugins keep

- Old addresses keep working: `/api/stats`, `/api/openttd/state`, `/overlay/openttd.html` and
  the other moved pages answer at the same URLs. Core's own `overlay/` wins on a name clash.
- The user's `config/commands.json` wins over a plugin's `commands.json` for the same name;
  plugin commands only fill in what the file doesn't have. Commands left at their plugin
  default aren't written back into the file when the dashboard saves.
- Turning a plugin on or off, or changing its address, needs a Core restart. Fields on a plugin's Gamer Stonks tab don't.

## Tests

`python -m pytest -q` from `fridge-stream-core` runs Core's tests and every `plugins/*/tests`
(without pytest: `python -m unittest discover -s tests` and `python -m unittest discover -s plugins -t .`).
Plugin loading itself: `tests/test_plugins.py`. `STREAM_CORE_PLUGINS_DIR` points Core at
another plugins folder (used by the tests for an empty one).
