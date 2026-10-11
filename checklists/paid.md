# Checklist — Paid list

Home: `core/paid.py` (`PaidLog`, table `paid_events` in `data/stream_core.db`). Admin: On stream → Paid (`admin/index.html` `#tab-paid`, `admin.js` "Paid tab"). API: `/api/admin/paid*` in `api/admin_routes.py`. Tests: `tests/test_paid.py`.

## Must keep

- [ ] Every paid chat line goes on the list from `StreamCore._note_paid_chat`: `ChatEvent.paid_kind` superchat / supersticker / jewels (YouTube), bits / powerup (Twitch; power-ups are `highlight` gigantified / animated, no bits count in IRC), kicks (Kick). Platform alerts in `core.paid.ALERT_KINDS` (subscribe / resub / gift / kicks / donation / member / member_milestone / member_gift / powerup / celebration / charity / hypetrain) go on it from `StreamCore._on_alert` when `source:"platform"`. Paid chat's own alert has `source:"chat"` and is never listed twice.
- [ ] A power-up is listed once: from EventSub with its bits while `adapters.twitch_eventsub.bits_live()`, else from its IRC chat line without bits. Platform alerts carrying `event_id` use it as the row's message id (no doubles on a resend). Amounts are kept for `PRICED_ALERT_KINDS` only.
- [ ] Alert tests, the overlay showcase and anything without `source:"platform"` never land on the list.
- [ ] Red-flagged chatters' paid messages and alerts **are** listed (`flagged`), and still never shown on an overlay.
- [ ] The list is kept whether or not `chat_log.enabled` is on. Nothing is deleted except by **Delete ticked rows older than…** (`POST /paid/delete-ticked`), which never touches unticked rows.
- [ ] Same platform message id is listed once (unique index on `platform, message_id`), so reconnects don't double rows.
- [ ] Filters (`PaidLog._where`): status open / done / all, since / until (or `when=stream` = latest `streams.started`, else midnight), platforms, group money / subs, kinds, min (in each row's own unit), has_message, q, sort oldest / newest / biggest. Default view: money group, unticked, oldest first.
- [ ] The menu badge counts unticked **money** rows only (`/paid/count`).
- [ ] CSV export goes through `SafeWriter`.
- [ ] Tests never write the real `data/stream_core.db`: `PaidLog` follows `StreamCore.store` (tests swap in a temporary Store) and creates its table on first use.

## Drop risks

- Listing paid chat twice (once from chat, once from its alert).
- Dropping a flagged chatter's money silently.
- A second database file for the list.

## After-change verify

- [ ] On stream → Paid renders, ticks stick after a reload, and the badge changes.
- [ ] `python -m pytest tests/test_paid.py`.
