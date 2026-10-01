# Changelog

All notable changes to **Fridge Stream Core** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are when the work landed in this tree.

---

## Unreleased

### Security

Binding to `127.0.0.1` kept other PCs out, but any web page open in the streamer's browser could still call the local APIs. These changes close that.

- **Local request guard** (`core/local_guard.py`) on Stream Core and standalone Chat Credits: state-changing requests with a foreign `Origin`, requests with a non-loopback `Host` (DNS rebinding), and cross-origin WebSockets get **403**. CORS is limited to loopback origins (was `*`). Game bridges / scripts that send no `Origin` are unaffected. Opt-in LAN names: `core.allowed_hosts` / `core.allowed_origins` (`app.*` for Chat Credits). This also protects the previously open `POST /api/market/dividend` and `/api/market/signal`.
- **Admin token**: `change-me` / empty is no longer accepted. Core generates a random token in `data/admin_token.txt` and prints it at startup; a real `points.admin_token` still wins. Comparison is constant-time. The dashboard no longer pre-fills `change-me`.
- **Permissions are platform-scoped** (breaking for YouTube): plain names match Kick + Twitch logins only; `kick:` / `twitch:` prefixes scope one platform; YouTube needs `youtube:<channel id>` because YouTube "usernames" are copyable display names. Core logs the channel id the first time a YouTube user whose name matches a plain entry chats. `!permit youtube:<name>` works for short-lived YouTube permits.
- **Minecraft mods** (Fabric server + client, NeoForge): HTTP APIs require Core's `X-Fridge-Core: 1` header, no `Origin`, loopback `Host`; `Access-Control-Allow-Origin: *` removed. `/api/execute` (op-level commands) was open to any web page. **Rebuild the jars** alongside this Core.
- **Factorio bridge**: listens on `127.0.0.1` (was all interfaces; `BIND_HOST` to override). `POST /api/metrics` requires Core's header; foreign-origin WebSockets refused.
- **Reactive Image**: HTTP control binds `127.0.0.1` by default; tablets / ESP need **Allow devices on my network** (`control.http_lan`). Browser cross-site requests refused unless `control.allow_cross_site`.
- **Overlays**: `replies.html` and `openttd-ticker.html` escape text before `innerHTML` (chat input / player company names could inject markup on the same origin as `/admin`). Market board/chart escape ticker names (`FridgeMarket.esc`).

### Added

- **Chatter profile pictures** in the chat payload (`user.profile_image_url`) for **YouTube** (from the chat item's author photo, asked at 128 px; `adapters/youtube_avatar.py`) and **Kick** (Kick doesn't send them with chat, so each new chatter's channel is looked up once — `/api/v2/channels/{slug}` → `user.profile_pic` — and cached in `data/kick_avatars.json`, re-checked weekly; 403/429 back off 10 min; `adapters/kick_avatars.py`, toggle `kick.avatars`, default on, Admin → Config → Kick). A Kick chatter's first message goes out immediately; when the lookup lands Core broadcasts `{"type":"user_update","data":{platform, id, username, profile_image_url}}` and patches recent chat history. New EventBus hook `on_user_update` / `publish_user_update`. Twitch pictures are not included yet (anonymous IRC has none; needs Helix or a lookup service). Tests: `tests/test_chat_avatars.py`.
- **Twitch emotes in the chat payload**: `type:chat` now carries `emotes` — ranges into `message` (`start`/`end`, inclusive code points) with `provider`, `id`, `name`, `url`, `static_url`, `animated`. Native Twitch emotes come from the IRC `emotes` tag; **BetterTTV / FrankerFaceZ / 7TV** global + channel emotes (looked up by the channel's `room-id`, refreshed every 30 min, public APIs, no keys) are matched as whole words. Toggle `twitch.third_party_emotes` (default on; Admin → Config → Twitch). The chat overlay renders them; Kick keeps its inline `[emote:id:name]` tokens. `/me` messages no longer show the raw `ACTION` wrapper. New module `adapters/twitch_emotes.py`, tests in `tests/test_twitch_emotes.py`.
- Workshop **feature checklists** in [checklists/](../checklists/) (index + one file per feature). Walk them on every change so admin APIs, config sections, ports, and opt-in defaults are not dropped again. Required by root `AGENTS.md`.

- Credits **style editor** (Admin → Credits): tabbed Motion / Copy / Type / Color / Layout / List, live preview, look presets (Classic, Star Wars, Gold, Neon, Teletype, End card, Name tape, Minimal).
- Overlay motions: `crawl`, `crawl-down`, `starwars`, `cards`, `fade`, `slides`, `ticker`, `typewriter`, plus easing, title intros, name-enter, loop fade/wipe, glow, vignette, edge mask. Spec: [overlay/CREDITS.md](overlay/CREDITS.md).
- Chat-member tickers (`feed: chatter`): base price from channel points, optional live link, consecutive-stream bonus.
- Dividend Chest item value table in Admin → Market (default + furnace XP fallback).
- Steam CCU refresh interval (`market.steam_poll_sec`, default 1800).

### Design

- Admin Market **desk** spec in [docs/MARKET.md](docs/MARKET.md): ticker CRUD, per-stock personalities (walk / jumps / drift), Steam CCU feed via `GetNumberOfCurrentPlayers` (no steamcharts scrape).

### Changed

- Default Minecraft ticker is `MINECRAF` only; Factorio ticker is `FACTORIO` only.
- Chat Kinetic uses the same power level + stock factor as the Chat Dynamo (no extra RPM→FE).
- Dividend Chest is a 54-slot hopper chest and accepts any item.

- Stats overlay widgets are selectable: Admin → Config → Overlay checkboxes (`overlay.modules`).
  - Also per-source: `/overlay/overlay.html?show=health,power` or `?hide=food,armor` (query wins).

## [0.16.1] — 2026-09-01

### Added

- **Factorio ticker mapping** in Admin → Market (and `factorio.market.*`).
  - Chat Dynamo boosts from a comma list of symbols (default `PWR, FACT`).
  - Power Vault and Item Vault each pay a configured ticker (comma = split the payout).
  - Flush thresholds (MJ / items) are editable. Hot-saved; next metrics pulse pushes them to the :3847 bridge.

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
