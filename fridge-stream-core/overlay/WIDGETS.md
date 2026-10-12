# Chat widgets (StreamElements / Streamlabs code widgets)

Some chat looks are more than CSS: the widget brings its own HTML, CSS, JavaScript and a
settings list ("fields"), and its script builds every line itself. Those are often sold on
Etsy or Ko-fi as a zip made for StreamElements (or as code boxes to paste into Streamlabs).
Core runs them with chat from Kick, Twitch and YouTube.

Plain CSS templates don't need this: paste them into **Chat overlay → Custom CSS** (see
[CHAT.md](CHAT.md)).

## Using one

1. Dashboard → **Overlays → Chat widgets** → pick the zip → **Import zip**.
   (Or open **Or paste the code boxes** and paste HTML, CSS, JS and the fields JSON.)
2. **Settings & preview**: change colours, fonts and switches, **Save settings**. The preview
   shows made-up chatters until real chat arrives. The widget's own buttons (its test messages)
   are there too.
3. **Copy OBS address** → OBS → add a **Browser** source → paste the URL. Transparent.

`http://127.0.0.1:3850/overlay/widget.html?name=<widget>`

| Switch | What it does |
|--------|--------------|
| `name` | Which widget (required) |
| `platforms=kick,twitch` (or `platform=`) | Only these platforms |
| `alerts=0` | Chat only (no follows, subs, tips, cheers, raids) |
| `hide=<seconds>` | Streamlabs chat boxes: lines leave after that (StreamElements widgets have their own setting) |
| `history=1` | Start with the last few messages |
| `preview=1` | Made-up chatters while chat is quiet |
| `hint=0` / `hint=1` | The corner line outside OBS |

All of them are in **Sources & overlays → Customise** as well.

## What the widget gets

**StreamElements** (`window` events, as on StreamElements):

- `onWidgetLoad`: `fieldData` (the settings), `channel.username` (your Twitch channel, else Kick),
  `currency` (`overlay.widget_currency` in config, default USD), `session.data` (latest / recent
  follower, sub, tip, cheer, raid since Core started), `overlay.isEditorMode: false`.
- `onEventReceived`: `message` (with `data.tags`, `badges`, `emotes`, `renderedText`, `msgId`,
  `userId`), `delete-message`, `delete-messages`, `follower-latest`, `subscriber-latest` (subs,
  resubs, gifts; YouTube memberships too), `tip-latest` (Super Chats, Super Stickers, donations,
  YouTube gifts, charity), `cheer-latest` (bits, power-ups, KICKs), `raid-latest`, `host-latest`,
  `widget-button` (the buttons on the dashboard), `kvstore:update`.
- `onSessionUpdate` after each alert.
- `SE_API`: `store.get/set` (kept in the page's own storage, shared by every widget like on
  StreamElements), `counters.get` (always 0), `sanitize`, `cheerFilter`, `getOverlayStatus`,
  `resumeQueue`, `setField` (do nothing).
- jQuery 3.7.1 is loaded first (`overlay/vendor/`), as on StreamElements, and `animate-lite.css`.

**Streamlabs** (`document` events):

- `onLoad` with the settings.
- The chat box: each message fills the widget's `<script type="text/template" id="chatlist_item">`
  (`{from}`, `{message}`, `{color}`, `{messageId}`, `{badges}`, plus `{platform}`, `{userId}`,
  `{avatar}`) into `#log`, then `onEventReceived` fires with `{command: "PRIVMSG", from, body,
  tags, messageId, platform, emotes}`. Deleted lines leave `#log` and fire `CLEARMSG`.
- Alerts arrive as Streamlabs' socket events: `{type: "follow" | "subscription" | "resub" |
  "donation" | "bits" | "raid" | "host" | "superchat", for, message: [{name, amount, ...}]}`.

Settings are filled into the code the way each platform does it: `{{key}}` and `{key}` on
StreamElements, `{{key}}` on Streamlabs. Streamlabs' chat settings (`{font_size}`,
`{text_color}`, `{message_hide_delay}` …) get Core's values, as for CSS templates.

## Kick and YouTube

Widgets are written for Twitch. Kick and YouTube lines arrive dressed as Twitch ones:
`service` says the real platform, Kick's `[emote:id:name]` becomes the emote name with an
`emotes` entry, YouTube members and Kick subscribers get the subscriber badge, owners the
broadcaster badge. Badge pictures are Twitch's own, or yours from **Chat overlay → Pictures**
(badge-broadcaster, badge-mod, badge-vip, badge-sub, badge-founder). Sub tiers are always tier 1;
a gifted sub reads "<gifter> gifted N subs" (Core doesn't know who got single gifts).

Most widgets find emotes by splitting the text on spaces, as Twitch always puts spaces around them.
YouTube and Kick emotes can touch (`:_heart::_heart:`), so StreamElements widgets get a space on each
side of every emote (`text`, `emotes` start/end and `renderedText` all match). `emotes[].animated`
and `gif` are true when Core knows the emote moves.

## Safety

The widget's code is someone else's (often scrambled so it can't be read). It runs in
`/widget-frame/<name>`, served with `Content-Security-Policy: sandbox allow-scripts` inside an
`<iframe sandbox="allow-scripts">`, so it gets a blank origin: it can't read the dashboard's
sign-in, call the admin API, open `/ws` or post to Core. Everything reaches it from
`widget.html` by `postMessage`. It can still load pictures and fonts from the internet (Google
Fonts, the seller's pictures), like on StreamElements.

Things that follow from that: a widget that saves to `localStorage` gets a memory copy that's
gone on reload (use `SE_API.store`); fonts from `/media/` can't be used inside a widget (the
blank origin can't load them), pictures from `/media/` can.

## Where things live

`core/widget_store.py` (import, settings, the frame), `data/widgets/<name>/` (html.txt, css.txt,
js.txt, fields.json, data.json, widget.json), `overlay/widget.html` + `widget.js` (the page OBS
shows), `overlay/widget-bridge.js` (Core packets → platform events), `overlay/widget-frame.js`
(inside the frame: the events, SE_API, the Streamlabs chat box). Tests `tests/test_widgets.py`.
Checklist [checklists/widgets.md](../../checklists/widgets.md).
