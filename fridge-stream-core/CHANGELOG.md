# Changelog

All notable changes to **Fridge Stream Core** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are when the work landed in this tree.

---

## [0.11.0] — 2026-08-26

### Added

- **Customizable command groups** in `config.yaml` (`command_groups`).
  - Each group: `enabled`, optional `bind` (`minecraft`, `points`, or any config section), `always`, `description`.
  - `core` is always on. `minecraft` binds to the game (config enabled **and** integration running). `points` binds to `points.enabled`.
  - Add your own groups from Admin → Config or by hand; commands use `"group": "yourid"`.
- **Hot-reload** for groups and `commands.json` — no Core restart.
  - Admin: **Save groups**, **Hot-reload**, **Save + hot-reload** on commands.
  - API: `GET/PUT /api/admin/command-groups`, `POST /api/admin/command-groups/reload`; `PUT /api/admin/commands` reloads the router.
- **Conflict handling** for duplicate command names / aliases.
  - Higher `priority` wins; equal priority keeps the first definition.
  - Admin banner lists token, winner, loser, and reason.

### Changed

- Config tab command editor includes group, handler, priority, and enabled.
- Saving `config.yaml` from the GUI no longer drops `command_groups`.
- Group enablement still follows integration toggles; you can also force a group off while the game stays running.

---

## [0.10.0] — 2026-08-26

### Added

- **Integrations tab** in the admin hub — modular test bench for game integrations.
  - Shared **Command tester**: type `!spawn creeper 2` (or any chat command), choose platform/role, **Dry run** (parse + template only) or **Live execute** (calls the real game integration).
  - **Per-game sub-panels** (Minecraft first; architecture ready for more): status pills, health recheck, command list with one-click Fill / Dry, metrics push (viewers / CPM / power 0–15), overlay URLs + optional preview iframe.
  - Shared overlays list (chat + alerts) for quick copy into OBS / XSplit.
- Admin API:
  - `GET /api/admin/integrations` — catalog of games, commands by group, health, overlay URLs
  - `POST /api/admin/commands/test` — dry-run or live command through the real CommandRouter
  - `POST /api/admin/games/{id}/metrics-test` — synthetic metrics to games + overlays
  - `GET /api/admin/games/{id}/health` — single integration health ping

### Notes for users

1. Open Admin → **Integrations**, paste the admin token if needed.
2. Prefer **Dry run** while tuning templates; use **Live execute** only when the Minecraft (or other) mods are running.
3. Metrics test is the easiest way to exercise Chat Dynamo / power level without live viewer count.

---

## [0.9.0] — 2026-08-25

### Added

- **Streamlabs / StreamElements-compatible alert overlay.** `#alert-box`, `#alert-message`, `#alert-user-message`, `.name`, `.amount`, and kind classes (`follower-alert`, `cheer-alert`, …) match the CSS streamers already use.
- **Skins:** Classic (default streamer look), Card (boxed panel), Custom CSS only (chrome reset so a pack can take over).
- **Custom CSS editor** on the Alert test tab. Saved to `overlay/alerts-custom.css` and picked up live (no Core restart). OBS Custom CSS still works on the same selectors.
- CSS variables (`--alert-accent`, `--alert-font`, `--alert-name-size`, …) for one-line restyles.
- Optional per-kind media in `overlay/assets/alerts/{kind}.gif|.webm|…`
- Notes: [overlay/ALERTS.md](overlay/ALERTS.md)

### Changed

- Default alert look is the classic streamer style (Montserrat, text-shadow, accent name) instead of only the boxed card.

---

## [0.8.0] — 2026-08-25

### Added

- **Alert test tab** in the admin hub. Fire follow / sub / resub / gift / raid / host / bits / Super Chat / donation without a live event.
- **Stream alerts overlay** (`/overlay/alerts.html`) — transparent Webpage source for OBS / XSplit. Admin preview uses `?preview=1` (checkerboard).
- Shared catalog in `core/alerts.py` (`build_alert`, kinds). Admin `GET /api/admin/alerts/kinds` and `POST /api/admin/alerts/test`.
- Paid chat auto-alerts: YouTube Super Chat → `superchat`, Twitch bits → `bits`, other paid → `donation`.
- Config: `overlay.alert_duration_ms` (default 6000, clamped 1500–30000).

### Notes for users

1. Add `/overlay/alerts.html` as a transparent Webpage source.
2. Open Admin → **Alert test**, paste the admin token, click a preset.
3. Tests show a **TEST** badge; live paid events do not.

---

## [0.7.2] — 2026-08-23

### Changed

- **Chat logging is off by default.** Messages still appear on the live overlay; they are not written to SQLite unless `chat_log.enabled: true`.
- **Chat points are off by default.** Enable `points.enabled: true` (or the Config checkbox) to award points and unlock `!points`.
- Config key: `chat_log.enabled` (example, defaults, admin Config tab, wizard).
- Status tab and Chat History tab show whether logging is on.

---

## [0.7.1] — 2026-08-22

### Fixed

- **Tab in `config.example.yaml` crashed a fresh GitHub clone.** PyYAML rejects tab indent (`ScannerError` on `overlay:`). The example file is spaces-only again.
- **Config loader is tab-tolerant.** Existing `config.yaml` copies that still have a tab are rewritten to spaces on startup instead of crashing.
- UTF-8 BOM from Notepad no longer breaks YAML/JSON parse.
- First run of `python main.py` (without `install.bat`) now seeds `config/config.yaml`, `config/commands.json`, and `data/` from the examples.
- `core/store.py` no longer references a non-existent `users.username` column.
- Permission lists accept a single YAML string as well as a list.
- Invalid `commands.json` logs an error and continues instead of crashing startup.
- Missing pip packages print install instructions instead of a raw traceback.
- Python 3.10 is officially supported.

---

*(Earlier history: see previous commits for 0.1.0–0.7.0 — multi-platform chat, admin config GUI, install scripts, points, Minecraft opt-in, rebrand.)*
