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

- **Config save bar.** Admin → Config (Core + platforms, Games, Points + chat, Advanced) keeps **Save & apply** pinned under the top bar while you scroll, flags *Unsaved changes* after an edit or **Reset form to defaults**, and saves with **Ctrl+S** (Cmd+S). The status line shows the server's reply, including which chat platforms reconnected.
- **Chat platform settings apply without a restart.** Saving Config in the admin page reconnects only the platforms (Kick, Twitch, YouTube) whose settings changed; turning one on or off, switching channel or YouTube video takes effect at once. Hand edits to `config.yaml` are picked up within a couple of seconds (`core.watch_config`, default on; a file that fails to parse is ignored and the running settings kept). Status tab has a **Reconnect** button per enabled platform (`POST /api/admin/platforms/{kick|twitch|youtube}/reconnect`). Switching Kick channel drops the old channel's cached `chatroom_id` so the new one is looked up. A platform that is enabled but could not start (channel not set, chatroom lookup failed) now shows as stopped instead of running. Game toggles and the port still need a restart. Tests: `tests/test_platform_reload.py`.
- **Stage curtain control** for Stream Rooms' new curtain: Admin → Live controls → *Stage curtain* (Reveal / Close / Open, shows whether it's open), `POST /api/admin/stage`, and mods' `!curtain open|close|reveal` (chat games, feature `stage`). Protocol: `stage` frames to the game, `stage_state` back (docs/REACTIONS.md).
- **Chat games + crowd moments** (`core/chat_games/`, Admin → **Chat games**, `chat_games:` in config, docs/CHAT_GAMES.md). Off by default; each feature has its own switch and command names; a `commands.json` command or a reaction with the same name wins (the page lists clashes).
  - Crowd moments: **emote combos** (3+ people using one mood's emotes within 10 s → the room reacts; 9 moods from the Kick / Twitch / YouTube global emotes + emoji, editable), **hype meter** (different chatters in the last minute, levels 5 / 10 / 20 fire crowd moments), **cheer vs boo** tug of war, **group launch** (`!launch`, countdown → lights, spotlight, fireworks).
  - Points games: `!claim` (once per stream), `!predict` (mods open / lock / settle / cancel; winners split the pot, nobody right → refunds), `!duel @name` + `!accept` / `!decline`, `!slots` (~93% back), `!heist` + `!join`. All stakes go through the one points ledger (`source="game"`).
  - Watch-along: polls (`!poll Q | A | B`, chat votes `!1` `!2`), `!rate 1-10` (average on screen and in the end credits), `!request` / `!bump` / `!queue`, `!clip` / `!moment` (stream time, CSV), trivia (`!trivia`, `!answer`; questions in `config/trivia.json`, 45 shipped in `trivia.example.json`).
  - Regulars: `!streak` (streams in a row; a stream = chat after a 4 h quiet gap, or Admin → Start a new stream), titles at 5 / 10 / 25 streams on the chat packet (`user.title`, Stream Rooms name tags) and in the credits (`title_note`), `!seat front|back` (front costs points, refunded if no seat is free), `!swap @name`.
  - **Boards**: new `board` / `board_clear` / `board_history` WebSocket packets (polls, predictions, hype, tug, launch, heist, trivia, rating), drawn by Stream Rooms and `/overlay/replies.html` (`?boards=0`, `?replies=0`).
  - Admin page: live controls (poll, prediction, trivia, rating, request queue, moments + CSV, new stream, **Test chat** that runs a line through the whole live path), settings form, combo mood editor; Live controls card. Routes `GET/PUT /api/admin/chat_games`, `POST …/action`, `POST …/simulate`, `GET …/moments.csv`.
  - Store: `streams` + `stream_attendance` tables; `data/chat_games.json` keeps requests, moments, ratings, trivia progress. New command group `chat_games`. `!help` lists reaction + chat game commands too.
- **New reactions** (seeded once into existing configs): `!sign <text>`, `!sleep` / `!snack` / `!phone`, `!highfive @name`, and the Kick emotes FLASHBANG, POLICE (🚨), ThisIsFine, DonoWall. New effects `crowd_motion`, `sign`, `seat_prop`, `highfive`, `seat_move`, `seat_swap`, `stage_fire`, `fireworks` (overlay too), `lights` modes `flash` / `police`. `{args}` in a reaction's settings = what was typed after the command.
- **Emote pictures for thrown emotes**: Core learns emote name → picture from chat, so an object like `KEKW` is drawn as the emote (game + fallback overlay).
- `ReactionEngine.play()` for Core-played effects (`"system": true`, optional `crowd`, refunds on `dropped`).
- **Reaction pictures.** A reaction's Object can be `img:<name>` to throw / drop / float a PNG, JPEG or animated GIF instead of an emoji. Upload and delete them in **Admin → Config → Reactions → Pictures** (5 MB cap, type checked from the file bytes, stored in `data/reaction_images/`); built-ins live in `overlay/assets/reactions/`. Core serves them at `GET /reactions/images/<file>` and adds `params.object_image {name, url, animated}` to reaction packets; Stream Rooms and `/overlay/reactions.html` draw the picture. New built-in **Boot** entry (`!boot`, 🥾, `img:boot`). New defaults are seeded into existing configs once (`reactions.seeded_defaults`), so deleting one sticks. `core/reaction_images.py`, `tests/test_reaction_images.py`.
- **Command replies carry who they answer.** The `/ws` `reply` frame now has `id`, `reply_to_user` (display name), `reply_to_message_id`, `source` (`command` / `reaction` / `game`), `timestamp` and `posted_to_chat` (always false until a platform can be posted to). New sockets get `reply_history` (last 20). This feeds Stream Rooms' new reply screen above the main screen: Core can't post into Kick / YouTube chat without an API login, so the reply screen and `/overlay/replies.html` are where viewers see answers. `ChatReply.source` added.
- **Credits: standalone Chat Credits engine merged into Core's credits** (`overlay/credits.js` / `.css` / `.html`, Admin → Credits). New **Matrix** motion (glyph rain, names decode a screen at a time; `matrix_density`) and preset; **Teletype** now types character by character with a caret (`typewriter_cps`, `typewriter_unit` line / card / page, or `name` for the old whole-name reveal with `type_ms`); page motions paginate by screen height instead of one block per page (`title_own_page` keeps the title on its own page); **letterbox** and **film grain**; **Play once, then clear** (`mode: clear`, or `clear_when_done`); movie styles can add opening cards, starring, special thanks, legal lines, an end hold and a post-credits stinger in their JSON (`core/cast.py` passes them through); dotted crew lists go two-up with 2+ columns. Look / roster changes redraw in place (a crawl keeps its position) instead of restarting the roll; motion changes still hard-reset. Kept from Core: easing, loop transitions, title intros, edge fade, glow, VIP colour, weights, sizes, alignment, job layouts, name enter + stagger, one appearance per person in movie rolls. The overlay also runs under standalone Chat Credits (`/api/credits/*` first, then `/api/*`).
- **Credits look sanitizer** `sanitize_look()` in `core/credits_theme.py`: standalone key names convert (`sw_tilt_deg`, `sw_perspective_px`, `page_hold_sec`, `page_fade_sec`), motion aliases (`teletype`, `nametape`), enum fallbacks and number clamps. Unknown keys pass through. Used by `CreditsEngine.configure()` and `apply_theme()`.
- **Admin → Credits**: Play once then clear, Restart roll, Download CSV (`GET /api/admin/credits/roster.csv`), live roster / play state over the WebSocket, list shows mods, message counts, sub / VIP / paid and movie jobs. Style editor: Matrix motion + preset, typewriter unit / speed, matrix density, letterbox, grain, clear-when-done, title-own-page, Share Tech Mono font. **Admin → Config → Chat credits**: ignore list, shortest message that counts, leave own channel out.
- Credits remember paid chatters (`is_paid`, for `paid` / `donors` job pools). Docs: `overlay/CREDITS.md`, new `overlay/MOTIONS.md`. Tests: `tests/test_credits.py`.
- **Several at once from a reaction command**: `!tomato x5`, `!tomato 5`, `!tomato @bob 5`, `!tomato screen x5` fire five (capped by the entry's **Max per message**, each one costs, same as `🍅🍅🍅`). A bare number only counts on its own or after an `@mention`, so `!tomato presenter 2` still aims at presenter 2. New per-entry **Per command** (`command_count`, default 1): how many a command fires when no number is typed, for things like a `!barrage` of 10. Tests in `tests/test_reactions.py`.
- **Chat reactions** (`core/reactions.py`, off by default: `reactions.enabled`). An emoji (🍅), emote name or `!command` in chat plays an effect — throw, pile up, float up, drift down, rain, confetti, wiggle, stand and cheer, big shout, stadium wave, spotlight, room lights, camera shake, applause meter — in Stream Rooms, or on the new fallback overlay **`/overlay/reactions.html`** when no game is connected. Core owns the rules: permission (public / mod / admin) plus optional sub/VIP requirement, per-user / global / per-target cooldowns, point costs from the Core ledger (`source=reaction`, refunded if the game drops it), `!nothrow` / `!throwok` opt-out/in (`data/reactions_optout.json`), `!targets`, and chat replies (emoji triggers stay silent). `🍅 @bob` / `!tomato @bob` / `!tomato screen` aim at an audience member, a stage spot or a guest. Edit everything in **Admin → Config → Reactions** (hot-applied, with a free Test button and a recent-reactions log). New command group `reactions`. Spec + WebSocket protocol: [docs/REACTIONS.md](docs/REACTIONS.md). Tests: `tests/test_reactions.py`.
- **Game ↔ Core WebSocket frames**: a game on `/ws` can now send JSON `hello` (with its effect list, which the Reactions editor uses), `room_state` (targets / guests / seated), `reaction_result`, `say` (rate-limited line through Core's reply path) and `overlay` (relayed as `game_overlay`). Only a socket that sent `hello` may use them; other frames are ignored as before.
- `Store.spend_points()`: atomic check-and-debit that refuses instead of clamping to 0.
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

- **Admin dashboard navigation rebuilt.** New **Live controls** landing page (running platforms / games, viewers, credits roll buttons, one-click test alerts, dry-run command box). Flat sidebar with every page visible (no collapsible groups); **Settings** lists Core + chat platforms, Games, Points, Reactions, Command groups, Chat commands and Advanced as separate pages (the Save config.yaml bar shows only on the pages it saves). Pages with sections show one section at a time from a tab strip — the accordions, and Expand / Collapse all, are gone. Credits and Alerts keep the preview in a column beside every section. Page addresses (`#credits/style`) so Back and bookmarks work. **Search** (`/`) over pages and individual settings jumps to and highlights the field. Admin token field folds away once saved. Live buttons press the same buttons as the feature pages, so there's one code path per action.
- Admin **Config save** keeps the live `reactions` block (it is only changed from the Reactions editor).

- Default Minecraft ticker is `MINECRAF` only; Factorio ticker is `FACTORIO` only.
- Chat Kinetic uses the same power level + stock factor as the Chat Dynamo (no extra RPM→FE).
- Dividend Chest is a 54-slot hopper chest and accepts any item.

- Stats overlay widgets are selectable: Admin → Config → Overlay checkboxes (`overlay.modules`).
  - Also per-source: `/overlay/overlay.html?show=health,power` or `?hide=food,armor` (query wins).

### Fixed

- `/overlay/replies.html` showed every reply twice (once from the `reply` frame, once from the system chat line); it now uses `reply` only, shows `@name`, and catches up from `reply_history`.
- Recent chat / alert history handed to new WebSocket clients could go stale once the list was trimmed (the trim built a new list; the API kept the old one). Lists are trimmed in place now.
- Credits: look keys that `LOOK_DEFAULTS` didn't list were dropped from `config.yaml` on the next start (`CreditsEngine.configure`); every non-engine `credits:` key is now kept.
- Admin → Credits **Pause / play** only worked once (the dashboard never learned the new play state).
- Overlay and admin files are served `no-store`, so an update shows up on the next OBS / browser reload.
- **YouTube chat emoji and reactions.** Standard emoji (🍅, 🥖 ...) arrived as their `:shortcut:` names, so emoji reactions never fired from YouTube and the overlay / Stream Rooms showed text like `:baguette_bread:`. They now come through as the emoji character. YouTube's own and channel member emoji (`:face-red-heart-shape:`) keep their `:shortcut:` text and get an `emotes` range with the image (`provider: "youtube"`, same shape as the Twitch ranges), so the chat overlay and Stream Rooms draw them. Reaction `emotes` names match with or without the colons. (`adapters/youtube.py` `runs_to_text_and_emotes`, InnerTube mode; the official API only sends plain text.)
- **Reactions aimed at YouTube chatters** failed with "there's no … here": YouTube names are handles that start with `@` (`@MaloneCara`), and the target check compared them with the `@`. Target names now ignore `@` (`!tomato MaloneCara`, `!tomato @MaloneCara` and `🍅 @MaloneCara` all work), opt-out / opt-in lists ignore it too, and replies no longer say `@@Name`. Tests: `tests/test_youtube_chat.py`.
- Reaction targets typed with spaces now work: `!tomato presenter 2`, `!tomato Podium 2`, `!tomato big piano`. Names match without case, spaces, `_`, `-` or dots, trying the longest run of words first (so trailing chat like "lol" is ignored).
- Saving **Command groups** (or Config) from the admin now really hot-applies group on/off. The save swapped in a fresh config dict but the running Core kept reading the old one until restart; `refresh_command_groups` / credits apply now follow the live config.

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
