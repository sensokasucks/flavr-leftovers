# Checklist — Admin hub

Home: `fridge-stream-core/admin/` (`index.html`, `admin.js`, `admin.css`) + `api/admin_routes.py`. URL: `http://127.0.0.1:3850/admin/`.

## Must keep

Tabs, in order:

- [ ] **Status** — adapters, games, credits on/off + unique count, points on/off
- [ ] **Paid** (On stream, `#paid`) — paid messages, tips and subs with tick boxes, filters remembered in `localStorage`, badge in the menu (`data-title="Paid"` keeps the page title clean); see [paid.md](paid.md)
- [ ] **Sources & overlays** — copyable Webpage URLs + descriptions, including sibling Fridge apps
- [ ] **Integrations** — command tester (dry-run / live), per-game sub-panels, health recheck, metrics test, overlay preview
- [ ] **Plugin pages** — a running plugin's `pages` get menu entries (Gamer Stonks is one: tape, listings, per-game vault/dynamo knobs from each plugin's `market` block); old `#market` links open `#plg-stonks-main` (see [market.md](market.md))
- [ ] **Settings → Plugins** — one card per installed plugin from its `plugin.json` `settings` (enabled tick, status, links, errors); empty state when `plugins/` is empty (see [plugins.md](plugins.md))
- [ ] **Stored files** (Overlays, `#files`) — every uploaded picture / video / sound / font once; Upload (several at a time), Copy CSS, Rename, Replace…, Delete (asks, names the places it empties), "Used by" per file (see [stored-files.md](stored-files.md))
- [ ] **Chat widgets** (Overlays, `#widgets`) — import a StreamElements / Streamlabs widget zip or pasted code, Copy OBS address, Settings & preview (one control per field, the widget's buttons), code editor, Rename, Delete (see [widgets.md](widgets.md))
- [ ] **Audience looks** (Overlays, `#looks`) — Stream Rooms' bubbles, silhouettes (built-in or stored pictures) and looks per group with a random mix; preview; saves on its own (see [audience-looks.md](audience-looks.md))
- [ ] **Phone remote** (Setup › Core, `#phone`) — on/off tick (starts / stops the 3860 door at once), address the phone opens, Windows network-type warning, Turn off when Core closes, Advanced address override, paired phones with Remove, Add a phone (QR + 6-digit code, countdown, Cancel; polls every 2 s while open). Only `/api/admin/phone-remote*` (`api/phone_admin_routes.py`). See [phone-remote.md](phone-remote.md).
- [ ] **Log files for troubleshooting** (Setup › Core › Advanced, card `#cfg-logs-card`) — tick saves `core.log_files` (default on, takes effect on restart); Core's and Stream Rooms' files newest first with Download; Open log folder per app. Only `/api/admin/logs*` (`api/log_routes.py`); files are written already cleaned by `core/debug_log.py` (IPs tagged, user / PC names, folders, config secrets hidden). Only names matching `NAME_RE` are served.
- [ ] **Credits** — enable, roll/loop/once/hold/once-then-clear, pause, restart, CSV download, live list over `/ws`, style editor, pins, preview (see [credits-core.md](credits-core.md))
- [ ] **Alert test** — fire kinds + skin + custom CSS (see [alerts.md](alerts.md))
- [ ] **Users & Points** — search, adjust, link another platform account **by name** (`POST /users/{id}/link` with `username` and no `platform_user_id`: the known account by that name, else a `name:` placeholder their first chat line claims), merge by name search (confirm names both people and their points), per-person Chat log / Download CSV / Red-flag
- [ ] **Chat History** — only fills when `chat_log.enabled`; shows the newest 200 and says so; names open the person; Download CSV follows the platform / search / 🚩 filters (`GET /chat/export?platform=&q=&flagged=`)
- [ ] **Red flags** (People) — its own page (`#redflags`), not a card on Chat history; Unflag offers Undo (`DELETE /red-flags/{id}` returns `removed`, `POST /red-flags/restore` puts it back). **Custom flags** card on the same page saves through `PUT /red-flags` (`custom`); its own Unflag + Undo (`DELETE /red-flags/custom/{id}`, `POST /red-flags/custom/restore`)
- [ ] **Config** — hybrid editor for `config.yaml` + `commands.json`; advanced fields accordion; **Reactions** editor; command group table; overlay module checkboxes
- [ ] One name per page: menu entry, set tabs, page title and in-app links use the same words ("Paid & thank-yous", "Overlay links for OBS", "Connect platforms"). No banner or hint points at a "Config" menu. Live controls is the landing page (`tab-live` is the `active` panel in the HTML).
- [ ] Credits on/off has one switch, on the Credits page (`PUT /credits/enabled`); a config save keeps the live `credits.enabled`. While off, the Credits page and Live controls show a red "Credits are off" line with **Turn on**, and the play state never says "Looping". Live controls and Credits page buttons share labels.
- [ ] Sources & overlays: Customise remembers its switches and open panels in `sessionStorage` (per browser tab); Copy shows "Copied ✓" on the button.
- [ ] Sub-page pills are a `role=tablist` (arrow keys move). Status cards are `<section>` with a heading, not `<legend>` outside a fieldset. **Start a new stream now** asks first.

APIs that the tabs depend on must not disappear:

- [ ] `GET /api/admin/integrations`
- [ ] `POST /api/admin/commands/test`
- [ ] `POST /api/admin/games/{id}/metrics-test`
- [ ] `GET /api/admin/games/{id}/health`
- [ ] `GET /api/admin/plugins`, `PUT /api/admin/plugins/{id}/settings` (manifest fields only, merged; `market` fields apply live)
- [ ] `GET/PUT /api/admin/command-groups` + `POST .../reload`
- [ ] `GET /api/admin/credits` including `cast` + the Credits write routes
- [ ] `/plugin-pages/<id>/...` serves only the plugin's `pages/` folder
- [ ] `GET/PUT /api/admin/reactions` + `POST /api/admin/reactions/test` (see [reactions.md](reactions.md))
- [ ] `GET/POST /api/admin/widgets`, `GET/PUT/DELETE /api/admin/widgets/{name}`, `POST /api/admin/widgets/{name}/button` (see [widgets.md](widgets.md))
- [ ] `GET/POST /api/admin/media`, `PUT/DELETE /api/admin/media/{name}`; `POST /api/admin/overlays/{alerts|chat}/assets/{slot}` takes `{file, kind}` or `{data, filename}` (see [stored-files.md](stored-files.md))

Auth:

- [ ] `_auth` never accepts `change-me` / empty. Fallback token lives in `data/admin_token.txt`. The console never prints the whole token (address + first 4 characters); Core writes `data/Open dashboard.url` (`/admin/#token=…`, the page stores it and strips it from the address bar), `core.open_dashboard` opens it at start.
- [ ] Easier sign-in (`core/dashboard_signin.py`, tests `tests/test_dashboard_signin.py`): Core also writes `Open Stream Core dashboard.url` beside `START Stream Core.bat` when Core sits in the workshop folder (git-ignored at the repo root: it holds the token). It opens the signed-in dashboard at start when `core.open_dashboard` is on **or** `data/dashboard_signed_in` is missing (written by `_auth` on the first good token), so the first start after the wizard lands signed in. The .bat texts, the wizard's "Next steps" and `needToken()` point at that shortcut and the button below, not at the bare `/admin/` address.
- [ ] "Sign in on this PC" (`#sign-in-here`, `signInHere()` → `POST /api/admin/sign-in-here`, no token needed) returns the token only when the connection is loopback, `Origin` is present and equals `http://<Host>` exactly (so a sibling app on another loopback port, which CORS otherwise trusts, can't read it), and `Sec-Fetch-Site` (when sent) is `same-origin`. Never add it to the phone door's `ALLOWED`. Settings › Points "Copy sign-in link" copies `/admin/#token=…` for another browser on this PC (OBS dock).
- [ ] A config save with an empty / placeholder `points.admin_token` keeps the live token (`keep_admin_token`); "Reset form to defaults" leaves the token box alone. Tests: `tests/test_admin_token.py`.
- [ ] `api()` unwraps FastAPI `detail` (`readableError`); a 401 calls `needToken()` (token box shown + highlighted + focused, message says where the token lives). Saving Config with a new `points.admin_token` updates the browser's stored token (`cfg-save`).

Save rules:

- [ ] Config save writes the same files the wizard / humans edit (`config.yaml`, `commands.json`).
- [ ] Save merges unknown keys. It does not drop `command_groups`, `*.market` (plugins' market fields stay as the Gamer Stonks page saved them), `credits`, `overlay.modules`, `reactions`, or game blocks. The full Config save keeps the live `reactions` block.
- [ ] Credits enable is hot-applied. Platform adapter settings hot-apply (only changed platforms reconnect); game toggles and port still need a restart — the UI must not claim otherwise.
- [ ] Groups + commands can hot-reload without a full process restart.

## Drop risks

- New tab added in HTML but not wired in `admin.js`.
- Feature shipped in a game file with no Integrations / Status row.
- Credits / Market UI that 404s because routes were not added (already happened in 0.13.1).

## After-change verify

- [ ] Every tab button in `index.html` has a matching panel and loader in `admin.js`.
- [ ] Status still lists each installed game plugin (Minecraft, Factorio, Granvir, OpenTTD when installed) with running / config / error.
- [ ] Sources list still includes chat, stats overlay, alerts, credits, OpenTTD, installed plugins' overlays (Gamer Stonks' market pages), plus sibling ports 3847 / 3851 / 3854 / 3855.

## Navigation (2026-09 rebuild)

- [ ] Landing page is **Live controls** (status chips, credits roll buttons, test alerts, dry-run command). Live buttons use `data-proxy="<id>"` to press the feature page's real button — don't duplicate handlers.
- [ ] Live / Setup menu (see "Menu layout" below). Settings sub-pages are menu items (`data-tab="config" data-sub="…"`) or tabs of a page set; panels with `data-menu-subs` (config, integrations) hide their own pill bar.
- [ ] Pages with `.acc-stack[data-acc]` show one sub-page at a time (`showSub`); `data-aside` sections (Credits / Alerts preview) stay visible beside every sub-page.
- [ ] Save config.yaml bar shows only on the yaml sub-pages (core, games, points, advanced); Reactions / groups / commands keep their own save buttons — and those stay **visible** (hide `.config-savebar` there, never every `.config-actions`).
- [ ] Every page with settings has the **page save bar** (`.page-savebar`, admin.js "Page save bar"): Chat games, Credits, Alerts, and Config → Reactions / Command groups / Chat commands. A new block of settings is added to its `sections` list (scope or fields + its own Save button or save function), or with `PAGE_SAVER.add(...)` when it is drawn later (game plugins' Market sub-pages) — otherwise its edits are never flagged or saved by the bar / Ctrl+S.
- [ ] Unsaved edits: orange dot on the sidebar item and sub-page pill; leaving that page (sidebar, Back) asks first; closing the tab asks (`beforeunload`). Action / test fields are not sections.
- [ ] Each block's own Save button keeps working; the bar clicks it (or calls its save function), and only clears a block when a write call succeeded (`apiWrites` / `apiFails` counters in `api()`).
- [ ] Routes are `#page/sub`; Back works; last page + last sub per page remembered in localStorage.
- [ ] Search (`/`) indexes nav items (+ `data-keywords`), sub-page pills, labels, legends and credits editor chips; a new setting with a `<label>` is searchable with no extra work.
- [ ] Element ids used by admin.js are unchanged by layout work — move markup, don't rename ids.

## Feedback and restarts (review batch 4)

- [ ] Status and Live controls show each platform's `platformLine()` ("Connected · last message …" or `last_error` + link to the setting) from `/api/admin/status`. Live controls lists platforms that need a look; with nothing on it shows `firstRunHint()`.
- [ ] Live controls "YouTube live video" card (`#live-yt-card`, shown while YouTube is on) → `POST /api/admin/platforms/youtube/video`, any YouTube link. Pasted links are cleaned in the UI (`cleanYouTube` / `cleanKick` / `cleanTwitch`), on save (`clean_platform_fields`) and in the adapters (`core/platform_links.py`). Tests: `tests/test_status_feedback.py`.
- [ ] Saves return `restart_needed` (from `core/restart.py`, compared with `state.boot_config`) and only mention a restart then; `#restart-banner` with **Restart Core now** while the list isn't empty. `POST /api/admin/restart`: exit code 75 under the START .bat loop (`STREAM_CORE_SUPERVISED=1`), re-exec on Linux/macOS, else 409 with what to do. Port change asks first.
- [ ] User page buttons (points, link, merge, notes), credits play buttons and CSV downloads (`downloadFile`) never fail silently: result or plain error next to the button.
- [ ] "Reload from disk" buttons (`RELOAD_BUTTONS`) confirm when their section is dirty (capture-phase click guard).

## Accessibility (2026-10)

- [ ] `:focus-visible` outline on every control; `html.hc` high-contrast theme (header `#hc-toggle`, `prefers-contrast: more`, remembered in localStorage).
- [ ] Form-only deletes / resets (reaction, command, group, Reset form to defaults) use `undoToast()` (role=status, Ctrl+Z) — not `confirm()`. Anything that writes or acts immediately keeps its `confirm()`.
- [ ] Under 900 px: sidebar is a drawer behind `#nav-toggle` (label = current page); no page scrolls sideways (tables scroll inside their card).

## Menu layout (2026-11, Live / Setup)

The rules Sen set for keeping the menu tidy (also in the project instructions). Check every new page or plugin page against them.

- [ ] **Two modes.** The switch at the top of the sidebar (`.nav-mode`, remembered in `localStorage` `stream_core_admin_mode`) shows the **Live** groups (things touched mid-stream: Live controls, Paid & thank-yous, Chat games, Chat & flags, Viewers, Games) or the **Setup** groups (set-once things: Stream look, Stream Rooms, Chat & viewers, Games, Core). Each `.nav-group` has `data-mode` and `data-heading`. Opening a page from search, a link or Back flips the switch to that page's mode (`markNav`).
- [ ] **One home per feature.** No two menu entries open the same thing. Live controls cards are shortcuts that link to (or press, `data-proxy`) the real page; they don't copy its settings.
- [ ] **Related pages are tabs, not entries.** One menu entry with `data-set="<name>"` covers several pages; `PAGE_SETS` in admin.js lists them as `[page, sub or null, tab label]` and `renderSetTabs` draws `.set-tabs` under the title. Today: thanks (Paid + Credits checklist), chatflags (Chat history + Red flags), links (Overlay links + More overlays), chatbox (Chat overlay + Chat widgets), cmds (Chat commands, Reactions, Command groups, Try a command), connect (Platforms + Connection check / Status).
- [ ] **One entry per game.** A game plugin's pages go under Live › Games (`#nav-games-live`, or the group its plugin.json `nav` names; old names Overlays / People / Settings map through `NAV_GROUP_ALIASES`). Turning games on/off is Setup › Games › Add or remove games.
- [ ] **Plain names** that say what the page is for; groups of about 5 entries at most.
- [ ] **Optional cards only when their thing is on.** Live controls: End credits card only while credits are on (`renderCreditsOnOff`), the Stream Rooms card (curtain included) only while Stream Rooms is connected, Pinned only with pins and Stream Rooms connected, YouTube live video only while YouTube is on.
- [ ] **Growing boxes go below the controls** and keep a fixed height (Stream events window `.live-feed`), so new lines never move buttons.
- [ ] **Old links keep working.** Page ids (`#credits`, `#redflags`, `#config/reactions` ...) never change; a page that moves into a plugin goes in `MOVED_TABS`.
- [ ] **Top-bar platform lights** (`#top-lights`, `renderTopLights`) for every switched-on chat platform; clicking one opens Connect platforms › Connection check.
- [ ] **Highlighted message card** (Live controls, `#live-hl-card`): on-screen line, queue with ×, Next / Clear, a Recent chat box with ★ (fixed height `.hl-pick`, polls `/api/admin/highlight/recent` + `/api/admin/highlight` every 2 s while the page is open) and Options (hold seconds, picture). Chat & flags rows have a ★ too (`highlightLine`); red-flagged rows have none. See [highlight.md](highlight.md).
- [ ] **Stream Rooms card** (Live controls, `#live-stage-card`, `admin.js loadRoomsCard`): polls `GET /api/admin/rooms` every 2 s while Live shows; buttons `data-rooms` → `POST /api/admin/rooms` (`ROOMS_ACTIONS` in core/reactions.py, stream-rooms `core/rooms_remote.gd` runs them), curtain stays `data-stage`. Tests: `tests/test_rooms_card.py`.
- [ ] **Stream Rooms settings** (Setup › Stream Rooms, `#rooms/<sub>`, `admin/rooms-setup.js`, page set `roomset`): drawn from the game's own `rooms_settings` list, never a hand-made copy; Basics / More, Find, Changed only, changed dot + Reset, Pin; Start here card on Room & sound. The co-stream password / address never leave the game.
- [ ] **Arrange, Pinned, Scenes, help, Ctrl+K** (`admin/live-extras.js`): layout per device (PC / phone) in `data/dashboard_prefs.json` (`core/dashboard_prefs.py`, merged, capped); Stream events starts last and wide but moves like any card; a card hidden because it doesn't apply uses `hidden`, Arrange's own hiding uses `.live-user-hidden`. Scenes run in Core (`POST /api/admin/rooms/scene`). "?" on every page title opens the manual section (`HELP_MAP`, `GET /api/admin/help`).
- [ ] **Stream events window** (Live controls, `#live-feed-card`): polls `GET /api/admin/activity?after=<id>` every 3 s while the page is open (core/activity.py). Kinds alert / redeem / command / game / flag / error match the filter buttons; plugins add lines with `ctx.activity(text)`. Pause / Clear only affect the window. Tests: `tests/test_activity.py`.
- [ ] **Folding cards** (`admin/fold-cards.js`, admin.css "Folding cards"): every `.cfg-card` with a `<legend>` (or `h3.card-legend`) folds to its title + a summary line ("On/Off · N settings", "N buttons", or its first help text). Setup pages start folded, Live pages start open (`AdminNav.modeOf` in admin.js, `LIVE_STARTS_OPEN`); open/folded is remembered per card in `localStorage` `stream_core_open_cards`. Skipped: a page part (`.acc` sub-page or panel) with one card, cards inside cards, `data-fold="no"`; `data-fold="open"` starts open. Plain `.acc-body` stacks become `.fc-grid`; open cards with 9+ settings span the row. Folded bodies are `hidden="until-found"` (Ctrl+F still finds them); search hits call `FoldCards.reveal`. Element ids inside cards never change. Stream Rooms settings cards use the same markup and click handling.
- [ ] To do (not built yet): an overlay whose source is off (e.g. Gamer Stonks turned off) goes blank instead of showing old numbers or an error, and its link in Overlay links is greyed out with "off".

