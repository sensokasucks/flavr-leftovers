# Checklist — Adapters / chat

Home: `fridge-stream-core/adapters/` (`kick.py`, `twitch.py`, `youtube.py`). Overlay: `overlay/chat.html`.

## Must keep

- [ ] Platforms are adapters only. They emit normalized chat / alert events onto the EventBus. They do not own commands, points, or games.
- [ ] Kick, Twitch, and YouTube all default **off** in `config.yaml`, `config.example.yaml`, and `core/config.py` DEFAULTS.
- [ ] Kick: Pusher chat, emotes, badges, chatroom id autodetection persisted to `config.yaml`.
- [ ] Twitch: anonymous IRC listen. No OAuth required to read chat.
- [ ] YouTube: dual-mode `innertube` / `official` / `auto`. Official needs `api_key`; innertube needs `video_id`.
- [ ] Chat overlay at `/overlay/chat.html` (Core :3850). Supports `?platform=` and `?platforms=` filters.
- [ ] Kick emote tokens `[emote:id:name]` resolve to `files.kick.com`.
- [ ] Chat payload `user.profile_image_url`: YouTube from the author photo; Kick from a one-time channel lookup cached in `data/kick_avatars.json` (`kick.avatars`, default on), followed by a `type:user_update` broadcast. Twitch: none yet.
- [ ] Twitch `type:chat` payloads carry `emotes` ranges (native IRC `emotes` tag + BetterTTV / FrankerFaceZ / 7TV via `adapters/twitch_emotes.py`, toggle `twitch.third_party_emotes`, default on). `start`/`end` are inclusive code points; the chat overlay renders them with `Array.from`. External readers (Stream Rooms audience) rely on this field.
- [ ] YouTube (InnerTube): standard emoji runs become the emoji character (so emoji reactions fire); YouTube / member custom emoji keep their `:shortcut:` text plus an `emotes` range with the image (`provider:"youtube"`, same shape as Twitch). `adapters/youtube.py` `runs_to_text_and_emotes`, tests in `tests/test_youtube_chat.py`.
- [ ] Core broadcasts `type:chat` and `chat_history` on the overlay WebSocket.
- [ ] Platform settings (Kick / Twitch / YouTube) hot-apply: admin Config save and hand edits to `config.yaml` (`core.watch_config`) reconnect only the changed platforms via `StreamCore.apply_platforms`. Status tab has a per-platform Reconnect. Game toggles and the port still need a restart. Tests: `tests/test_platform_reload.py`.

## Drop risks

- Adding a fourth platform by stuffing logic into `kick.py` instead of a new adapter.
- Flipping a platform default to `true` in DEFAULTS or example config.
- Chat overlay losing multi-platform filters when the WS payload shape changes.
- Kick avatar lookups without the cache / 403 back-off (one request per message would get the IP blocked by Cloudflare).
- Dropping `emotes` from the chat payload or `ChatEvent` (overlay and Stream Rooms fall back to plain text silently).

## After-change verify

- [ ] Example config still has all three platforms `enabled: false`.
- [ ] Admin → Status still lists each adapter separately.
- [ ] Admin → Sources still links `/overlay/chat.html`.
- [ ] Chat overlay still works with no platform query (all enabled platforms) and with a filter.
