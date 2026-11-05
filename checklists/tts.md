# Checklist — Read aloud (TTS)

Home: `fridge-stream-core/core/tts.py` (TtsEngine), `core/tts_text.py` (filters), `api/tts_routes.py`, `admin/tts.js` (Setup → Read aloud (TTS) page + Live controls "Read aloud" card), `overlay/tts-player.js` (loaded by the alerts overlay). Tests: `tests/test_tts.py`.

Core ships **no voice**. It talks to the streamer's own OpenAI-style server (`POST /v1/audio/speech`), usually on another PC. Cloud services use the same boxes and are untested.

## Must keep

- [ ] `tts.enabled` default **false**; every trigger has its own switch. Core runs fine with no server set.
- [ ] Server address accepts `host:port`, `.../v1` and `.../v1/audio/speech` (`speech_url`). The API key never leaves Core: GET sends `api_key_set`, a save keeps the old key unless a new one is typed, `api_key_clear` removes it.
- [ ] Settings save merges into the live config (`merge_settings` + `save_config`), other blocks untouched. The highlight trigger's switch is also written to `highlight.read_aloud` (and read from it when `tts:` has none).
- [ ] Alerts never wait on a voice longer than `server.timeout_sec` + `WAIT_EXTRA_MS`; a voice that won't come sends `tts_skip {alert_id}` so the overlay lets go at once.
- [ ] Server down: after `FAIL_LIMIT` (3) failures in a row Core stops asking, rechecks every `RECHECK_SEC` (30 s), notes "down" / "back" once each in Stream events, tries `backup_url` first when set. Paid lines and `!tts` lines not read go on the missed list (max 50, Replay / Remove); a missed or dropped `!tts` refunds its points. "Pretend the server is down" is in memory only.
- [ ] Blocked words: whole words only (`ass` ≠ `class`), `word*` prefix, phrases, leet / spaced-out / repeated-letter dodges caught (`norm_word`, `BlockList`). Names checked too (blocked name → "someone"). Optional red-flag phrases. Links dropped by default. A blocked line skips only the voice, never the alert.
- [ ] Templates fill only `{name}`, `{headline}`, `{message}`, `{amount}`; anything else in braces stays as typed.
- [ ] `!tts` (word, cost, cooldown, who): spends points before the line is made, refunds on filter / failure / Clear; mods skip the cooldown. Doesn't run when the command router already owns the word.
- [ ] Chat trigger skips commands, paid lines and Core's own echoed replies; who / 1-in-N / min gap apply.
- [ ] Audio files live in `data/tts/` (git-ignored with `data/`), last `KEEP_FILES` kept, served at `/tts/<file>` only when the name matches `FILE_RE`.
- [ ] Overlay plays one line at a time; alert-tied lines wait for that alert to show and its sound to end; lines for alerts a source filtered out never play there. `?tts=0`, `?tts_volume=` (catalog + ALERTS.md). A line is cut at 2 minutes.
- [ ] Plugins: `await ctx.say(text, voice)` (docs/PLUGINS.md) goes through the filters and the "Game plugins" trigger.
- [ ] Dashboard: settings page lives under Setup → Stream look; the Live card shows only while TTS is on (Skip, Clear queue, missed list).

## After-change verify

- [ ] `python -m pytest tests/test_tts.py tests/test_overlay_compat.py -q`
- [ ] Setup → Read aloud (TTS): Check connection, Play here, Send to overlay, Blocked words "What would be read?", pretend chatter, pretend down → missed list → Replay.
- [ ] Alert test with "Read aloud too": the alert stays up until its voice ends.
