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
- [ ] CSV export still works for users and for chat history. Every CSV export writes through `core/csv_safe.py` `SafeWriter` (cells starting with `= + - @` get a leading `'`). Tests: `tests/test_csv_safe.py`.
- [ ] Market trades and dividends use this same points ledger (`source=market` / `source=dividend`). Do not add a second cash book.
- [ ] OpenTTD `!invest` debits this ledger. Do not invent a parallel points file.
- [ ] Red flags (`core/red_flags.py`, list in table `red_flagged` in this same DB): a flagged chatter's chat is never broadcast, never in `recent_chat`, gets no reactions / commands / games / points / credits / alerts, but **is** still logged. Flagging sends `chat_user_hidden` once. `red_flags` is owned by its page, People → Red flags (admin config save keeps it). Unflag can be undone (`POST /red-flags/restore`); `POST /red-flags/flag` also takes `platform_user_id` (the person page's Red-flag button). `enabled: false` hides nobody but keeps the list. Mods/streamer skipped by default. **Check past chat** (`POST /red-flags/check-past`) only lists who would be flagged; nobody is flagged until the streamer confirms (`POST /red-flags/apply-past`, source `past`). It skips people already flagged and, with `skip_mods`, Core's own mods/admins, the streamer's channel and anyone seen with a mod badge since start (the log keeps no badges).
- [ ] Red-flag phrases are matched with one combined pattern per line (`RedFlags._any`); the phrase is looked up only on a hit.
- [ ] Chat reactions spend with `Store.spend_points()` (atomic check-and-debit) and refund with `adjust_points`, `source=reaction`.
- [ ] Chat lines reach the database through one writer (`Store.start_writer`, `submit_chat`): a queue, one transaction per batch (0.25 s / up to 500 lines), WAL + `synchronous=NORMAL`, chatter ids cached in memory. The chat read loop never waits for the disk; chat points land a moment after the line. Link / merge take the same write lock and clear the id cache. A full queue (50,000) drops database lines only, never overlay chat. `stop()` writes what is queued. Tests: `tests/test_busy_chat.py`.

## Drop risks

- Config save wiping `points.*`.
- Identity-link UI that only stores one platform.
- Paying dividends by writing `users.points` without a ledger row.

## After-change verify

- [ ] Example config still has `points.enabled: false`, `chat_log.enabled: false` and `chat_log.only_flagged: false`.
- [ ] Admin tabs **Users & Points** and **Chat History** still render.
- [ ] Status hub still shows points on/off.
