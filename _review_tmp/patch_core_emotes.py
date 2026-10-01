"""Stream Core: Twitch emote ranges (native + BTTV/FFZ/7TV). Run from the FlaVR_leftovers root."""
import sys, pathlib
ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
C = ROOT / "fridge-stream-core"

def edit(rel, pairs, base=C):
    p = base / rel
    s = p.read_text(encoding="utf-8")
    for o, n in pairs:
        if s.count(o) != 1:
            raise SystemExit(f"{rel}: anchor found {s.count(o)}x: {o[:60]!r}")
        s = s.replace(o, n)
    p.write_text(s, encoding="utf-8", newline="")
    print("patched", rel)

nl = "\r\n" if b"\r\n" in (C / "adapters/twitch.py").read_bytes() else "\n"
def N(t): return t.replace("\n", nl)

edit("core/models.py", [(N('''    reward_id: Optional[str] = None      # platform-specific reward/redemption id
    reward_title: Optional[str] = None
'''), N('''    reward_id: Optional[str] = None      # platform-specific reward/redemption id
    reward_title: Optional[str] = None

    # Emote ranges in `message` (Twitch native + BTTV/FFZ/7TV), see adapters/twitch_emotes.py.
    # Kick keeps its inline [emote:id:name] tokens instead.
    emotes: list[dict] = field(default_factory=list)
'''))])

edit("adapters/twitch.py", [
(N('''from adapters.base import BaseAdapter
'''), N('''from adapters.base import BaseAdapter
from adapters.twitch_emotes import ThirdPartyEmotes, parse_twitch_emotes, strip_action
''')),
(N('''PRIVMSG_RE = re.compile(
    r"^(?:@(?P<tags>[^ ]+) )?:(?P<nick>[^!]+)![^ ]+ PRIVMSG #(?P<chan>[^ ]+) :(?P<msg>.*)$"
)
'''), N('''PRIVMSG_RE = re.compile(
    r"^(?:@(?P<tags>[^ ]+) )?:(?P<nick>[^!]+)![^ ]+ PRIVMSG #(?P<chan>[^ ]+) :(?P<msg>.*)$"
)
ROOMSTATE_RE = re.compile(r"^@(?P<tags>[^ ]+) :tmi\\.twitch\\.tv ROOMSTATE #")
''')),
(N('''        self._writer: Optional[asyncio.StreamWriter] = None
'''), N('''        self._writer: Optional[asyncio.StreamWriter] = None
        # BTTV / FFZ / 7TV emotes, loaded once the channel's room-id is known
        self.emotes3p = ThirdPartyEmotes(bool(cfg.get("third_party_emotes", True)))
''')),
(N('''        self._running = False
        self._stop.set()
        if self._writer:'''), N('''        self._running = False
        self._stop.set()
        self.emotes3p.stop()
        if self._writer:''')),
(N('''        m = PRIVMSG_RE.match(line)
        if not m:
            return
        tags = _parse_tags(m.group("tags") or "")
        nick = m.group("nick")
        msg = m.group("msg") or ""
'''), N('''        rs = ROOMSTATE_RE.match(line)
        if rs:
            self.emotes3p.set_room(_parse_tags(rs.group("tags")).get("room-id", ""))
            return
        m = PRIVMSG_RE.match(line)
        if not m:
            return
        tags = _parse_tags(m.group("tags") or "")
        nick = m.group("nick")
        msg = strip_action(m.group("msg") or "")
        self.emotes3p.set_room(tags.get("room-id", ""))
        emotes = parse_twitch_emotes(tags.get("emotes", ""), msg)
        emotes = sorted(emotes + self.emotes3p.match(msg, emotes), key=lambda e: e["start"])
''')),
(N('''                message_id=tags.get("id"),
            )
        )'''), N('''                message_id=tags.get("id"),
                emotes=emotes,
            )
        )''')),
])

edit("main.py", [(N('''                "message": event.message,
                "timestamp": event.timestamp,
                "user": {
                    "id": event.user.id,'''), N('''                "message": event.message,
                "timestamp": event.timestamp,
                # emote ranges (Twitch native + BTTV/FFZ/7TV); Kick uses inline tokens
                "emotes": list(event.emotes or []),
                "user": {
                    "id": event.user.id,'''))])

edit("core/config.py", [(N('''    "twitch": {
        "enabled": False,  # opt-in chat platform
        "channel": "YOUR_TWITCH_CHANNEL",
    },'''), N('''    "twitch": {
        "enabled": False,  # opt-in chat platform
        "channel": "YOUR_TWITCH_CHANNEL",
        # BetterTTV / FrankerFaceZ / 7TV emotes in the chat payload + chat overlay
        "third_party_emotes": True,
    },'''))])

edit("config/config.example.yaml", [(N('''  channel: "YOUR_TWITCH_CHANNEL"   # twitch.tv/THIS_PART (no #)
  # Read-only via anonymous IRC — no OAuth needed to listen.
'''), N('''  channel: "YOUR_TWITCH_CHANNEL"   # twitch.tv/THIS_PART (no #)
  # Read-only via anonymous IRC — no OAuth needed to listen.
  third_party_emotes: true        # BetterTTV / FrankerFaceZ / 7TV emotes (public APIs, no keys)
'''))])

