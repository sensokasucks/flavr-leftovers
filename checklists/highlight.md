# Checklist — Highlighted message

Home: `fridge-stream-core/core/highlights.py` (HighlightBoard), `api/highlight_routes.py`, `overlay/highlight.{html,js,css}`, the Live controls card (`#live-hl-card`, admin.js "Highlighted message"). Credits side: [credits-core.md](credits-core.md) (Featured).

## Must keep

- [ ] One highlight on screen at a time; more wait in a queue (`QUEUE_MAX` 20, oldest waiting dropped). **Next** = current off, next on; **Clear** = screen and queue empty; × removes one waiting.
- [ ] `highlight.hold_sec` (0..600, default 0 = until Next / Clear) is timed by Core (`HighlightBoard.run`), never by the overlay. `show_avatar` default on. `read_aloud` exists in config, default **off**, nothing uses it until TTS is built.
- [ ] Every change broadcasts `{"type": "highlight", "data": HighlightBoard.state()}` on `/ws` (`current`, `queue`, `queue_len`, `hold_sec`, `show_avatar`); new sockets get it on connect. Stream Rooms uses `current.user` / `current.platform` for the seat glow.
- [ ] Highlights are built by `clean_item()`: known fields only, strings clipped, emote / picture links must be http(s), avatar_local must be `/avatars/...`, colours must be `#hex`. The overlay escapes all text too (it shares an origin with `/admin`).
- [ ] Red-flagged chatters can't be highlighted (409), and `main.py hide_flagged` takes a newly flagged chatter off the screen and queue (`forget_user`).
- [ ] Recent chat list (`note_chat`, last 300 lines, each with a rising `seq`): fed from `main.py _on_chat` (after the overlay payload) and `_on_flagged_chat` (marked `flagged`); Core's own echoed replies are left out. `recent_since(after)` returns `reset: true` when the window must start over (first call, or Core restarted).
- [ ] `POST /api/admin/highlight` finds the line by platform + message_id (keeps emotes); an older saved line (Chat & flags) sends `message` + `user` as a fallback. `X-Fridge-From: phone` marks phone presses. Each push adds a "command" line to the Stream events window.
- [ ] A highlight reaching the screen calls `on_featured` → `CreditsEngine.feature` (Featured section in the end credits).
- [ ] Overlay message HTML matches the chat overlay's emote handling (`chat.js renderMessageHtml`): Twitch / 7TV ranges, Kick `[emote:ID:NAME]` tokens. Row carries the chat overlay's class names so `?css=<saved chat stylesheet>` works.
- [ ] Settings save (`PUT /api/admin/highlight/settings`) merges into the live config; other blocks kept.

## After-change verify

- [ ] `python -m pytest tests/test_highlights.py -q`
- [ ] Overlay Links for OBS lists "Highlighted message (lower third)".
- [ ] Simulated chat (Chat games → simulate) shows up in the Live card's Recent chat; ★ puts it on `/overlay/highlight.html`.
