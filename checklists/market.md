# Checklist — Fridge Market

Home: `core/market.py`. Spec: `fridge-stream-core/docs/MARKET.md`. Admin tab **Market**.

## Must keep

- [ ] Opt-in: `market.enabled` default **false**. Command group `market` binds to that flag.
- [ ] One Core ledger. Games emit signals / flushes; they do not keep a second share book.
- [ ] Not OpenTTD Chat Fund. `!invest` stays a one-way cash injection on group `openttd`. Market tokens stay distinct (`!buy`, `!sell`, `!tickers`, `!ticker`, `!portfolio` when those ship).
- [ ] Public API: `GET /api/market/state`, `GET /api/market/history`, `POST /api/market/signal`, `POST /api/market/dividend`.
- [ ] Holdings table `market_holdings`. Dividends go through `store.pay_dividend` (dust burned if nobody is invested).
- [ ] Preview tape ticks seed listings even while `enabled` is false so overlays can be designed.
- [ ] Overlays: `/overlay/market.html`, `/overlay/market-board.html`, `/overlay/market-chart.html`, plus per-game tapes (`market-minecraft.html`, `market-factorio.html`, `market-openttd.html`, dynamo helper pages).
- [ ] Per-trigger cooldowns: `cooldown_sec` + `cooldown_scope` (`symbol` / `book` / `global`). Death dip must not be spawn-campable when cooldown > 0.
- [ ] Steam CCU via `GetNumberOfCurrentPlayers` only — **no steamcharts scrape**. Interval: `market.steam_poll_sec` (default 1800).
- [ ] Chat-member tickers (`feed: chatter`): base price from channel points, optional live link, consecutive-stream bonus (`chatter_points_scale`, `chatter_streak_bonus`).
- [ ] Admin → Market can edit ticker CRUD / personalities, grant shares, test payout, and per-game dynamo / vault / chest knobs.
- [ ] Config tab save **must not wipe** `minecraft.market.*`, `factorio.market.*`, or `market.*`.
- [ ] Default Minecraft ticker is `MINECRAF` only. Default Factorio ticker is `FACTORIO` only. Do not silently resurrect `STEVE` / `FRG` / `PWR` / `FACT` as defaults unless the checklist and example config are updated together.
- [ ] Chat Dynamo / Chat Kinetic use the same power level × stock factor (clamped). No extra RPM→FE conversion layer.

## Minecraft hook

- [ ] Chat Dynamo RF = stream power × average `price/base` of `minecraft.market.dynamo_symbols`, clamped `dynamo_min_factor`–`dynamo_max_factor`.
- [ ] Dividend Vault (`fridge_minecraft:dividend_vault`) eats TRE / RF and pays `vault_symbol`.
- [ ] Dividend Chest (`fridge_minecraft:dividend_chest`) is a 54-slot hopper chest, accepts any item, item value table in Admin → Market (default + furnace XP fallback).
- [ ] Core polls server mod `GET /api/market` and pays pro-rata.

## Factorio hook

- [ ] Chat Dynamo output = `power_level × (ticker price / base)` clamped 0.25–3× on `factorio.market.dynamo_symbols`.
- [ ] Power Vault / Item Vault flush to `POST /api/market/dividend`. Flush thresholds (MJ / items) editable and hot-saved; next metrics pulse pushes them to the :3847 bridge.
- [ ] Power work pays `vault_symbol` holders; item counts pay `chest_symbol` holders.

## Drop risks

- Config GUI omitting nested `*.market` blocks.
- Reintroducing vanilla OpenTTD 25% share slots as “the market”.
- Scraping steamcharts after the desk spec banned it.
- Changing default ticker symbols in code but not example YAML (or the reverse).

## After-change verify

- [ ] `docs/MARKET.md` still describes the APIs you actually expose.
- [ ] Admin → Market still shows dynamo symbols / clamp / vault + chest rates / grant / test payout.
- [ ] Example config `minecraft.market` / `factorio.market` / `market.*` keys still parse in `core/config.py`.