edit("admin/index.html", [(N('''          <input id="cfg-tw-channel" type="text" placeholder="twitch.tv/THIS_PART" />
        </label>
'''), N('''          <input id="cfg-tw-channel" type="text" placeholder="twitch.tv/THIS_PART" />
        </label>
        <label class="check"><input id="cfg-tw-3p" type="checkbox" /> BetterTTV / FrankerFaceZ / 7TV emotes</label>
'''))])

edit("admin/admin.js", [
(N('''    $("cfg-tw-channel").value = tw.channel ?? "";
'''), N('''    $("cfg-tw-channel").value = tw.channel ?? "";
    $("cfg-tw-3p").checked = tw.third_party_emotes !== false;
''')),
(N('''        channel: $("cfg-tw-channel").value.trim().replace(/^#/, ""),
      },'''), N('''        channel: $("cfg-tw-channel").value.trim().replace(/^#/, ""),
        third_party_emotes: $("cfg-tw-3p").checked,
      },''')),
])

edit("overlay/chat.js", [
(N('''  function renderMessageHtml(raw) {
    const parts = [];'''), N('''  // Twitch (native + BetterTTV / FrankerFaceZ / 7TV): Core sends emote ranges.
  // start/end are inclusive code-point indices, so split with Array.from.
  function renderRangesHtml(raw, emotes) {
    const chars = Array.from(raw);
    const list = emotes
      .filter((e) => Number.isInteger(e.start) && Number.isInteger(e.end) && e.url)
      .sort((a, b) => a.start - b.start);
    const parts = [];
    let pos = 0;
    for (const e of list) {
      if (e.start < pos || e.end >= chars.length) continue;
      if (e.start > pos) parts.push(escapeHtml(chars.slice(pos, e.start).join("")));
      const name = escapeHtml(e.name || chars.slice(e.start, e.end + 1).join(""));
      parts.push(
        `<img class="emote" src="${escapeHtml(e.url)}" alt="${name}" title="${name}" loading="lazy" />`
      );
      pos = e.end + 1;
    }
    if (pos < chars.length) parts.push(escapeHtml(chars.slice(pos).join("")));
    return parts.join("");
  }

  function renderMessageHtml(raw, emotes) {
    if (Array.isArray(emotes) && emotes.length) return renderRangesHtml(raw, emotes);
    const parts = [];''')),
(N('''    const textHtml = renderMessageHtml(data.message);'''), N('''    const textHtml = renderMessageHtml(data.message, data.emotes);''')),
])

edit("CHANGELOG.md", [(N('''### Added

- Workshop **feature checklists**'''), N('''### Added

- **Twitch emotes in the chat payload**: `type:chat` now carries `emotes` — ranges into `message` (`start`/`end`, inclusive code points) with `provider`, `id`, `name`, `url`, `static_url`, `animated`. Native Twitch emotes come from the IRC `emotes` tag; **BetterTTV / FrankerFaceZ / 7TV** global + channel emotes (looked up by the channel's `room-id`, refreshed every 30 min, public APIs, no keys) are matched as whole words. Toggle `twitch.third_party_emotes` (default on; Admin → Config → Twitch). The chat overlay renders them; Kick keeps its inline `[emote:id:name]` tokens. `/me` messages no longer show the raw `ACTION` wrapper. New module `adapters/twitch_emotes.py`, tests in `tests/test_twitch_emotes.py`.
- Workshop **feature checklists**'''))])

edit("checklists/adapters-chat.md", [
(N('''- [ ] Kick emote tokens `[emote:id:name]` resolve to `files.kick.com`.
'''), N('''- [ ] Kick emote tokens `[emote:id:name]` resolve to `files.kick.com`.
- [ ] Twitch `type:chat` payloads carry `emotes` ranges (native IRC `emotes` tag + BetterTTV / FrankerFaceZ / 7TV via `adapters/twitch_emotes.py`, toggle `twitch.third_party_emotes`, default on). `start`/`end` are inclusive code points; the chat overlay renders them with `Array.from`. External readers (Stream Rooms audience) rely on this field.
''')),
(N('''- Chat overlay losing multi-platform filters when the WS payload shape changes.
'''), N('''- Chat overlay losing multi-platform filters when the WS payload shape changes.
- Dropping `emotes` from the chat payload or `ChatEvent` (overlay and Stream Rooms fall back to plain text silently).
''')),
], base=ROOT)

edit("README.md", [(N('''| **Twitch** | `twitch.enabled`, `channel` | Anonymous IRC (no OAuth to listen) |'''),
 N('''| **Twitch** | `twitch.enabled`, `channel`, `third_party_emotes` | Anonymous IRC (no OAuth to listen). Emotes (native + BetterTTV / FrankerFaceZ / 7TV) ride along in the chat payload |'''))])
print("done")
