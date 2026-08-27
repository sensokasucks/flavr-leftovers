# Fridge Chat Credits

Standalone, low-overhead credits roll for stream chat.

It listens to the platforms you enable, keeps **one unique row per chatter per platform**, and drives a movie-style scrolling overlay you drop into XSplit (or OBS) as a Webpage source.

Nothing here talks to Minecraft, Factorio, or Stream Core unless you opt in. The process is one Python asyncio loop + a tiny JSON session file.

**Non-tech install (Windows):** follow **[INSTALL.md](INSTALL.md)** — install Python once (pip is included; you never run pip yourself), then double-click **INSTALL Chat Credits.bat**. You do **not** need Stream Core.

```
Twitch IRC ─┐
Kick Pusher─┤
YouTube API─┼─► EventBus ─► Roster (unique names) ─► /overlay/credits.html
Core ingest─┘                                      ─► / control desk
```

## Why it stays light

- No browser inside the app. XSplit already renders the Webpage source.
- No SQLite, no points, no command router, no viewer polling.
- Twitch is anonymous IRC (`justinfan`) — no OAuth token.
- Kick is the same public Pusher socket Stream Core uses, without the metrics loop.
- YouTube and Stream Core ingest are off unless you turn them on.
- Session is a JSON file rewritten every few seconds only when the list changed.

Typical idle cost is a few tens of MB of RAM for the Python process.

## Quick start (Windows)

1. Install [Python 3.10+](https://www.python.org/downloads/) and tick **Add python.exe to PATH**.
2. From the workshop folder, double-click **`INSTALL Chat Credits.bat`** (once).
3. Double-click **`START Chat Credits.bat`** whenever you stream.
4. Open [http://127.0.0.1:3854/](http://127.0.0.1:3854/) — enable Twitch / Kick, Save config, restart once.
5. Webpage source: `http://127.0.0.1:3854/overlay/credits.html` (transparent).

Full click-by-click: **[INSTALL.md](INSTALL.md)**.

Inside this folder you can also use `install.bat` / `start.bat`.

### Manual / macOS / Linux

```bash
cd fridge-chat-credits
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# edit config/config.yaml — or use the control-desk Config section
python main.py
```

### URLs

| Page | URL | Use |
|------|-----|-----|
| Control desk | http://127.0.0.1:3854/ | Counts, look editor, freeze/roll/reset, **config editor** |
| Credits overlay | http://127.0.0.1:3854/overlay/credits.html | XSplit / OBS Webpage source |
| Same overlay | http://127.0.0.1:3854/credits | Alias |
| CSV export | http://127.0.0.1:3854/api/roster.csv | Backup of the list |

The control desk **Config.yaml** section writes this app’s own `config/config.yaml` (Twitch / Kick / YouTube / Stream Core ingest / ignore list). That file is **not** Stream Core’s config. Platform toggles need a restart; look and ignore-list changes apply immediately.

If you already run Stream Core, you can skip this standalone app and use **Admin → Credits** there instead (same overlay, Core’s chat adapters, no second process).

Use a **transparent** Webpage source, full canvas or a centered column.

The overlay crawls with a pixel `requestAnimationFrame` loop (not CSS
`@keyframes`). Speed is `credits.speed_px_per_sec` in real pixels.

**Roll credits** freezes the unique list and restarts the crawl from below the
frame. New chatters in live mode are appended without jumping the roll back to
the top.

## Config (`config/config.yaml`)

Copy from `config.example.yaml` if you want a clean slate.

### Platforms (all optional, all off until enabled)

**Twitch** — read-only IRC, no login:

```yaml
twitch:
  enabled: true
  channel: "your_channel"
```

**Kick** — public chat socket:

```yaml
kick:
  enabled: true
  channel_slug: "your_slug"
  # chatroom_id: 12345678    # only if the API lookup 403s
```

**YouTube** — Data API poller (heavier, needs a key + the live video id):

```yaml
youtube:
  enabled: true
  api_key: "AIza..."
  video_id: "xxxxxxxxxxx"
```

**Stream Core ingest** — reuse chat Core is already reading so you do not open a second Kick socket:

```yaml
ingest:
  stream_core:
    enabled: true
    ws_url: "ws://127.0.0.1:3850/ws"
```

Do not enable both `kick.enabled` and Stream Core ingest unless you want Kick names twice.

### Roster filters

```yaml
roster:
  ignore_own_channel: true
  min_message_length: 1
  ignore_usernames:
    - nightbot
    - streamelements
```

Identity is `(platform, username)`. The same person on Twitch and Kick appears twice, which is intentional — the overlay can show which platform they spoke on.

### Credits look

Everything under `credits:` is live-editable from the control desk (saved to `data/theme.json` so your YAML comments stay intact).

Useful keys:

| Key | Meaning |
|-----|---------|
| `title` / `subtitle` / `footer` | Header and closer lines |
| `section_label` | Label above the mixed name grid |
| `group_by_platform` | Split Twitch / Kick / YouTube blocks |
| `sort` | `first_seen` · `name` · `messages` · `last_seen` |
| `columns` | 1–3 |
| `speed_px_per_sec` | Crawl speed |
| `mode` | `loop` · `once` · `hold` |
| `show_platform` | Colored dots next to names |
| `highlight_mods` | Gold names for mods / broadcaster |
| `custom_font_url` | Optional stylesheet URL for a webfont |
| `background` | `transparent` for overlay; `#000` to preview |

Query-string overrides work on the overlay without touching config, e.g.

`http://127.0.0.1:3854/overlay/credits.html?columns=1&speed_px_per_sec=28&title=THE%20CREW`

## Control desk

- **Roll credits (freeze list)** — snapshot the current names so a late chatter does not reshuffle mid-roll.
- **Live list** — overlay grows as new unique people speak.
- **Loop / Play once / Hold still** — playback mode.
- **Reset session** — empty the unique list (also wipes `data/session.json`).
- **Save look** — persist colors, type, speed, grouping.
- **Add** — seed a test name so you can preview the roll offline.

## Adding another platform later

1. Subclass `adapters.base.BaseAdapter`.
2. Normalize each message into `ChatEvent` / `ChatUser` (`core/models.py`).
3. `await self._emit(event)`.
4. Register it in `main.py` behind a config flag.

The roster, overlay, and control desk do not change.

## Ports

| App | Port |
|-----|------|
| Stream Core | 3850 |
| Reactive Image | 3851 |
| This app | **3854** |

Bound to `127.0.0.1` by default.

## Layout

```
fridge-chat-credits/
├── main.py
├── requirements.txt
├── INSTALL.md         # click-by-click for non-tech users
├── install.bat        # one-time Windows install
├── start.bat          # start while streaming
├── config/config.yaml
├── core/          models, bus, roster, config
├── adapters/      twitch, kick, youtube, stream_core
├── api/server.py
├── overlay/       credits.html + control.html
└── data/          session.json + theme.json (created at runtime)
```
