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
- [ ] Chat payload `user.profile_image_url`: YouTube from the author photo; Kick from a one-time channel lookup cached in `data/kick_avatars.json` (`kick.avatars`, default on); Twitch from Helix with the sign-in (`twitch.avatars`, `data/twitch_avatars.json`). Late lookups go out as `type:user_update`.
- [ ] Saved pictures (`core/avatar_store.py`, `avatars.save_local` default on): Core downloads each picture once into `data/avatars/<platform>/`, serves it at `/avatars/<platform>/<file>?v=<time>` and adds `user.avatar_local` to chat payloads and `user_update` (a second `user_update` when the file is ready). https public hosts only, 3 MB cap, weekly refresh, 10-minute back-off. `avatars.hide` names get no picture anywhere (a newly hidden chatter gets `user_update` with `hidden: true`); Stream Rooms merges its list in with `{"type":"avatars_hide_import"}`. The admin config save keeps `avatars` (owned by its own card). Tests: `tests/test_avatar_store.py`.
- [ ] Twitch `type:chat` payloads carry `emotes` ranges (native IRC `emotes` tag + BetterTTV / FrankerFaceZ / 7TV via `adapters/twitch_emotes.py`, toggle `twitch.third_party_emotes`, default on). `start`/`end` are inclusive code points; the chat overlay renders them with `Array.from`. External readers (Stream Rooms audience) rely on this field.
- [ ] YouTube (InnerTube): standard emoji runs become the emoji character (so emoji reactions fire); YouTube / member custom emoji keep their `:shortcut:` text plus an `emotes` range with the image (`provider:"youtube"`, same shape as Twitch). `adapters/youtube.py` `runs_to_text_and_emotes`, tests in `tests/test_youtube_chat.py`.
- [ ] Core broadcasts `type:chat` and `chat_history` on the overlay WebSocket.
- [ ] Sub events become overlay alerts through `BaseAdapter._emit_alert` (kinds `subscribe` / `resub` / `gift`, `source:"platform"`): Twitch `USERNOTICE`, YouTube membership items (InnerTube) and membership event types (official API), Kick `SubscriptionEvent` / `GiftedSubscriptionsEvent`. One alert per gift bomb (Twitch per-recipient `subgift` with `msg-param-community-gift-id`, YouTube gift redemptions skipped); Kick drops the duplicate from its second chatroom channel. Tests: `tests/test_sub_alerts.py`.
- [ ] Raids, cheers, hosts and Kicks: Twitch `USERNOTICE msg-id=raid` (viewer count) and the `bits` tag on chat (paid chat, so the Bits alert); Kick `StreamHostEvent` (raid when it brings viewers, else host) and `KicksGifted` (donation in KICKs) on the `channel_<id>` Pusher channel (id from `kick.channel_id` or the viewer-count lookup). The first payload of each Kick event is logged at INFO since the fields are undocumented. Tests: `tests/test_platform_events.py`.
- [ ] Chat payloads carry `is_paid` / `paid_amount` / `paid_currency` and `highlight` (Twitch `msg-id` `highlighted-message` / `gigantified-emote-message` / `animated-message` → `"highlighted"` / `"gigantified"` / `"animated"`, else null). The overlay's `.paid` / `.highlighted` classes and Stream Rooms' bubble tints read them. Tests: `tests/test_chat_highlights.py`.
- [ ] YouTube InnerTube: unknown actions / items / renderer fields are logged once and sampled to `data/youtube_new_fields.jsonl` (capped at 200 lines, `adapters/youtube_capture.py`). It must never stop a message from being emitted. Tests never write to the real file.
- [ ] YouTube replies to Super Chats: `reply_to` from the reply chip (`beforeContentButtons`, panel tag `PAreply_thread`), matched to the Super Chat by the reply-thread id in its `replyButton` (last 300 kept); unknown chip icons are noted as `chip:<icon>`. Tests: `tests/test_youtube_replies.py`.
- [ ] Platform settings (Kick / Twitch / YouTube) hot-apply: admin Config save and hand edits to `config.yaml` (`core.watch_config`) reconnect only the changed platforms via `StreamCore.apply_platforms`. Status tab has a per-platform Reconnect. Game toggles and the port still need a restart. Tests: `tests/test_platform_reload.py`.

## Drop risks

- Adding a fourth platform by stuffing logic into `kick.py` instead of a new adapter.
- Flipping a platform default to `true` in DEFAULTS or example config.
- Chat overlay losing multi-platform filters when the WS payload shape changes.
- Downloading pictures per message instead of once per chatter, or fetching links that aren't https / public (the store refuses them).
- Kick avatar lookups without the cache / 403 back-off (one request per message would get the IP blocked by Cloudflare).
- Alerting once per gift-bomb recipient (Twitch `subgift` with a community gift id, YouTube redemptions) instead of once per bomb.
- Dropping `emotes` from the chat payload or `ChatEvent` (overlay and Stream Rooms fall back to plain text silently).

## After-change verify

- [ ] Example config still has all three platforms `enabled: false`.
- [ ] Admin → Status still lists each adapter separately.
- [ ] Admin → Sources still links `/overlay/chat.html`.
- [ ] Chat overlay still works with no platform query (all enabled platforms) and with a filter.
