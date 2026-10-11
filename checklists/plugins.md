# Checklist — Plugins (games and features)

Home: `fridge-stream-core/plugins/<id>/` (one folder per game, empty in git; the games live in [flavr-game-plugins](https://github.com/sensokasucks/flavr-game-plugins)), loader `core/plugins.py`,
manifests `core/plugin_manifest.py`, contract `core/plugin_api.py`. Spec: [docs/PLUGINS.md](../fridge-stream-core/docs/PLUGINS.md).

## Must keep

- [ ] Core starts, serves the dashboard and runs chat with `plugins/` empty (no game cards, groups, commands or game listings). Test: `tests/test_plugins.py`.
- [ ] A broken plugin (bad JSON, import error, start error, `core_api` newer than Core's `PLUGIN_API_VERSION`) is logged and shown on its card; other plugins and Core keep running.
- [ ] Config stays at the top of `config.yaml` under the plugin id; defaults come from `plugin.json` `config_defaults` with `enabled` forced **false** (games and features alike). The only migration is `config_moved_from`: an old block is copied in only while the plugin has none, and the old block is left in the file.
- [ ] Plugin API 1 manifests keep working; API 2 adds `category`, `provides` / `after`, `pages`, `config_moved_from`, `ctx.db`, `ctx.plugins`, `ctx.require_admin`, `ctx.require_game`. Test: `tests/test_plugin_features.py`.
- [ ] Start order: a plugin starts after what its `after` names (ids or `provides` names) and stops before it. `ctx.service()` returns `None` when no provider runs; callers cope.
- [ ] Plugin pages are served only from the plugin's own `pages/` folder (`/plugin-pages/<id>/...`, no `..`), appear in the menu only while the plugin runs, and use the admin token for every API call.
- [ ] A plugin's own data goes in `ctx.db` (its own file), never new tables in Core's `stream_core.db`.
- [ ] `specials`: a core command whose `special` a plugin lists goes to that running plugin's `execute` (its `reply` is said); with the plugin off, nothing is said. Command group `aliases` and `config_moved_from` binds follow the plugin running.
- [ ] No market code in Core: the market is the Gamer Stonks plugin (`ctx.service("market")`); `ctx.market` stays `None`.
- [ ] Plugin ids can't take one of Core's own config section names.
- [ ] Old URLs keep working: `/api/stats` (Minecraft), `/api/openttd/state`, every moved `/overlay/*.html`. Plugin routes exist even while the game is off. Core's own `overlay/` wins on a file-name clash.
- [ ] `config/commands.json` wins over a plugin's `commands.json`; plugin defaults only fill gaps and aren't written back unless edited.
- [ ] Group bind: a plugin's group is on only while the plugin is enabled **and** running. The four old ids stay game binds without a plugin.
- [ ] HTTP plugins send `X-Fridge-Core: 1` and use only the paths in the manifest's `http` block.
- [ ] Enabling / disabling a plugin or changing its address says "restart Core"; `market` fields apply live.
- [ ] No game-specific code in Core (`main.py`, `core/`, `api/`, `admin/`): it goes in the plugin and reaches Core through a hook in `core/plugin_api.py`.
- [ ] `games/base.py` stays as a re-export of `BasePlugin` / `BaseGameIntegration` for outside code.
- [ ] No game plugin folders committed to this repo; `.gitignore` keeps installed ones out. Games and their checklists live in flavr-game-plugins.

## Drop risks

- A new game wired into `main.py` / `admin_routes.py` by hand instead of a plugin hook.
- Moving a plugin page to a new URL (breaks OBS sources people already have).
- Writing every plugin default command into the user's `commands.json` on save.

## After-change verify

- [ ] `python -m pytest -q` from `fridge-stream-core` (also runs `plugins/*/tests` of installed games).
- [ ] The game repo's tests still pass against this Core (`python -m pytest -q` in flavr-game-plugins with `STREAM_CORE_DIR` set).
- [ ] Both repos' **Tests** GitHub Actions run is green on the pull request (`.github/workflows/tests.yml`: Windows + Python 3.10, Linux + 3.12 / 3.13; flavr-game-plugins tests against Core `main`).
- [ ] Start Core with `STREAM_CORE_PLUGINS_DIR` pointing at an empty folder: dashboard loads, Settings → Plugins shows the empty message.
- [ ] Settings → Plugins card, its tab on the Gamer Stonks page (if it has a `market` block), Status row and Sources entries for each installed plugin; a plugin with `pages` gets its menu entry, and `#plg-<id>-<page>` opens it after a reload.
