# Chat games + crowd moments

Chat-driven crowd moments and games: emote combos, the hype meter, cheer vs boo, a group launch, streaks and titles, seats, predictions, duels, slots, heists, trivia, polls, ratings, requests and moments.

Core owns every rule, the same way it does for chat reactions: commands, permissions, cooldowns, timers and points. What viewers see goes out two ways:

- **Effects** go through the reaction path (`ReactionEngine.play`). Stream Rooms draws them, or `/overlay/reactions.html` does when the game isn't connected.
- **Boards** (polls, predictions, the hype meter, heist crews, trivia and so on) go out as `board` packets. Three places draw them:
  - Stream Rooms' reply screen, in rooms with a `REPLY_Screen` marker.
  - Stream Rooms' corner board. In other rooms it shows by default; see Audience tab → Chat games.
  - `/overlay/replies.html`. Add `?boards=0` to hide boards there, or `?replies=0` to show boards only.

Answers go through the same API-free reply path as other commands, with `source: "chat_game"`. Core can't post into Kick or YouTube chat without a login, so the reply screen and the replies overlay are where viewers read them.

## Turning it on

1. Go to **Admin → Chat games → Settings**, tick **Chat games on**, then press **Save + apply**. It works straight away; no restart is needed.
2. The `chat_games` command group must also be on. It is on by default, under Settings → Command groups.
3. Some games spend points, so they need **Chat points** turned on:
   - `!predict`, `!duel`, `!slots` and `!heist`
   - `!claim`
   - `!bump`
   - `!seat front`

Every feature has its own **On** switch and its own command names. The config block is `chat_games:` in `config.yaml`; every key is optional. A normal Config save never overwrites this block.

A chat command in `commands.json` wins over a chat game with the same name, and so does a reaction command. The Settings page lists any such clashes.

## What chat can do

### Crowd moments

| Chat | What happens |
|------|--------------|
| Emotes / emoji | **Emote combos.** When 3+ different people use emotes from the same mood within 10 s, that mood's effects play. Numbers in the effects scale up with the crowd, up to 3×. Each mood has its own cooldown. Edit the moods in Admin → Chat games → Emote combos. |
| (just chatting) | **Hype meter.** Counts different people chatting in the last 60 s. Each level (5 / 10 / 20 people) fires its effects once, with a cooldown before the same level can fire again. The meter shows as a small board. |
| `!cheer` / `!boo` | **Tug of war.** The first one starts a 30 s round. Each person counts at most once a second. When the round ends, the winning side gets its reveal: confetti and a standing crowd for cheers, a tomato rain and dim lights for boos. |
| `!launch` | **Group launch.** 5 people within 60 s starts a sequence: lights down, a spotlight, a 3-2-1 board, then fireworks, confetti, a camera shake and a cheering crowd. The pad then recharges for 10 min. If not enough people join, it fizzles and can be tried again after a minute. |

The default moods and their emotes:

| Mood | Emotes and emoji |
|---|---|
| laugh | KEKW, LULW, LUL, OMEGALUL, `face-purple-smiling-tears`, 😂 🤣 |
| hype | PogU, PogChamp, GIGACHAD, `face-blue-star-eyes`, 🔥 🚀 |
| clap | Clap, HYPERCLAP, 👏 |
| love | `<3`, catKISS, `face-red-heart-shape`, ❤️ 😍 |
| sad | Sadge, BibleThump, 😢 |
| dance | vibePls, catJAM, ratJAM, 💃 🕺 |
| shock | kkHuh, WutFace, monkaS, 😱 ❓ |
| sleepy | ResidentSleeper, 😴 |
| bye | KEKBye, GG, HeyGuys, 👋 |

In a mood's effects, `{emote}` stands for the emote the crowd used most. Core shows that emote's picture: Kick, Twitch, BTTV, FFZ and 7TV (still images), and YouTube custom emoji.

### Your seat

These seat commands are chat reactions. Edit them in Settings → Reactions.

| Chat | What happens |
|------|--------------|
| `!sign GO TEAM` | A sign over your head for 20 s |
| `!sleep` · `!snack` · `!phone` | 💤, 🍿, or a lit-up phone |
| `!highfive @name` | You both jump and high-five across the room |

These two are chat games, set in Admin → Chat games → Seats:

| Chat | What happens |
|------|--------------|
| `!seat front` / `!seat back` | Moves you to a free seat. The front costs 50 points, and they come back if no seat is free. |
| `!swap @name` | Offers a seat swap. They type `!swap` to accept (60 s). |

These Kick emotes play a one-off effect. They are also reactions:

| Emote | Effect |
|---|---|
| FLASHBANG | A white flash |
| POLICE (or 🚨) | Red and blue lights |
| ThisIsFine | Cartoon fire on the stage |
| DonoWall | A big shout |

### Points games

| Chat | What happens |
|------|--------------|
| `!claim` | Free points (50) once per stream |
| `!predict 1 50` · `!predict yes 50` | Bet on the open prediction. You can add to your bet but not switch sides. Winners split the whole pot by stake. If nobody picked the winner, everyone is refunded. |
| `!duel @name 50` → `!accept` / `!decline` | Coin flip. The winner takes both stakes, and the loser gets a 🍅 (Settings: *Thrown at the loser*). With no answer in 60 s, the stake is refunded. |
| `!slots 20` | Three reels (see below) |
| `!heist 50` → `!join 50` | Starts a crew; others join within 60 s. Then the story plays out on the reply screen. The success chance is 45% +4% per extra member, capped at 80%. If it works, each member has a 20% chance of being caught; the rest get 1.8× their stake. If it fails, everyone loses their stake. |

