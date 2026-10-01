# Checklist — Chat Credits (standalone)

Home: `fridge-chat-credits/`. Port **3854**. Use this list only when that package is in play. Core’s built-in roll is [credits-core.md](credits-core.md).

## Must keep

- [ ] Unique chatters **per platform**. One row per chatter per platform.
- [ ] Adapters: Twitch IRC, Kick Pusher, optional YouTube, optional Stream Core ingest. All off until enabled.
- [ ] No Minecraft / Factorio / points / command router unless ingest is explicitly on.
- [ ] Overlay: `http://127.0.0.1:3854/overlay/credits.html` (alias `/credits`).
- [ ] Desk API stays behind `core/local_guard.py` (`LocalGuard(..., section="app")`) + loopback-only CORS — the desk has no login.
- [ ] Control desk: `http://127.0.0.1:3854/` — counts, look editor, freeze/roll/reset, **this app’s** config editor.
- [ ] Desk Config.yaml writes `fridge-chat-credits/config/config.yaml`, **not** Stream Core’s file.
- [ ] Platform toggles need a restart; look + ignore-list apply immediately.
- [ ] Session JSON under `data/`. CSV at `/api/roster.csv`.
- [ ] Same movie-cast idea as Core (`core/cast.py`, `config/cast/*.json`, pins, 50-char jobs).
- [ ] Pixel `requestAnimationFrame` crawl. Do not revert to CSS `@keyframes` + `translateY(%)`.
- [ ] Root bats: `INSTALL Chat Credits.bat` / `START Chat Credits.bat`.
- [ ] If the user already runs Core Credits, README still says they can skip this process.

## Drop risks

- Control desk saving into Stream Core’s `config.yaml`.
- Adding SQLite / points “to catch up with Core” and losing the light footprint.

## After-change verify

- [ ] Overlay and desk URLs still documented in the package README.
- [ ] Cast style + pin behaviour still matches the Core credits contract, or the README says where they diverge.
