# Checklist — Game plugins

Home: `fridge-stream-core/plugins/<id>/` (one folder per game), loader `core/plugins.py`,
manifests `core/plugin_manifest.py`, contract `core/plugin_api.py`. Spec: [docs/PLUGINS.md](../fridge-stream-core/docs/PLUGINS.md).

## Must keep

- [ ] Core starts, serves the dashboard and runs chat with `plugins/` empty (no game cards, groups, commands or game listings). Test: `tests/test_plugins.py`.
- [ ] A broken plugin (bad JSON, import error, start error, `core_api` newer than Core's `PLUGIN_API_VERSION`) is logged and shown on its card; other plugins and Core keep running.
- [ ] Config stays at the top of `config.yaml` under the plugin id. No migration; defaults come from `plugin.json` `config_defaults` with `enabled` forced **false**.
- [ ] Plugin ids can't take one of Core's own config section names.
- [ ] Old URLs keep working: `/api/stats` (Minecraft), `/api/openttd/state`, every moved `/overlay/*.html`. Plugin routes exist even while the game is off. Core's own `overlay/` wins on a file-name clash.
- [ ] `config/commands.json` wins over a plugin's `commands.json`; plugin defaults only fill gaps and aren't written back unless edited.
- [ ] Group bind: a plugin's group is on only while the plugin is enabled **and** running. The four old ids stay game binds without a plugin.
- [ ] HTTP plugins send `X-Fridge-Core: 1` and use only the paths in the manifest's `http` block.
- [ ] Enabling / disabling a plugin or changing its address says "restart Core"; Market fields apply live.
- [ ] No game-specific code in Core (`main.py`, `core/`, `api/`, `admin/`): it goes in the plugin and reaches Core through a hook in `core/plugin_api.py`.
- [ ] `games/base.py` stays as a re-export of `BasePlugin` / `BaseGameIntegration` for outside code.
- [ ] Games pack: `tools/pack_games.py` zips each plugin folder (tracked files only).

## Drop risks

- A new game wired into `main.py` / `admin_routes.py` by hand instead of a plugin hook.
- Moving a plugin page to a new URL (breaks OBS sources people already have).
- Writing every plugin default command into the user's `commands.json` on save.

## After-change verify

- [ ] `python -m pytest -q` from `fridge-stream-core` (includes `plugins/*/tests`).
- [ ] Start Core with `STREAM_CORE_PLUGINS_DIR` pointing at an empty folder: dashboard loads, Settings → Game plugins shows the empty message.
- [ ] Settings → Game plugins card, Market sub-page, Status row and Sources entries for each installed plugin.
