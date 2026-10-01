# Checklist — Admin hub

Home: `fridge-stream-core/admin/` (`index.html`, `admin.js`, `admin.css`) + `api/admin_routes.py`. URL: `http://127.0.0.1:3850/admin/`.

## Must keep

Tabs, in order:

- [ ] **Status** — adapters, games, credits on/off + unique count, points on/off
- [ ] **Sources & overlays** — copyable Webpage URLs + descriptions, including sibling Fridge apps
- [ ] **Integrations** — command tester (dry-run / live), per-game sub-panels, health recheck, metrics test, overlay preview
- [ ] **Market** — tape + per-game vault/dynamo knobs (see [market.md](market.md))
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
- [ ] `GET/PUT /api/admin/command-groups` + `POST .../reload`
- [ ] `GET /api/admin/credits` including `cast` + the Credits write routes
- [ ] Market admin routes used by the Market tab
- [ ] `GET/PUT /api/admin/reactions` + `POST /api/admin/reactions/test` (see [reactions.md](reactions.md))

Auth:

- [ ] `_auth` never accepts `change-me` / empty. Fallback token lives in `data/admin_token.txt` and is printed at startup.

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
- [ ] Status still mentions each enabled game slot: Minecraft, Factorio, Granvir, OpenTTD.
- [ ] Sources list still includes chat, stats overlay, alerts, credits, market, OpenTTD, plus sibling ports 3847 / 3851 / 3854 / 3855.

## Navigation (2026-09 rebuild)

- [ ] Landing page is **Live controls** (status chips, credits roll buttons, test alerts, dry-run command). Live buttons use `data-proxy="<id>"` to press the feature page's real button — don't duplicate handlers.
- [ ] Flat sidebar, no collapsible groups. Settings sub-pages are sidebar items (`data-tab="config" data-sub="…"`); the config pill bar is hidden.
- [ ] Pages with `.acc-stack[data-acc]` show one sub-page at a time (`showSub`); `data-aside` sections (Credits / Alerts preview) stay visible beside every sub-page.
- [ ] Save config.yaml bar shows only on the yaml sub-pages (core, games, points, advanced); Reactions / groups / commands keep their own save buttons.
- [ ] Routes are `#page/sub`; Back works; last page + last sub per page remembered in localStorage.
- [ ] Search (`/`) indexes nav items (+ `data-keywords`), sub-page pills, labels, legends and credits editor chips; a new setting with a `<label>` is searchable with no extra work.
- [ ] Element ids used by admin.js are unchanged by layout work — move markup, don't rename ids.
