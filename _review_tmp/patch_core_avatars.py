"""Stream Core: chatter profile pictures for Kick + YouTube. Run from the FlaVR_leftovers root."""
import sys, pathlib
ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
C = ROOT / "fridge-stream-core"

def edit(rel, pairs, base=C):
    p = base / rel
    s = p.read_text(encoding="utf-8")
    for o, n in pairs:
        if s.count(o) != 1:
            raise SystemExit(f"{rel}: anchor found {s.count(o)}x: {o[:70]!r}")
        s = s.replace(o, n)
    p.write_text(s, encoding="utf-8", newline="")
    print("patched", rel)

edit("core/event_bus.py", [
('''AlertHandler = Callable[[dict], Awaitable[None]]
''', '''AlertHandler = Callable[[dict], Awaitable[None]]
UserUpdateHandler = Callable[[dict], Awaitable[None]]
'''),
('''        self._alert_handlers: List[AlertHandler] = []
''', '''        self._alert_handlers: List[AlertHandler] = []
        self._user_update_handlers: List[UserUpdateHandler] = []
'''),
('''    async def publish_chat(self, event: ChatEvent) -> None:''', '''    def on_user_update(self, handler: UserUpdateHandler) -> None:
        """Late user info (e.g. a Kick profile picture looked up after the first message)."""
        self._user_update_handlers.append(handler)

    async def publish_user_update(self, payload: dict[str, Any]) -> None:
        for h in list(self._user_update_handlers):
            try:
                await h(payload)
            except Exception:
                log.exception("user_update handler error")

    async def publish_chat(self, event: ChatEvent) -> None:'''),
])

edit("main.py", [
('''                    "color": event.user.color,
                    "is_mod": event.user.is_mod,''', '''                    "color": event.user.color,
                    "profile_image_url": event.user.profile_image_url,
                    "is_mod": event.user.is_mod,'''),
('''        self.bus.on_alert(self._on_alert)
''', '''        self.bus.on_alert(self._on_alert)

        # Late user info (Kick profile pictures) → overlays + recent chat history
        self.bus.on_user_update(self._on_user_update)
'''),
('''    async def _on_alert(self, payload: dict) -> None:''', '''    async def _on_user_update(self, payload: dict) -> None:
        """{"platform", "id", "username", "profile_image_url"} → WS ``type:user_update``."""
        plat = payload.get("platform")
        uid = str(payload.get("id") or "")
        for item in self.recent_chat:
            user = item.get("user") or {}
            if item.get("platform") == plat and str(user.get("id") or "") == uid:
                user["profile_image_url"] = payload.get("profile_image_url")
        if self.state.ws_manager:
            try:
                await self.state.ws_manager.broadcast({"type": "user_update", "data": payload})
            except Exception:
                log.exception("user_update WS broadcast failed")

    async def _on_alert(self, payload: dict) -> None:'''),
])

edit("adapters/kick.py", [
('''from adapters.base import BaseAdapter
''', '''from adapters.base import BaseAdapter
from adapters.kick_avatars import KickAvatars
'''),
('''        self._stop_event = asyncio.Event()
''', '''        self._stop_event = asyncio.Event()
        # Chatter profile pictures (looked up once per chatter, cached in data/)
        self.avatars = KickAvatars(bool(kick_cfg.get("avatars", True)))
'''),
('''                except asyncio.CancelledError:
                    pass
        log.info("Kick adapter stopped")''', '''                except asyncio.CancelledError:
                    pass
        self.avatars.stop()
        log.info("Kick adapter stopped")'''),
('''            badges=badges,
            color=identity.get("color"),
        )

        event = ChatEvent(
            platform=Platform.KICK,''', '''            badges=badges,
            color=identity.get("color"),
        )
        slug = str(sender.get("slug") or username)
        pic = sender.get("profile_pic") or self.avatars.get(slug)
        if pic:
            user.profile_image_url = str(pic)
        elif pic is None:
            uid, uname = user.id, user.username

            async def _found(url: str) -> None:
                await self.bus.publish_user_update(
                    {"platform": "kick", "id": uid, "username": uname, "profile_image_url": url}
                )

            self.avatars.request(slug, _found)

        event = ChatEvent(
            platform=Platform.KICK,'''),
])

