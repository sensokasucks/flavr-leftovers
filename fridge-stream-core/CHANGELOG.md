# Changelog

All notable changes to **Fridge Stream Core** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are when the work landed in this tree.

---

## [0.18.1] — 2026-09-03

### Fixed

- Admin **Save look** no longer crashes (`Cannot read properties of null`) when a look field is missing — target time included.

### Added

- **Play once, then empty** — overlay goes fully transparent after the stinger. Checkbox: “Leave the screen empty when the roll finishes.” Chat: `!credits clear`.

---

## [0.18.0] — 2026-09-02

### Added

- Core credits now match the standalone Studio roll by default (`style_id: movie`, letterbox / grain / vignette).
- Alerts join the credits: raids, follows, gifts, hosts, cheers, resubs appear even if they never typed. Raid viewer counts / bits / gift qty show under the name.
- Chat commands: `!credits` (count) · `!credits me` · `!credits who "name"` · `!credits roll` / `once` / `live` / `pause` (mod-gated, same permission as `!credit`).
- Legal placeholders `{duration}` `{count}` plus an optional runtime opening card.
- Admin Credits tab: VIP highlight, font / title size, custom font URL, roster CSV, extra Core groups (hosts / cheers / VIPs).

### Changed

- Default movie style label is **Studio**. Subscribe alerts are no longer dumped into Gifted Subs.

---

## [0.17.0] — 2026-09-01

### Added

- Movie credits sequence: opening hold cards → crawl → legal → end hold → stinger.
- Style JSON fields: `studio`, `mpaa`, `opening`, `legal`, `stinger`, `letterbox`, `grain`, `vignette`.
- Overlay letterbox / film grain / vignette (CSS only) + target duration still times the crawl.
- Raid / follow / gifted group blocks remain Core-only.

---

## [0.16.0] — 2026-08-28

Workshop snapshot: Fridge Market wired into Minecraft + Factorio, plus **Granvir** as a new game slot.

### Added

- **Granvir** stats package (`fridge-granvir-stats`) + Core game slot (`games/granvir.py`).
  - BepInEx plugin serves HTTP **:3855** (`GET /stats`, health, overlay pages).
  - Host-only writes (co-op safe). `mock/mock_server.py` for overlay work without the game.
  - Overlays: health, heat, campaign, squad, combined.
  - Config: `granvir.enabled` (default off) + `granvir.bridge_url` (`http://127.0.0.1:3855`).

- **Minecraft × Fridge Market**
  - Chat Dynamo RF = stream power × average `price/base` of configured tickers (default `STEVE`, `FRG`), clamped in Admin → Market.
  - New blocks: `fridge_minecraft:dividend_vault` (eats TRE / RF) and `fridge_minecraft:dividend_chest` (hopper-fed, burns smeltables for furnace XP).
  - Core polls the server mod (`GET /api/market`) and pays pro-rata dividends to `market_holdings` via `store.pay_dividend`.
  - Admin tab **Market**: dynamo symbols / clamp, vault + chest rates, grant shares, test payout, live pending RF/XP.
  - Knobs live in `minecraft.market.*` (hot-saved from the tab; Config tab no longer wipes them).

### Design

- **Fridge Market** — points stock book for chat, game-priced listings, admin events.
  - Spec: [docs/MARKET.md](docs/MARKET.md). Trading commands / admin tab still later.
  - Separate from OpenTTD Chat Fund (`!invest` stays a one-way cash injection).
  - Per-game streamer company, death dip, dividend vault, shared `game.signal` catalog.
  - Optional per-trigger cooldowns (`cooldown_sec` + `cooldown_scope`) so spawn-camps cannot floor a ticker.

### Added

- Factorio **Power Vault** + **Item Vault** flush work to `POST /api/market/dividend`.
  - Power work (MJ) pays `PWR` holders; item counts pay `FACT` holders.
  - Chat Dynamo output is `power_level × (PWR price / PWR base)` (clamped 0.25–3×).
  - Holdings table `market_holdings` + pro-rata `store.pay_dividend` (dust burned if nobody is invested).
- Market **preview tape** (`core/market.py`) ticks seed listings for overlays.
- Overlays: `/overlay/market.html` (ticker), `/overlay/market-board.html`, `/overlay/market-chart.html`.
- Public API: `GET /api/market/state`, `GET /api/market/history`, `POST /api/market/signal` (cooldown-aware).

---

## [0.15.0] — 2026-08-27

### Added

- **OpenTTD game slot** (`games/openttd.py`) — Admin Port client (vanilla + JGRPP).
  - Opt-in `openttd.enabled`; default port 3977.
  - Commands (group `openttd`): `!companies` / `!tickers`, `!quote`, `!invest`, `!ottdfund`, `!ottdsay`, `!ottdpause` / `!ottdunpause`.
  - Chat Fund ledger in SQLite; points debit via Core store.
  - Overlays: `/overlay/openttd.html`, `/overlay/openttd-ticker.html`, `GET /api/openttd/state`.
  - Game Script **FridgeChatFund** (`gamescripts/FridgeChatFund`) applies `ChangeBankBalance` from Admin Port JSON.
  - Does **not** use vanilla/JGR 25% share slots (removed on trunk; exploit-prone on JGR).
  - Docs: `games/OPENTTD.md`.

---

## [0.14.0] — 2026-08-27

### Added

- **Factorio Chat Dynamo** — same stream power source as Minecraft’s Chat Dynamo.
  - Stream Core already computes `power_level` 0–15 from viewers / CPM / commands.
  - `games/factorio.py` now POSTs that snapshot to the Factorio bridge `POST /api/metrics`.
  - Fridge Factorio Stats 1.1.0 adds the `fridge-chat-dynamo` electric-energy-interface. Output scales 0 → startup max MW (default 6 MW at level 15).
  - Bridge RCON command: `/fridge-power <0-15>`. Craft the dynamo or `/fridge-give-dynamo`.

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
