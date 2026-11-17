# Checklist — Stream start / end + companion bot link

Home: `fridge-stream-core/core/stream_state.py` (StreamState: is the stream live, since when, on which platforms), `core/companion_link.py` (CompanionLink: Core → companion bot pushes), `api/companion_routes.py` (dashboard routes), `admin/companion.js` (Credits page card **When you go live** + Setup → Discord & video requests → **Companion bot** tab). Wiring in `main.py` (`_stream_changed`, `_companion_heartbeat`, `_companion_snapshot`, `_on_alert`, `_metrics_loop`). Tests: `tests/test_stream_state.py`, `tests/test_twitch_eventsub.py`.

The companion bot itself lives in its own repo ([flavr-bot](https://github.com/sensokasucks/flavr-bot), `docs/CORE_LINK.md` there is the other half of the message list).

## Must keep

- [ ] Adapters only call `bus.report_live(platform, live, source)`; repeats are fine (StreamState ignores an unchanged answer). Sources: Twitch EventSub `stream.online` (type `live` only) / `stream.offline` + one Helix `streams` check after each fresh EventSub connect; Kick `_poll_viewers` `livestream.is_live`; YouTube reaching the live chat = live, the chat loop ending after it was reached = offline. Adapter `stop()` reports nothing (closing Core is not the stream ending).
- [ ] `stream.online` / `stream.offline` need no scope and are subscribed even when `twitch.paid_events` is off (`EventSubClient(paid=False)` skips only the scoped ones). `why_not()` blocks only for no sign-in / wrong account; the paid-scope hint is `paid_hint()`.
- [ ] One stream: first platform live → `started` (new `session` number); last platform offline → `dropped`; any back within `stream.restart_grace_min` (default 15, 0–120) → `resumed` (same session, `restarts` + 1); else `ended`, with `ended_at` = when it dropped.
- [ ] Saved in `data/stream_state.json` (live, started_at, dropped_at, alive_at, session). `tick()` (metrics loop) notes `alive_at` once a minute while live. After a restart `resume_timer()` counts the drop from `alive_at`, so a Core opened the next day ends the old stream instead of resuming it.
- [ ] `credits.auto_session` default **false**: only a `started` event resets the credits; `resumed` / `ended` never do.
- [ ] Every change adds a `stream` line to Stream events (`core/activity.py` KINDS, admin.js `LIVE_FEED_KINDS`, the Stream filter button) and a `stream_state` `/ws` frame.
- [ ] Companion link `companion.enabled` default **false**. Core only sends (`POST {url}/core/push`, `Authorization: Bearer {key}`); it opens no port. The key is never sent to the dashboard (`key_set`), kept on save unless a new one is typed, cleared with `key_clear`.
- [ ] Sending never blocks: `send()` queues (max 200); heartbeat / snapshot replace older unsent ones; stream events and alerts wait while the bot is away. Test alerts and follows are never sent. Snapshots: top 500 points (only while `points.enabled` and `send_points`), the request queue (`send_queue`); every 5 minutes and right after a stream ends.
- [ ] Dashboard: the go-live card lives on the Credits page (Feature + roll), the companion card is a tab of the existing Discord & video requests page. No new menu entry.

## After-change verify

- [ ] `python -m pytest tests/test_stream_state.py tests/test_twitch_eventsub.py -q`
- [ ] Real stream: go live on Twitch with Connect Twitch done → Stream events shows "Stream started (Twitch)"; with the switch on, the Credits list empties once. Stop the stream → "Every platform is offline…", then "Stream ended" after the grace minutes.
- [ ] Companion bot running: Test says "The companion bot answered."; its `/status` shows Core's heartbeat.
