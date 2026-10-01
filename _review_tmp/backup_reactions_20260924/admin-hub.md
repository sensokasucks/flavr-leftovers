# Checklist — Admin hub

Home: `fridge-stream-core/admin/` (`index.html`, `admin.js`, `admin.css`) + `api/admin_routes.py`. URL: `http://127.0.0.1:3850/admin/`.

## Must keep

Tabs, in order:

- [ ] **Status** — adapters, games, credits on/off + unique count, points on/off
- [ ] **Sources & overlays** — copyable Webpage URLs + descriptions, including sibling Fridge apps
- [ ] **Integrations** — command tester (dry-run / live), per-game sub-panels, health recheck, metrics test, overlay preview
- [ ] **Market** — tape + per-game vault/dynamo knobs (see [market.md](market.md))
- [ ] **Credits** — enable, roll/loop/once/hold, style editor, pins, preview (see [credits-core.md](credits-core.md))
- [ ] **Alert test** — fire kinds + skin + custom CSS (see [alerts.md](alerts.md))
- [ ] **Users & Points** — search, adjust, link identities, CSV
- [ ] **Chat History** — only fills when `chat_log.enabled`
- [ ] **Config** — hybrid editor for `config.yaml` + `commands.json`; advanced fields accordion; command group table; overlay module checkboxes

APIs that the tabs depend on must not disappear:

- [ ] `GET /api/admin/integrations`
- [ ] `POST /api/admin/commands/test`
- [ ] `POST /api/admin/games/{id}/metrics-test`
- [ ] `GET /api/admin/games/{id}/health`
- [ ] `GET/PUT /api/admin/command-groups` + `POST .../reload`
- [ ] `GET /api/admin/credits` including `cast` + the Credits write routes
- [ ] Market admin routes used by the Market tab

Auth:

- [ ] `_auth` never accepts `change-me` / empty. Fallback token lives in `data/admin_token.txt` and is printed at startup.

Save rules:

- [ ] Config save writes the same files the wizard / humans edit (`config.yaml`, `commands.json`).
- [ ] Save merges unknown keys. It does not drop `command_groups`, `*.market`, `credits`, `overlay.modules`, or game blocks.
- [ ] Credits enable is hot-applied. Platform adapter toggles still need a restart — the UI must not claim otherwise.
- [ ] Groups + commands can hot-reload without a full process restart.

## Drop risks

- New tab added in HTML but not wired in `admin.js`.
- Feature shipped in a game file with no Integrations / Status row.
- Credits / Market UI that 404s because routes were not added (already happened in 0.13.1).

## After-change verify

- [ ] Every tab button in `index.html` has a matching panel and loader in `admin.js`.
- [ ] Status still mentions each enabled game slot: Minecraft, Factorio, Granvir, OpenTTD.
- [ ] Sources list still includes chat, stats overlay, alerts, credits, market, OpenTTD, plus sibling ports 3847 / 3851 / 3854 / 3855.
