# Changelog

All notable changes to **Fridge Stream Core** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are when the work landed in this tree.

---

## [0.13.1] — 2026-08-27

### Fixed

- Admin Credits API was missing the movie-cast fields and write routes, so the Credits tab could not load styles, pin jobs, or change `!credit` permission after 0.13.0.
  - `GET /api/admin/credits` now includes `cast` (styles, current style, pins, `command_permission`, job cap).
  - Added `PUT /credits/cast/style`, `PUT /credits/cast/file`, `POST /credits/cast/pin`, `PUT /credits/command-permission`.

---

## [0.13.0] — 2026-08-26

Movie-style end credits on top of the 0.12 unique-chatter roll. Same day as 0.12.x.

### Added

- **Cast styles** in `config/cast/*.json` (shipped style: `movie.json`). Copy that file to add another look. Styles are `names` (plain roster) or `movie` (departments + jobs).
- **Persistent job pins** in `data/cast_overrides.json` — survive session reset and roll.
- **Groups** from the style file: mods, subs, starring (top talkers). Core also tags raiders / followers / gifted-subs from the alert bus.
- Chat commands (group `credits`, binds to `credits.enabled`):
  - `!credit "name" "job title"` — pin a job (aliases `!job`, `!cast`).
  - `!credit "name" clear` — unpin.
  - `!credits` — unique chatter count.
- `credits.command_permission`: `mod` (default), `admin`, or `public`.
- Job titles capped at **50** characters.
- Command group `credits` in `config.yaml` / admin Config (hot-reload with the rest of the groups).
- Same movie-cast module lives in standalone **fridge-chat-credits** (`core/cast.py` + control desk), so the :3854 app can use the same styles without Core.

### Changed

- Credits overlay uses a pixel `requestAnimationFrame` crawl (`credits.speed_px_per_sec`) so XSplit/OBS CEF actually scrolls (CSS `@keyframes` + `translateY(%)` did not).
- Admin → Credits can pick a cast style and show pinned jobs.

### Docs

- Root workshop README links here: [fridge-stream-core/CHANGELOG.md](CHANGELOG.md).

---

## [0.12.1] — 2026-08-26

### Added

- **Factorio** as a first-class Stream Core game slot (same pattern as Minecraft).
  - Config: `factorio.enabled` (default off) + `factorio.bridge_url` (default `http://127.0.0.1:3847`).
  - Admin → Config card, Status → Game integrations, Integrations → Factorio panel with overlay URLs.
  - Health check hits the existing Fridge Factorio Stats bridge `GET /stats`.
  - Command group `factorio` binds to the integration running (stats/overlay only — no factory chat commands yet).

---

## [0.12.0] — 2026-08-26

### Added

- **Chat credits** as a built-in, opt-in Core feature (`credits.enabled`, default off).
  - Unique chatters from the same Kick / Twitch / YouTube adapters as live chat.
  - Overlay: `/overlay/credits.html` (transparent Webpage source).
  - **Admin → Credits** tab: enable/disable (hot-applied), roll / loop / once / hold, look editor, test names, live preview.
  - Public overlay API: `GET /api/credits/{theme,roster,play}`; admin API under `/api/admin/credits/*`.
  - Session list saved to `data/credits_session.json`.
- Config tab checkbox for credits enable (look still lives on the Credits tab).
- Status hub shows credits on/off and unique count.
- Sources list points at the built-in overlay (standalone app on :3854 remains optional).

### Notes

1. Enable Kick/Twitch/YouTube as usual so there is chat to collect.
2. Open Admin → **Credits**, tick Enabled, Save enable — no Core restart.
3. Add `/overlay/credits.html` in XSplit/OBS. Use **Roll credits** at the end of a stream to freeze the list.

---

## [0.11.1] — 2026-08-26

### Fixed

- `core.command_groups` now exports both `resolve_active_groups` and `catalog_status` (admin Status tab) plus a `CommandGroups` compatibility class.
- `main.py` import of command groups is indented inside the `try` so Core can start.

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
