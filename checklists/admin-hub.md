# Checklist — Admin hub

Home: `fridge-stream-core/admin/` (`index.html`, `admin.js`, `admin.css`) + `api/admin_routes.py`. URL: `http://127.0.0.1:3850/admin/`.

## Must keep

Tabs, in order:

- [ ] **Status** — adapters, games, credits on/off + unique count, points on/off
- [ ] **Sources & overlays** — copyable Webpage URLs + descriptions, including sibling Fridge apps
- [ ] **Integrations** — command tester (dry-run / live), per-game sub-panels, health recheck, metrics test, overlay preview
- [ ] **Market** — tape + per-game vault/dynamo knobs (see [market.md](market.md)); one sub-page per game plugin with `market` fields, drawn from its `plugin.json`
- [ ] **Settings → Game plugins** — one card per installed plugin from its `plugin.json` `settings` (enabled tick, status, links, errors); empty state when `plugins/` is empty (see [plugins.md](plugins.md))
- [ ] **Credits** — enable, roll/loop/once/hold/once-then-clear, pause, restart, CSV download, live list over `/ws`, style editor, pins, preview (see [credits-core.md](credits-core.md))
- [ ] **Alert test** — fire kinds + skin + custom CSS (see [alerts.md](alerts.md))
- [ ] **Users & Points** — search, adjust, link identities, CSV
- [ ] **Chat History** — only fills when `chat_log.enabled`
- [ ] **Config** — hybrid editor for `config.yaml` + `commands.json`; advanced fields accordion; **Reactions** editor; command group table; overlay module checkboxes

APIs that the tabs depend on must not disappear:

- [ ] `GET /api/admin/integrations`
- [ ] `POST /api/admin/commands/test`
- [ ] `POST /api/admin/games/{id}/metrics-test`
- [ ] `GET /api/admin/games/{id}/health`
- [ ] `GET /api/admin/plugins`, `PUT /api/admin/plugins/{id}/settings` (manifest fields only, merged), `PUT /api/admin/market/settings`
- [ ] `GET/PUT /api/admin/command-groups` + `POST .../reload`
- [ ] `GET /api/admin/credits` including `cast` + the Credits write routes
- [ ] Market admin routes used by the Market tab
- [ ] `GET/PUT /api/admin/reactions` + `POST /api/admin/reactions/test` (see [reactions.md](reactions.md))

Auth:

- [ ] `_auth` never accepts `change-me` / empty. Fallback token lives in `data/admin_token.txt` and is printed at startup.
- [ ] `api()` unwraps FastAPI `detail` (`readableError`); a 401 calls `needToken()` (token box shown + highlighted + focused, message says where the token lives). Saving Config with a new `points.admin_token` updates the browser's stored token (`cfg-save`).

Save rules:

- [ ] Config save writes the same files the wizard / humans edit (`config.yaml`, `commands.json`).
- [ ] Save merges unknown keys. It does not drop `command_groups`, `*.market`, `credits`, `overlay.modules`, `reactions`, or game blocks. The full Config save keeps the live `reactions` block.
- [ ] Credits enable is hot-applied. Platform adapter settings hot-apply (only changed platforms reconnect); game toggles and port still need a restart — the UI must not claim otherwise.
- [ ] Groups + commands can hot-reload without a full process restart.

## Drop risks

- New tab added in HTML but not wired in `admin.js`.
- Feature shipped in a game file with no Integrations / Status row.
- Credits / Market UI that 404s because routes were not added (already happened in 0.13.1).

## After-change verify

- [ ] Every tab button in `index.html` has a matching panel and loader in `admin.js`.
- [ ] Status still lists each installed game plugin (Minecraft, Factorio, Granvir, OpenTTD when installed) with running / config / error.
- [ ] Sources list still includes chat, stats overlay, alerts, credits, market, OpenTTD, plus sibling ports 3847 / 3851 / 3854 / 3855.

## Navigation (2026-09 rebuild)

- [ ] Landing page is **Live controls** (status chips, credits roll buttons, test alerts, dry-run command). Live buttons use `data-proxy="<id>"` to press the feature page's real button — don't duplicate handlers.
- [ ] Flat sidebar, no collapsible groups. Settings sub-pages are sidebar items (`data-tab="config" data-sub="…"`); the config pill bar is hidden.
- [ ] Pages with `.acc-stack[data-acc]` show one sub-page at a time (`showSub`); `data-aside` sections (Credits / Alerts preview) stay visible beside every sub-page.
- [ ] Save config.yaml bar shows only on the yaml sub-pages (core, games, points, advanced); Reactions / groups / commands keep their own save buttons — and those stay **visible** (hide `.config-savebar` there, never every `.config-actions`).
- [ ] Every page with settings has the **page save bar** (`.page-savebar`, admin.js "Page save bar"): Chat games, Credits, Alerts, Market, and Config → Reactions / Command groups / Chat commands. A new block of settings is added to its `sections` list (scope or fields + its own Save button or save function), or with `PAGE_SAVER.add(...)` when it is drawn later (game plugins' Market sub-pages) — otherwise its edits are never flagged or saved by the bar / Ctrl+S.
- [ ] Unsaved edits: orange dot on the sidebar item and sub-page pill; leaving that page (sidebar, Back) asks first; closing the tab asks (`beforeunload`). Action / test fields are not sections.
- [ ] Each block's own Save button keeps working; the bar clicks it (or calls its save function), and only clears a block when a write call succeeded (`apiWrites` / `apiFails` counters in `api()`).
- [ ] Routes are `#page/sub`; Back works; last page + last sub per page remembered in localStorage.
- [ ] Search (`/`) indexes nav items (+ `data-keywords`), sub-page pills, labels, legends and credits editor chips; a new setting with a `<label>` is searchable with no extra work.
- [ ] Element ids used by admin.js are unchanged by layout work — move markup, don't rename ids.

## Accessibility (2026-10)

- [ ] `:focus-visible` outline on every control; `html.hc` high-contrast theme (header `#hc-toggle`, `prefers-contrast: more`, remembered in localStorage).
- [ ] Form-only deletes / resets (reaction, command, group, Reset form to defaults) use `undoToast()` (role=status, Ctrl+Z) — not `confirm()`. Anything that writes or acts immediately keeps its `confirm()`.
- [ ] Under 900 px: sidebar is a drawer behind `#nav-toggle` (label = current page); no page scrolls sideways (tables scroll inside their card).
