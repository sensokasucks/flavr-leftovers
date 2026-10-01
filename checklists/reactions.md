# Checklist — Chat reactions

Home: `fridge-stream-core/core/reactions.py`. Spec: [docs/REACTIONS.md](../fridge-stream-core/docs/REACTIONS.md). Admin: Config → Reactions. Overlay: `/overlay/reactions.html`.

## Must keep

- [ ] `reactions.enabled` default **false**. Command group `reactions` (bind `reactions`) exists in `DEFAULT_GROUPS`, `DEFAULTS.command_groups` and `config.example.yaml`.
- [ ] Core owns permissions, sub/VIP limits, cooldowns, costs, opt-in/out and replies. The game and the overlay only draw.
- [ ] Costs go through the one points ledger: `Store.spend_points()` (atomic, never negative, whole units only), refunds via `adjust_points`, both `source="reaction"`. No second points store.
- [ ] Entries with `cost > 0` do nothing while `points.enabled` is false (and the editor says so).
- [ ] Nothing is charged for a refused reaction (permission, target, cooldown, no route). A charge that can't be delivered is refunded. `dropped` from the game refunds once.
- [ ] Emoji triggers never post chat replies. Commands may.
- [ ] A `commands.json` command (or `!permit`) with the same name wins over a reaction command. The editor lists clashes.
- [ ] Only a WebSocket that sent `hello` may send `room_state` / `reaction_result` / `say` / `overlay`. `say` is rate limited and length-capped. Unknown frames are ignored (old overlays still just send `ping`).
- [ ] `reaction` events go only to hello'd game sockets when routed to the game; the overlay route is a broadcast with `route:"overlay"`, and the overlay ignores other routes.
- [ ] `PUT /api/admin/config` keeps the live `reactions` block; only `PUT /api/admin/reactions` changes it (and hot-applies).
- [ ] Overlay text from chat is set with `textContent` only.
- [ ] Opt-outs persist in `data/reactions_optout.json`.
- [ ] Pictures (`core/reaction_images.py`): `GET /reactions/images/<file>` serves only a bare file name with a png/jpg/gif extension from `data/reaction_images/` then `overlay/assets/reactions/` (no path traversal). Uploads are admin-only, type sniffed from bytes, capped at 5 MB, and written only to `data/reaction_images/` (local, gitignored). Delete never touches built-ins.
- [ ] `ReactionEngine.play()` (chat games) skips the rules but keeps routing, `system: true`, and refunds a `charge` when the game reports `dropped`.
- [ ] `{args}` reactions (sign) take all typed words as text (no target / count); `TARGET_REQUIRED` effects (highfive, seat_swap) refuse a missing or self target.
- [ ] Emote pictures only use https URLs learned from chat (`EmoteBook`); the fallback overlay only loads `/reactions/images/` or https.
- [ ] Stage frames: Core → game `stage` {action: curtain, value: open|close|reveal|toggle} only to hello'd game sockets (`send_stage`); game → Core `stage_state` {curtain} kept in `status().stage`. `POST /api/admin/stage` and mods' `!curtain` (chat games `stage`) are the only senders.
- [ ] New built-in entries go in `LATER_DEFAULTS` and are seeded once via `reactions.seeded_defaults`; a deleted entry is never re-added.
- [ ] Target names compare with `target_key` (no case, spaces, `_ - .` or `@`), so YouTube handles (`@Name`) match however they're typed; opt lists ignore `@`; replies use one `@`.

## Drop risks

- Rewriting the WS loop in `api/server.py` and losing the JSON branch or the `detach` in `finally`.
- Adding a cost check with `adjust_points(-cost)` (clamps to 0 instead of refusing).
- Config save serializing a stale `reactions` copy from the form.
- Seeding a new default on every normalize (re-adds entries the streamer deleted).

## After-change verify

- [ ] `python -m unittest tests.test_reactions tests.test_reaction_images tests.test_youtube_chat -v`
- [ ] Config → Reactions → Pictures: upload a PNG and a GIF, `!boot` / `img:<name>` draws them in the overlay and Stream Rooms.
- [ ] Admin → Config → Reactions loads, saves, Test sends to the overlay (no game) / game.
- [ ] `/overlay/reactions.html?debug=1` draws a test reaction.
