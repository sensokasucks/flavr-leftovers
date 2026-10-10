# Checklist — Shared overlays

Home: `fridge-stream-core/overlay/`. Captured as XSplit / OBS **Webpage** (or Browser) sources. Transparent where noted.

## Must keep

Core (:3850):

| URL | Role |
|-----|------|
| `/overlay/chat.html` | Multi-platform chat (`?platform=` / `?platforms=`) |
| `/overlay/overlay.html` | Stats widgets |
| `/overlay/alerts.html` | Follow / sub / raid / bits / Super Chat / donation |
| `/overlay/credits.html` | End credits (crawl, Star Wars, pages, ticker, typewriter, matrix) |
| `/overlay/market.html` | Ticker tape |
| `/overlay/market-board.html` | Board |
| `/overlay/market-chart.html` | Chart |
| `/overlay/openttd.html` | OpenTTD companies (file in `plugins/openttd/overlay/`; plugin `overlay/` folders are served at `/overlay/` after Core's own) |
| `/overlay/openttd-ticker.html` | OpenTTD ticker |
| `/overlay/replies.html` | Command replies (Core's API-free reply path; `?force=1` ignores `overlay.replies_enabled`) |
| `/overlay/reactions.html` | Chat reactions fallback (see [reactions.md](reactions.md)) |
| `/avatars/<platform>/<file>` | Chatter pictures Core saved (not a source; overlays and Stream Rooms load them). By name: `/api/chatters/avatar?name=` |

- [ ] Stats widgets are selectable: Admin → Config → Overlay (`overlay.modules`) **and** URL query `?show=` / `?hide=` (query wins).
- [ ] Default modules: health, food, xp, deaths, armor, viewers, cpm, power, effects, inventory.
- [ ] Overlay HTML stays dumb. No hidden business logic that Core already owns.
- [ ] Anything that can carry chat, player, or bridge text is escaped before `innerHTML` (`replies.html`, `openttd*.html`, market name fields via `FridgeMarket.esc`). Overlays share an origin with `/admin`.
- [ ] Sibling overlays keep their own ports (do not proxy them through 3850 unless you also update Sources + this list):
  - Factorio `http://127.0.0.1:3847/overlay.html` (+ split sources)
  - Chat Credits standalone `http://127.0.0.1:3854/overlay/credits.html`
  - Granvir `http://127.0.0.1:3855/overlay.html` (+ health/heat/campaign/squad)
- [ ] Reactive Image is **Window Capture**, not a Webpage source.
- [ ] Command replies: every `ChatReply` goes out on `/ws` as a system `chat` line **and** `{"type":"reply","data":{id, message, platform, reply_to_user, reply_to_message_id, source, timestamp, posted_to_chat}}` (`source`: command / reaction / game). New sockets get `reply_history` (last 20). `replies.html` and the Stream Rooms reply screen use `reply` only, so nothing shows twice. Keep the recent_* lists trimmed in place (`del lst[:-n]`) — `state.recent_*` points at the same list.
- [ ] `/ws` fan-out: each client has its own send queue and task (`api/server.py` `_ClientSender`); a broadcast never waits for a client, except up to `SEND_ROOM_WAIT_SEC` (0.25 s) once when that client's queue is full. A client 1,000 messages behind after that wait or with one send stuck for 15 s is closed (code 1013) and reconnects. Tests: `tests/test_busy_chat.py`.
- [ ] `overlay/overlay-hint.js` (chat and alerts overlays): a corner line saying whether Core answers, which platforms are connected (`/api/health` `connected`), the filter and the message count. Shown only outside OBS (`window.obsstudio` absent), never with `?preview=1`; `?hint=0` hides it, `?hint=1` forces it. The chat overlay ignores unknown platform names in `?platform=` / `?platforms=` (with a console warning) and shows every platform when none is left; `yt` / `ttv` are accepted.

## Drop risks

- Rewriting `overlay.js` and losing `?show=` / `?hide=`.
- Removing a source from the Admin Sources list because “it is in another repo folder”.
- Putting secrets or player tokens in overlay query strings.

## After-change verify

- [ ] Admin → Sources still lists every URL in the table above plus sibling ports.
- [ ] `overlay.html?show=health,power` still hides the rest.
- [ ] Chat overlay filter query still works (see [adapters-chat.md](adapters-chat.md)).
