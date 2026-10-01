# Chat reactions

An emoji, emote or `!command` in chat plays an effect in a game (Stream Rooms) or, when no game is connected, on the fallback overlay `/overlay/reactions.html`.

Core owns every rule. The game only draws what Core sends and reports what happened.

| Rule | Where |
|------|-------|
| Triggers (emoji, emote names, commands) | `reactions.entries[].emoji / emotes / commands` |
| Effect + settings | `effect`, `params` (settings come from the effect list the game reports) |
| Who can use it | `permission` (public / mod / admin) + optional `require: [sub, vip]` (either one; mods and admins pass) |
| Cooldowns | per user, for everyone, per target (`cooldown_*_sec`), using `core.market.CooldownGate` |
| Cost | Core points ledger, `source="reaction"`. Needs `points.enabled`. Admins are free unless `admins_free: false` |
| Who can be targeted | `targeting: opt_out` (everyone until `!nothrow`) or `opt_in` (only after `!throwok`). Stored in `data/reactions_optout.json` |
| Chat replies | `reactions.messages.*` templates; emoji triggers never reply (no spam) |

Edit it all in **Admin → Config → Reactions**. Save writes the `reactions:` block of `config.yaml` and applies immediately. A normal Config save never overwrites that block.

## Chat syntax

- `🍅` — throw at the stage. `🍅🍅🍅` = three (capped by `max_per_message`, each one costs).
- `🍅 @bob` — the first `@mention` in the message is the target.
- `!tomato @bob`, `!tomato screen`, `!tomato mika` — audience member, stage spot, guest.
- `!tomato x5`, `!tomato 5`, `!tomato @bob 5`, `!tomato screen x5` — five at once (capped by `max_per_message`, each one costs). A bare number only counts on its own or after an `@mention`, so `!tomato presenter 2` still means presenter 2; use `x3` there.
- `command_count` (Admin: **Per command**) — how many a command fires when no number is typed, e.g. a `!barrage` entry with 10.
- `!nothrow` / `!throwok` — opt out / in. `!targets` — list this room's targets.
- A reaction whose settings contain `{args}` (the built-in `!sign`) uses everything typed after the command as its text: `!sign GO TEAM 2` holds up "GO TEAM 2" (no target, no count). Nothing typed → the `need_text` reply.
- `highfive` / `seat_swap` reactions need someone else: `!highfive` alone or at yourself → the `need_target` reply.

Built-in entries besides tomato / roses / confetti / wiggle / boot, added once to an existing config (`seeded_defaults`):

| Id | Trigger | Effect |
|----|---------|--------|
| `sign` | `!sign <text>` | `sign` over the sender's seat, 20 s |
| `sleep` / `snack` / `phone` | `!sleep` (`!nap`), `!snack` (`!popcorn`), `!phone` | `seat_prop` 💤 / 🍿 / lit-up phone |
| `highfive` | `!highfive @name` (`!hi5`) | `highfive` |
| `flashbang` | Kick emote FLASHBANG | `lights` flash |
| `police` | Kick emote POLICE, 🚨 | `lights` police (red / blue) |
| `this_is_fine` | Kick emote ThisIsFine | `stage_fire` |
| `dono_wall` | Kick emote DonoWall | `big_shout` "🧱 DONO WALL 🧱" |

Emote names as objects: Core remembers each emote it sees in chat (Twitch native / BTTV / FFZ / 7TV still images, YouTube custom emoji, Kick `[emote:id:name]`), so an object like `KEKW` goes out with `object_image` = that emote's picture once someone has used it. Until the picture loads (or if it can't), the game shows the name as text.

Target names ignore case, spaces, `_`, `-` and dots, so `!tomato Presenter 2` finds `presenter2` and `!tomato big piano` finds `big_piano`.

A reaction command only works if no `commands.json` command owns the same name. Clashes are listed in the Reactions editor; the chat command wins.

## Routing

`send_to: auto` sends to the game when one is connected, otherwise to the fallback overlay if it can play that effect, otherwise refuses ("the stage isn't open"). Nothing is charged for a refused reaction. `game` and `overlay` force one side.

The fallback overlay plays: `throw`, `fall_down`, `rain`, `float_up`, `confetti`, `big_shout`, `camera_shake`, `fireworks`.

Stream Rooms plays all of these, plus `pile_up`, `wiggle`, `stand_cheer`, `stadium_wave`, `spotlight`, `lights` (flicker / dim / tint / flash / police), `meter`, `crowd_motion` (wiggle / jump / cheer / wave / spin / dance, for everyone or the `crowd`), `sign`, `seat_prop`, `highfive`, `seat_move` (front / back), `seat_swap`, `stage_fire`, `fireworks`.

## WebSocket protocol (for the game)

Same socket as overlays: `ws://127.0.0.1:3850/ws`. JSON text frames. `"ping"` still gets `{"type":"pong"}`. Unknown frames are ignored.

### Game → Core

```jsonc
// 1. first, on every connect. Only a socket that sent hello may send the rest.
{"type":"hello","data":{"client":"stream_rooms","protocol":1,
  "effects":[{"id":"throw","label":"Throw","targeted":true,
              "params":[{"name":"object","type":"text","default":"🍅"},
                        {"name":"impact","type":"select","default":"splat","options":["splat","bounce"]}]}]}}
// param types: text | number (min/max) | select (options) | color | bool
// An effect listed without params keeps Core's built-in settings for that id.

// 2. whenever the room, guests or seating change
{"type":"room_state","data":{"room":"theater",
  "targets":[{"id":"screen","label":"Screen","aliases":["tv"]}],
  "guests":[{"id":"guest1","name":"Mika","aliases":[]}],
  "seated":["alice","bob"]}}      // omit seated (or null) to skip the "not in the audience" check

// 3. after playing a reaction
{"type":"reaction_result","data":{"id":"r-…","outcome":"hit"}}   // hit | fallback | dropped
// "dropped" refunds the points (refund_if_dropped). Results after 2 minutes are ignored.

// optional
{"type":"say","data":{"text":"bob got tomatoed"}}   // posted through Core's reply path, rate limited (say_per_minute)
{"type":"overlay","data":{…}}                       // relayed to overlays as {"type":"game_overlay","data":…}
```

