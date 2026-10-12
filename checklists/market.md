# Checklist — Gamer Stonks (the market)

The market left Stream Core in 2026-10: it is the **Gamer Stonks** plugin, `plugins/stonks/` in
[flavr-game-plugins](https://github.com/sensokasucks/flavr-game-plugins). Its own checklist
(tape, vaults, dividends, overlays, commands) lives there: `checklists/stonks.md`.

## What Core still owes it (Must keep)

- [ ] Plugin API 2: `pages`, `ctx.db`, `ctx.plugins` / `ctx.service`, `provides` / `after`, `config_moved_from`, `specials`, command group `aliases`, `ctx.require_admin`, `ctx.require_game`. See [plugins.md](plugins.md).
- [ ] The games-only check (`core/local_guard.py` `game_caller_problem`) stays; Gamer Stonks' `/api/market/signal` and `/api/market/dividend` use it through `ctx.require_game`.
- [ ] `config/commands.json` keeps `!buy`, `!sell`, `!tickers`, `!portfolio` (group `market`, `special: market_*`); Core passes them to Gamer Stonks. Don't rewrite that file just to move them.
- [ ] Points: `ctx.store` keeps `get_or_create_user`, `get_user`, `spend_points`, `adjust_points`, `set_points`, `chatter_streak`.
- [ ] `PUT /api/admin/plugins/{id}/settings` keeps saving `market` fields live, and the full Config save keeps them as saved.
- [ ] Old `#market` dashboard links open the Gamer Stonks page.

## Drop risks

- Putting market code back into Core instead of a plugin hook.
- Dropping Core's old `market_holdings` table or `data/market_tickers.json` by hand before Gamer Stonks has copied them (it does so once, on its first start).