edit("adapters/youtube.py", [
('''from adapters.base import BaseAdapter
''', '''from adapters.base import BaseAdapter
from adapters.youtube_avatar import best_photo
'''),
('''            is_mod=bool(author.get("isChatModerator") or author.get("isChatOwner")),
            is_vip=bool(author.get("isChatSponsor")),
            is_subscriber=bool(author.get("isChatSponsor")),
        )''', '''            is_mod=bool(author.get("isChatModerator") or author.get("isChatOwner")),
            is_vip=bool(author.get("isChatSponsor")),
            is_subscriber=bool(author.get("isChatSponsor")),
            profile_image_url=best_photo(author.get("profileImageUrl") or "") or None,
        )'''),
('''            is_vip=is_member,
            is_subscriber=is_member,
            badges=badges,
        )''', '''            is_vip=is_member,
            is_subscriber=is_member,
            badges=badges,
            profile_image_url=best_photo(renderer.get("authorPhoto") or {}) or None,
        )'''),
])

edit("core/config.py", [('''        "channel_slug": "YOUR_KICK_CHANNEL",
        "poll_viewer_interval_sec": 15,
    },''', '''        "channel_slug": "YOUR_KICK_CHANNEL",
        "poll_viewer_interval_sec": 15,
        # look up each chatter's profile picture once (cached in data/kick_avatars.json)
        "avatars": True,
    },''')])

edit("config/config.example.yaml", [('''  # chatroom_id: 12345678
  poll_viewer_interval_sec: 15
''', '''  # chatroom_id: 12345678
  poll_viewer_interval_sec: 15
  avatars: true                    # chatter profile pictures (one lookup per chatter, cached)
''')])

edit("admin/index.html", [('''          <input id="cfg-kick-poll" type="number" min="5" max="300" />
        </label>
''', '''          <input id="cfg-kick-poll" type="number" min="5" max="300" />
        </label>
        <label class="check"><input id="cfg-kick-avatars" type="checkbox" /> Chatter profile pictures</label>
''')])

edit("admin/admin.js", [
('''    $("cfg-kick-poll").value = k.poll_viewer_interval_sec ?? 15;
''', '''    $("cfg-kick-poll").value = k.poll_viewer_interval_sec ?? 15;
    $("cfg-kick-avatars").checked = k.avatars !== false;
'''),
('''      poll_viewer_interval_sec: num($("cfg-kick-poll").value, 15),
    };''', '''      poll_viewer_interval_sec: num($("cfg-kick-poll").value, 15),
      avatars: $("cfg-kick-avatars").checked,
    };'''),
])

edit("CHANGELOG.md", [('''### Added

- **Twitch emotes in the chat payload**''', '''### Added

- **Chatter profile pictures** in the chat payload (`user.profile_image_url`) for **YouTube** (from the chat item's author photo, asked at 128 px; `adapters/youtube_avatar.py`) and **Kick** (Kick doesn't send them with chat, so each new chatter's channel is looked up once — `/api/v2/channels/{slug}` → `user.profile_pic` — and cached in `data/kick_avatars.json`, re-checked weekly; 403/429 back off 10 min; `adapters/kick_avatars.py`, toggle `kick.avatars`, default on, Admin → Config → Kick). A Kick chatter's first message goes out immediately; when the lookup lands Core broadcasts `{"type":"user_update","data":{platform, id, username, profile_image_url}}` and patches recent chat history. New EventBus hook `on_user_update` / `publish_user_update`. Twitch pictures are not included yet (anonymous IRC has none; needs Helix or a lookup service). Tests: `tests/test_chat_avatars.py`.
- **Twitch emotes in the chat payload**''')])

edit("checklists/adapters-chat.md", [
('''- [ ] Kick emote tokens `[emote:id:name]` resolve to `files.kick.com`.
''', '''- [ ] Kick emote tokens `[emote:id:name]` resolve to `files.kick.com`.
- [ ] Chat payload `user.profile_image_url`: YouTube from the author photo; Kick from a one-time channel lookup cached in `data/kick_avatars.json` (`kick.avatars`, default on), followed by a `type:user_update` broadcast. Twitch: none yet.
'''),
('''- Dropping `emotes` from the chat payload or `ChatEvent`''', '''- Kick avatar lookups without the cache / 403 back-off (one request per message would get the IP blocked by Cloudflare).
- Dropping `emotes` from the chat payload or `ChatEvent`'''),
], base=ROOT)

edit("README.md", [('''| **Twitch** | `twitch.enabled`, `channel`, `third_party_emotes` |''', '''| **Kick pictures** | `kick.avatars` | Chatter profile pictures, looked up once per chatter and cached (`data/kick_avatars.json`). YouTube pictures come with chat; Twitch none yet |
| **Twitch** | `twitch.enabled`, `channel`, `third_party_emotes` |''')])
print("done")