### Stage (curtain)

Core → game: `{"type":"stage","data":{"action":"curtain","value":"open"|"close"|"reveal"|"toggle"}}` (Admin → Live controls → Stage curtain, `POST /api/admin/stage`, mods' `!curtain` from chat games).
Game → Core: `{"type":"stage_state","data":{"curtain":"open"|"closed"}}` on connect and on every change; Core keeps it in `status().stage` and relays it to overlays as `stage_state`.

### Core → game

```jsonc
{"type":"hello_ok","data":{"protocol":1,"reactions_enabled":true,"effects_known":["throw",…]}}

{"type":"reaction","data":{
  "id":"r-3f9c…", "reaction":"tomato", "label":"Tomato",
  "effect":"throw", "params":{"object":"🍅","impact":"splat","stick_sec":6,"arc_height":1.0},
  "count":2,                                   // 🍅🍅
  "from":{"platform":"twitch","id":"…","username":"alice","display_name":"Alice","color":"#ff8a3d","profile_image_url":"…"},
  "target":{"type":"user","name":"bob"},       // stage (name "" = anywhere) | user | guest | null
  "route":"game",                              // play only route == "game"
  "message":"🍅🍅 @bob", "cost":0, "ts":1790000000.0}}
```

The game also still receives every `chat` / `user_update` / `reply` broadcast, as any overlay does.

Reactions Core plays for itself (chat games: combos, the hype meter, duels, launches — see [CHAT_GAMES.md](CHAT_GAMES.md)) have `"system": true` and may carry `"crowd": [from, …]`, the people it's about: `float_up`, `wiggle` and `stand_cheer` play from every crowd seat, `crowd_motion` with `who: "crowd"` moves just them. `cost` > 0 means points were taken; a `dropped` result refunds them.

The target's name was checked against the last `room_state`. If it has gone since (the person left, the room changed), play it on the stage and report `"fallback"`.

## Pictures (custom images)

A reaction can throw / drop / float a picture instead of an emoji: set its **Object** setting to `img:<name>`. The built-in `boot` entry (`!boot`, 🥾) throws `img:boot`.

- Built-in pictures: `overlay/assets/reactions/` (ships `boot.png`).
- Your uploads: **Admin → Config → Reactions → Pictures**. Stored in `data/reaction_images/` (local, not in git). An upload with a built-in's name replaces it for this install; deleting the upload brings the built-in back.
- PNG, JPEG or GIF (animated GIFs play), up to 5 MB. The type is read from the file itself, not the extension. Names: `a-z 0-9 - _`, up to 40 characters.
- In an entry's Object box, click a thumbnail or type `img:name`; an unknown name is flagged.

Core adds `object_image` to the packet's `params` when the object is a known picture:

```jsonc
"params":{"object":"img:boot","object_image":{"name":"boot","url":"/reactions/images/boot.png?v=1790000000","animated":false}, …}
```

The URL is relative to Core's HTTP address. Stream Rooms turns its `chat_core_url` (`ws://host:port/ws`) into `http://host:port`, downloads the picture through `EmoteCache` and draws it as a sprite (it appears as soon as the first download finishes; later uses are cached). The fallback overlay draws an `<img>`.

Routes: `GET /reactions/images/<file>` (public, read-only, cached a day), `GET /api/admin/reactions/images`, `POST /api/admin/reactions/images` (`{name, data}` base64 / data URL), `DELETE /api/admin/reactions/images/<name>` (uploads only).

New built-in entries (like `boot`) are added to an existing config once and listed in `reactions.seeded_defaults`; if you delete one it stays deleted.

## Stream Rooms (the game side)

`stream_rooms/autoload/reactions.gd` + `core/reactions/reaction_layer.gd`. It sends `hello` with all 22 effects (throw adds a `splat_color` setting), `room_state` on connect / room swap / seat and podium changes, and a `reaction_result` for every reaction (`dropped` when reactions are off in the game, the effect needs a seat the sender doesn't have, or nothing reports within 20 s).

Targets it offers: `screen` (aliases tv, stage, movie), `webcam`, `chat`, one per `TARGET_<Name>` marker, and for each presenter on set a guest `presenter<n>` (their picture; aliases guest<n>, p<n>) plus a stage target `podium<n>` (their podium).

## Files

- `core/reactions.py` — engine, effect catalog, defaults, protocol
- `core/reaction_images.py` — picture library (built-in + uploads)
- `core/store.py` — `spend_points()` atomic check-and-debit
- `api/server.py` — WebSocket JSON frames → engine
- `api/admin_routes.py` — `GET/PUT /api/admin/reactions`, `POST /api/admin/reactions/test`
- `admin/` — Config → Reactions editor
- `overlay/reactions.html|css|js` — fallback overlay (`?debug=1`, `?scale=1.5`, `?any=1`)
- `data/reactions_optout.json`, `data/reactions_caps.json` (last effect list a game reported)
- `overlay/assets/reactions/`, `data/reaction_images/` — pictures
- `tests/test_reactions.py`, `tests/test_reaction_images.py`
