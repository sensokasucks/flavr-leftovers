# Checklist — Credits (built into Stream Core)

Home: `core/credits.py`, `core/cast.py`, `core/credits_theme.py`, `overlay/credits.*`, Admin Credits tab. Spec: `overlay/CREDITS.md`, motions: `overlay/MOTIONS.md`.

Standalone twin: the [fridge-chat-credits](https://github.com/sensokasucks/fridge-chat-credits) repo (its own checklist is there) — same cast module idea, different process. Core's overlay engine is the merged superset (it also runs under the standalone: `/api/credits/*` first, then `/api/*`). The standalone `cast.py` does not send the movie extras below.

## Must keep

- [ ] Opt-in: `credits.enabled` default **false**. Enable from Admin → Credits (hot-applied) or Config checkbox.
- [ ] The on/off switch is only on the Credits page; Settings → Points, permissions + chat → Chat credits just says on/off with a link. `PUT /api/admin/config` keeps the live `credits.enabled` (a stale form copy can't switch credits off). `POST /credits/play` returns `credits_enabled` and a `warning` while off. Tests: `tests/test_dashboard_tidy.py`.
- [ ] Unique chatters come from the **same** Kick / Twitch / YouTube adapters as live chat. No second listener.
- [ ] Overlay URL: `http://127.0.0.1:3850/overlay/credits.html` (transparent Webpage source).
- [ ] Every motion runs on one pixel `requestAnimationFrame` loop (`credits.speed_px_per_sec` / `duration_sec` for crawls). Do **not** go back to CSS `@keyframes` + `translateY(%)` (CEF dropped that animation).
- [ ] Motion / motion-timing change and Restart **hard-reset** the engine (timers, observers, transforms). Look and roster changes **redraw in place** (crawl keeps its y, pages keep their page).
- [ ] Hold / Pause still mount the chosen motion (Matrix, Teletype, pages) frozen — never fall back to a crawl.
- [ ] Modes: `loop` / `once` / `hold` / `clear` (play once, then empty screen; `clear_when_done` does the same for `once`). Roll credits freezes the unique list and restarts the crawl from below the frame. Live appends do not jump to the top.
- [ ] Cast styles in `config/cast/*.json` (`names` or `movie`). Shipped style: `movie.json`.
- [ ] Persistent job pins in `data/cast_overrides.json` survive session reset and roll.
- [ ] Groups: mods, subs, starring (top talkers); raiders / followers / gifted-subs from the alert bus.
- [ ] Movie extras pass through `CastBoard.decorate()` from the style JSON only when defined: `cards`, `starring` (labels → top talkers), `thanks`, `legal`, `end_hold_sec`, `stinger`, `look`. `{count}` expands. A plain `movie.json` sends none of them.
- [ ] One appearance per person in a movie roll (overlay de-dupes by display name).
- [ ] Commands (group `credits`, bind `credits`):
  - `!credit "name" "job title"` (aliases `!job`, `!cast`)
  - `!credit "name" clear`
  - `!credits` (unique chatter count)
- [ ] `credits.command_permission`: `mod` (default) / `admin` / `public`.
- [ ] Job titles capped at **50** characters.
- [ ] Session list saved to `data/credits_session.json`.
- [ ] The session file is written compactly (no indent) from a worker thread (`CreditsEngine.save_if_dirty_async`), never on the event loop during a stream.
- [ ] Admin → Credits API must include `cast` (styles, current style, pins, `command_permission`, job cap) **and** write routes:
  - `PUT /credits/cast/style`
  - `PUT /credits/cast/file`
  - `POST /credits/cast/pin`
  - `PUT /credits/command-permission`
- [ ] Style editor: Motion / Copy / Type / Color / Layout / List + live preview + look presets (Classic, Star Wars, Gold, Neon, Teletype, End card, Name tape, Matrix, Minimal). Presets reset letterbox / grain / backdrop first. Aliases `teletype` / `nametape`.
- [ ] Motions: `crawl`, `crawl-down`, `starwars`, `cards`, `fade`, `slides`, `ticker`, `typewriter`, `matrix`. `MOTION_IDS` (`core/credits_theme.py`), editor `MOTIONS` and the overlay stay in lockstep.
- [ ] `sanitize_look()` runs in `configure()` and `apply_theme()`: standalone keys convert (`sw_tilt_deg`, `sw_perspective_px`, `page_hold_sec`, `page_fade_sec`), enums fall back, numbers clamp, **unknown keys pass through**. `configure()` keeps every non-engine `credits:` key (it used to drop keys missing from `LOOK_DEFAULTS`).
- [ ] `GET /api/admin/credits/roster.csv` (admin token) — columns `platform, username, display_name, messages, first_seen, mod`.
- [ ] Admin Credits tab listens on `/ws` for `credits_roster` / `credits_play`; Pause label follows the real play state.
- [ ] Config → Chat credits edits `ignore_usernames`, `min_message_length`, `ignore_own_channel` and merges onto the loaded `credits:` block (look keys survive).
- [ ] `/overlay/*` and `/admin` html/js/css served `Cache-Control: no-store`.

## Drop risks

- **0.13.1 regression:** shipping the Credits tab UI without the matching admin API fields / write routes.
- Config save wiping `credits.*`.
- Replacing the RAF crawl with CSS animation “because it is simpler”.
- A look sanitizer that whitelists keys: new overlay keys (and Matrix / Teletype) silently revert to Classic after a save or restart.
- Resetting the roll on every theme message: live previewing a colour restarts the credits mid-stream.

## After-change verify

- [ ] `GET /api/admin/credits` returns `cast` plus enable/mode/look.
- [ ] Credits tab loads styles, can pin a job, and can change command permission without a 404.
- [ ] Overlay still scrolls in a transparent Webpage source (document if you only smoke-tested in a normal browser).
- [ ] `python -m unittest tests.test_credits tests.test_boot` pass.
- [ ] Each motion plays, loops, and ends correctly on Play once / Play once, then clear (`window.__credits.engine.phase`).
- [ ] Status hub shows credits on/off and unique count.
- [ ] Sources list points at the built-in overlay (standalone :3854 stays optional).
