# Checklist — Chat games + crowd moments

Home: `fridge-stream-core/core/chat_games/`. Spec: [docs/CHAT_GAMES.md](../fridge-stream-core/docs/CHAT_GAMES.md). Admin: **Chat games** page (+ Live controls card). Boards: Stream Rooms reply screen / corner board, `/overlay/replies.html`.

## Must keep

- [ ] `chat_games.enabled` default **false**. Command group `chat_games` (bind `chat_games`) exists in `DEFAULT_GROUPS`, `DEFAULTS.command_groups` and `config.example.yaml`.
- [ ] `PUT /api/admin/config` keeps the live `chat_games` block; only `PUT /api/admin/chat_games` changes it (hot-applied, `invalidate()`).
- [ ] Every stake / prize goes through the one points ledger (`Store.spend_points` all-or-nothing, `adjust_points`), `source="game"`. No second points store; nothing below zero.
- [ ] Refund paths stay: prediction cancel / no winners, duel decline / expiry, seat move dropped by the game (`charge` → `ReactionEngine.pending`).
- [ ] Points games say "points are off" instead of running when `points.enabled` is false.
- [ ] A `commands.json` command (or `!permit`) and a reaction command win over a chat game with the same name (`command_taken`); the admin page lists clashes. Poll digits (`!1` …) and `!answer` only exist while a poll / question is open.
- [ ] Chat games watch every message (combos, hype) even when a reaction or command took it; system (Core bot) lines are ignored.
- [ ] Mod-only: opening / locking / settling predictions, polls, trivia, rate open/close (`is_mod`: platform mod flag or permissions mod/admin).
- [ ] Board and reply text comes from chat: `/overlay/replies.html` escapes it; Stream Rooms draws it as plain text.
- [ ] `data/chat_games.json` (requests, moments, ratings, trivia progress) stays local; `config/trivia.example.json` shipped, `trivia.json` is the user's.
- [ ] Time-based work only in `ChatGames.tick()` (main.py loop, 0.5 s) on the engine clock, so tests can drive it.

## Drop risks

- Rewriting `_on_chat` in main.py and losing the order: reactions → chat games → router (or returning before chat games observe).
- Using `CooldownGate` (wall clock) inside chat games instead of the engine `Gate`.
- A new stake path that uses `adjust_points(-x)` (clamps to 0) instead of `spend`.

## After-change verify

- [ ] `python -m unittest tests.test_chat_games tests.test_reactions -v`
- [ ] Admin → Chat games → Run → Test chat: "3 people laugh", `!slots 20` (points on), a poll from the card, `!1` from Test chat, End.
- [ ] `/overlay/replies.html?force=1` shows the board; Stream Rooms shows it on the reply screen / corner.