Amounts can be written as `50`, `1k` or `all`.

Slots pay out like this, for about 93% back on average:

| Reels | Pays |
|---|---|
| Three of a kind | 🍒 4×, 🍋 8×, 🔔 15×, ⭐ 25×, 💎 60×, 7️⃣ 200× |
| Two 🍒 | 1.5× |
| Any other pair | 0.5× |

### Watch along

| Chat | What happens |
|------|--------------|
| `!1` `!2` `!3` (or `!vote 2`) | Vote in the open poll. You can change your vote. |
| `!rate 8` | Rate what's on (1–10). The first `!rate` opens voting for 2 min. The result is announced, and the latest rating from this stream goes into the end credits, above the footer. |
| `!request <link or title>` | Adds to the queue (2 each, 50 in total). |
| `!bump` | Spends 100 points to move your request up. |
| `!queue` | Shows the next three requests. |
| `!clip` / `!moment [note]` | Marks the stream time. Marks within 20 s of each other count as one moment. |
| `!answer <guess>` | Answers the trivia question. The first right answer gets 100 points and a spotlight on their seat. Case, accents, spaces and a leading "the" / "a" don't matter. |

### Regulars

| Chat | What happens |
|------|--------------|
| `!streak` | Streams in a row, best run and total |

Titles are earned at **5 / 10 / 25** streams: *Regular*, *Die-hard*, *Legend*. By default a title is based on your best run.

- Stream Rooms shows the title on name tags ("Name · Regular"). Turn this off in Audience tab → *Regulars' titles on name tags*.
- The end credits show it next to the name.

A **stream** starts when chat comes back after a quiet gap, 4 h by default. Admin → Chat games → Run → **Start a new stream now** forces a new one.

`!help` also lists the reaction and chat game commands that are on.

## For mods

Mods and admins can run these from chat:

| Command | Does |
|---|---|
| `!poll Question? \| A \| B \| C` | Opens a poll. Add `\| 90s` as a last part to end it on a timer. |
| `!poll end` | Ends the poll |
| `!predict open Question? \| A \| B` | Opens a prediction. With no options it's Yes / No. |
| `!predict lock` | Locks bets |
| `!predict win A` | Settles the prediction |
| `!predict cancel` | Cancels and refunds everyone |
| `!trivia` | Asks a question |
| `!trivia stop` | Skips the question |
| `!rate open Title` | Opens voting on a named title |
| `!rate close` | Closes voting |
| `!curtain open` / `close` / `reveal` | Runs Stream Rooms' stage curtain. Just `!curtain` toggles it. Admin → Live controls has the same buttons, and those work without chat games. |

**Admin → Chat games → Run** has the same controls, plus:

- the request queue, with **Played** and **Remove**;
- the moments list, with a CSV download;
- **Start a new stream now**;
- a **Test chat** box that sends a line through the whole live path, with "3 people laugh" and "Crowd launches" buttons.

The **Live controls** page has a Chat games card for mid-stream use.

Trivia questions come from `config/trivia.json`. If that file doesn't exist, `config/trivia.example.json` is used (45 general-knowledge questions). The format is:

```json
{"questions": [{"q": "What is the capital of Japan?", "a": ["Tokyo"]}]}
```

`a` lists every answer that counts; the first one is shown. Each question is asked once before any repeats. Set **Ask one every (min)** to ask on a timer.

## Board packet (for the game and overlays)

```jsonc
{"type": "board", "data": {
  "id": "poll",                  // poll | predict | tug | hype | launch | heist | trivia | rate
  "kind": "bars",                // bars | tug | meter | count | list | question | rating
  "title": "📊 Snack?",
  "lines": [{"key": "1", "label": "1. Popcorn", "value": 6, "pct": 0.6, "note": "6 (60%)", "win": false}],
  "footer": "Vote: !1 !2",
  "ends_at": 1790000060.0,       // or null
  "state": "open",               // open | locked | closed
  "ts": 1790000000.0}}
{"type": "board_clear", "data": {"id": "poll"}}
{"type": "board_history", "data": [ ...boards that are up... ]}   // new sockets
```

A closed board stays up for `board_hold_sec` (12 s), then clears. Text inside boards comes from chat, so escape it.

## Effects Core plays for chat games

These are reaction packets with `"system": true`. Two optional fields go with them:

- `crowd`: the `from` blocks of the people it's about.
- `cost`: points already taken. They are refunded if the game reports `dropped`.

| Used by | Effects |
|---|---|
| Crowd moments | `crowd_motion` (dance / cheer / wiggle / jump for everyone or the crowd), `float_up` and `wiggle` (from every crowd seat), `confetti`, `fireworks`, `meter`, `lights`, `spotlight`, `stadium_wave`, `camera_shake` |
| Seats | `seat_move`, `seat_swap` |
| Duels | `throw` at the loser |

The full list is in [REACTIONS.md](REACTIONS.md).

## Files

- `core/chat_games/`
  - `config.py`: defaults, cleaning, and the admin form
  - `engine.py`: commands, boards, timers and points
  - `crowd.py`
  - `regulars.py`
  - `wagers.py`
  - `watch.py`
- `core/store.py`: tables for streams and attendance (`streams`, `stream_attendance`)
- `data/chat_games.json`: requests, moments, ratings and trivia progress (local)
- `api/admin_routes.py`:
  - `GET /api/admin/chat_games` and `PUT /api/admin/chat_games`
  - `POST …/action`
  - `POST …/simulate`
  - `GET …/moments.csv`
- `overlay/replies.html`: draws the boards
- `tests/test_chat_games.py`
