# Checklist — Points / users / chat log

Home: `core/store.py`. DB: `data/stream_core.db`.

## Must keep

- [ ] Points are opt-in (`points.enabled` default **false**).
- [ ] Awards: `per_message` + `cooldown_sec` anti-spam.
- [ ] Live sub / follow / gift alerts (adapter alerts, `source:"platform"`, never Alert-test ones) pay `points.sub_points` (sub + resub), `points.follow_points` (once per viewer, ledger `source=follow`), `points.gift_points` × qty to the gifter. `StreamCore._award_alert_points` → `Store.award_for_alert`; ledger `source` = alert kind. Name-only alerts (Kick) match the platform identity by username, else create a `name:<user>` identity that the viewer's first chat line claims. Hot-applied from Admin → Config.
- [ ] Ledger lives in SQLite with the chat log — not a second database.
- [ ] Admin token (`points.admin_token` / `X-Admin-Token`) still gates `/admin`.
- [ ] Admin → Users & Points: search, adjust points, link cross-platform identities, export CSV.
- [ ] Chat History tab is separate from the live overlay. `chat_log.enabled` default **false**.
- [ ] CSV export still works for users and for chat history.
- [ ] Market trades and dividends use this same points ledger (`source=market` / `source=dividend`). Do not add a second cash book.
- [ ] OpenTTD `!invest` debits this ledger. Do not invent a parallel points file.
- [ ] Chat reactions spend with `Store.spend_points()` (atomic check-and-debit) and refund with `adjust_points`, `source=reaction`.

## Drop risks

- Config save wiping `points.*`.
- Identity-link UI that only stores one platform.
- Paying dividends by writing `users.points` without a ledger row.

## After-change verify

- [ ] Example config still has `points.enabled: false` and `chat_log.enabled: false`.
- [ ] Admin tabs **Users & Points** and **Chat History** still render.
- [ ] Status hub still shows points on/off.
