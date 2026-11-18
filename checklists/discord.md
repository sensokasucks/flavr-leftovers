# Checklist — Discord bot + video requests

Home: `fridge-stream-core/core/discord_bot.py` (DiscordBot: the streamer's own bot, written on `websockets` + `httpx`, no discord.py), `core/video_requests.py` (VideoRequestQueue, rules, YouTube look-up), `api/video_request_routes.py`, `admin/discord.js` (Setup → Chat & viewers → Discord & video requests + the Live card "Video requests"), `overlay/video-player.html/.css/.js` (the player page), `overlay/video-queue.html/.css/.js` (the queue overlay). Tests: `tests/test_video_requests.py`.

Viewers post YouTube links in one Discord channel; the streamer or approvers say yes / no (dashboard or Discord buttons); approved videos play one after another on the player page (OBS Browser Source, or a browser tab shared onto Stream Rooms' big screen), or, with `play_on: rooms`, are downloaded into Stream Rooms.

## Must keep

- [ ] `discord.enabled` and `video_requests.enabled` default **false**. Core runs fine with no token.
- [ ] The bot token never leaves Core: GET sends `token_set`, a save keeps the old token unless a new one is typed, `token_clear` removes it. Never logged, never in a status text.
- [ ] Settings save merges into the live config (`discord:` and `video_requests:` blocks only, through `read_settings`) then `save_config`. The bot reconnects only when `enabled` or `token` changed (`RECONNECT_KEYS`).
- [ ] Gateway intents GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT (33281). Close codes 4004 / 4013 / 4014 stop reconnecting and show a plain-words reason; others reconnect with a back-off.
- [ ] Every message the bot posts sends `allowed_mentions: {parse: []}` (a video title can't ping @everyone).
- [ ] Only messages in `request_channel_id` count; bots ignored; `requester_role_ids` (empty = everyone). Buttons (`vr:<act>:<id>`) obey `_may_decide`: Administrator, Manage Server, or an `approver_role_ids` role. Anyone else gets a private (flags 64) "not allowed" reply.
- [ ] Nothing plays without a yes. The streamer's own Add (dashboard) lands approved and skips the per-person, repeat, cooldown, length and blocked-word rules, never the YouTube checks (live, age-restricted, not embeddable in player mode).
- [ ] YouTube look-up needs no API key (oEmbed + watch page). A failed look-up refuses the link with a reason; it never crashes the bot.
- [ ] Queue saved in `data/video_requests.json` (git-ignored with `data/`); a "playing" item at start goes back to approved. History trimmed.
- [ ] Player routes (`/api/video-requests/player*`) need no token (overlay on this PC, Core listens on 127.0.0.1). Admin routes need X-Admin-Token.
- [ ] Auto-play (`auto_play`, off by default) starts the next approved video when one ends or fails, after `gap_seconds` (default 10, 0 = at once). During that pause nothing plays; the Live card shows the countdown with **Start now** and **Hold** (`POST .../hold`: the countdown stops, auto-play stays on, the queue waits for Play next). Skip and Play now never wait. The first video of a run is started by hand. Any `play()` ends a running pause, and a stale pause task must never start a second video.
- [ ] "Up next" (`show_next`): the player page shows the card during the pause (with seconds left) and in the corner for the last `next_seconds` of a video; `?next=0` hides it. The queue overlay `/overlay/video-queue.html` (`.css/.js`; Now playing + up to 5 next, `?count=`, `?now=0`, `?thumbs=0`, `?align=right`) reads the same `GET /api/video-requests/player` and never sends anything.
- [ ] The player page never waits: it follows `seq`, reports `ended` / `error` (YouTube error codes → plain words in History), shows "Click to start" in a plain browser tab until the browser lets it play with sound. It has **no** overlay-hint.js (the tab is shared on stream).
- [ ] `play_on: rooms`: Core asks Stream Rooms through `send_stage` and follows its `rooms_state` `video` block (`now`, `ended_n`, `job`); the next approved video is prepared ahead (`video_prep`).
- [ ] Dashboard: one Setup entry (Bot / Channels / Request rules / Player / Companion bot tabs, cards never fold); the Live card shows only while video requests are on. The Companion bot tab is run by `admin/companion.js` with its own Save (the page's Save row hides on that tab); its rules are in [stream-state.md](stream-state.md).

## After-change verify

- [ ] `python -m pytest tests/test_video_requests.py -q`
- [ ] With a real bot: post a link in the request channel → Approve on the Live card → it plays on the player page; Deny with a reason → the bot answers in the channel; a button press by someone without the role is refused privately.
- [ ] Player page in a normal browser tab: Click to start, then Skip / Pause from the Live card.
