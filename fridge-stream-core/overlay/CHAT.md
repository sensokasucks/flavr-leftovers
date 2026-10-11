# Chat overlay

Webpage source: `/overlay/chat.html` (transparent). Filters: `?platform=twitch`, `?platforms=kick,twitch`, `?badges=0` (no K / T / Y letters). Preview with made-up chatters when there is no chat yet: `?preview=1`.

The HTML follows the **Streamlabs Chat Box** layout (the one most chat CSS packs and tutorials are written for), with StreamElements' names added, so CSS you already have can move here with little or no rewriting.

## Skins

| Skin | What it is |
|------|------------|
| `classic` | Stream Core's look: dark fade at the bottom, text shadow, coloured badge chips |
| `plain` | The neutral base chat packs expect: no fade, no shadow, one line per message |
| `custom` | Chrome reset — your CSS is the whole look |

Set the skin in **Admin → Chat overlay**, or `?skin=classic|plain|custom` on the URL.

## Paste your CSS

1. Open **Admin → Chat overlay**.
2. Paste into **Custom CSS** (Streamlabs Chat Box CSS, StreamElements chat CSS, OBS Custom CSS, Nerd Or Die packs...).
3. Save. The overlay reloads the file live — no Core restart.
4. If the pack still fights the default look, switch the skin to **Plain** or **Custom CSS only**.

The same rules can go into OBS **Custom CSS** on the browser source instead.

## Free chat templates (keep your layout)

Free chat templates come in three families, and the overlay carries all three sets of names on
the same elements, so one row matches whichever template you paste:

| Family | Add to the overlay address | Tested with |
|--------|----------------------------|-------------|
| Streamlabs Chat Box CSS | `?template=streamlabs` | the default Streamlabs template, nnja 8-bit, nico scroll, maylogger bubbles |
| StreamElements chat CSS | `?template=streamelements` | StreamElements' own custom chat, danirabbit cards, m1s1da bubbles, a JRPG dialog box |
| jChat / Chat Is This CSS | `?template=jchat` | jChat v2 with its size / font / stroke / shadow files, Johnnycyan's ChatIS CSS, an SMS-bubble fork |

`?template=` starts from **Custom CSS only**, leaves out the K / T / Y letters, chatter pictures and
word badges (templates expect badge pictures), and puts a reply's "Replying to …" inside the
message so table and flex layouts keep their columns. `?badges=1` / `?avatars=1` bring those back.
StreamElements rows also get `animated fadeInUp` (`?in=bounceIn` picks another animate.css name).

**Settings in the template.** Templates carry the widget's settings as placeholders:
`{font_size}`, `{text_color}`, `{message_hide_delay}` (Streamlabs) or `{{fontSize}}`, `{{fontName}}`,
`{{emoteSize}}` (StreamElements). When you save, Core fills the common ones with its own values
(`--chat-size`, `--chat-text`, `--chat-emote-size`, Roboto, "Hide messages after" for the delay)
and says how many it filled. Change those values with the CSS variables below, or edit the saved
CSS. A placeholder Core doesn't know stays as it is and the browser skips just that line.

**Animations.** Templates name animate.css animations (`fadeInRight`, `flipInX`, `fadeOut` …)
without loading animate.css. The overlay loads `animate-lite.css`, which has those keyframes.

**What doesn't come across.** Templates that ship their own HTML or JavaScript (StreamElements
"custom widgets", maylogger's sliding bubbles script) only bring their CSS. jChat's own URL
options (`?fade=`, `?size=`) are Core's `?hide=` and the CSS variables instead.

**One look per OBS source.** Save a template as its own stylesheet (Chat overlay → Custom CSS →
Stylesheet → Add stylesheet), then put `?css=<name>` on that source's address. Each source can
use a different template.

## Deleted messages

When a mod deletes a message, times out or bans a chatter, or clears chat (Twitch CLEARMSG /
CLEARCHAT, Kick message deleted / user banned / chat cleared, YouTube deleted messages), Core sends
`{"type": "chat_removed", "data": {platform, message_id, user_id, username, all}}`. The overlay
gives the matching rows `.deleted` (what Streamlabs templates style) and removes them a moment
later. Core also drops them from the catch-up history a reconnecting overlay gets.

## Markup and selectors

```html
<div id="chat-root" class="widget-ChatBox">
  <div id="chat_container">                                         <!-- jChat's wrapper -->
  <div id="log" class="sl__chat__layout">
    <div class="msg message-row chat_line" data-from="login" data-sender="login" data-nick="login"
         data-id="…" data-msgid="…" data-time="…" data-platform="twitch" data-user-id="…">
      <div class="reply">↩ Replying to Name: what they said</div>   <!-- only on replies -->
      <img class="avatar" src="…">                                   <!-- only with chatter pictures on -->
      <span class="meta user-box user_info" style="color: #bf94ff">
        <span class="plat plat-twitch">T</span>
        <span class="badges"><span class="badge mod moderator-icon">Mod</span></span> <!-- <img class="badge mod moderator-icon"> with a picture -->
        <span class="name user user-name nick">Name</span>
        <span class="colon">:</span>
      </span>
      <span class="message text user-message">hello <img class="emote" src="…"></span>
    </div>
  </div>
  </div>
</div>
```

```
#log                      the list (Streamlabs / StreamElements id)
#log > div, .msg          one message; .paid on Super Chats / Kicks / Bits, .system on Core's own lines
                          .highlighted / .gigantified / .animated on Twitch channel-point messages
[data-from="login"]       who sent it; [data-platform="kick|twitch|youtube"]
.meta                     badges + name (the chatter's colour is an inline style here, like Streamlabs)
.badges .badge            badge chips; .badge.mod .vip .sub .broadcaster .og .founder
.name                     the chatter's name          .colon   the ":" after it
.message                  the text                    .emote   emote pictures
.emote.sticker / .emote.gift   a YouTube Super Sticker / Jewels gift picture (drawn 2.5 × an emote)
.plat                     the K / T / Y letter        .reply   "Replying to …" line
.avatar                   chatter picture
.deleted                  a row a mod just removed (it leaves 0.45 s later)

StreamElements names: .message-row  .user-box  .user-name  .user-message  [data-msgid]
jChat names:          #chat_container  .chat_line  .user_info  .nick  .colon  .message  [data-nick]
Badge icon classes:   .broadcaster-icon  .moderator-icon  .vip-icon  .subscriber-icon
```

Chatter pictures come from Core itself (`/avatars/<platform>/<file>`, saved once per chatter) as soon as Core has a copy, and from the platform's own link until then. Names on **Never show a picture for** (Settings → Core + chat platforms) never get one, and lose it at once when added.

## CSS variables

```css
:root {
  --chat-font: "Segoe UI", system-ui, sans-serif;
  --chat-size: 16px;
  --chat-text: #f5f7fa;
  --chat-name-weight: 700;
  --chat-emote-size: 28px;
  --chat-gap: 4px;
  --chat-bg: linear-gradient(...);   /* the fade; set to none for no background */
  --chat-badge-size: 16px;
  --chat-avatar-size: 26px;
}
```

## Pictures and sounds

Pick them in **Admin → Chat overlay → Pictures and sounds** from **Stored files** (`data/media/`, the same files the
alerts use), or upload a new one there. Dropping files into `overlay/assets/chat/` still works for a slot with nothing
picked (Core copies them into Stored files at start):

| File | What it does |
|------|--------------|
| `background.png` / `.jpg` / `.webp` / `.gif` | Picture behind the chat (stretched to cover) |
| `badge-mod.png`, `badge-vip.png`, `badge-sub.png`, `badge-broadcaster.png`, `badge-og.png`, `badge-founder.png` | Picture badges instead of the text chips |
| `message.mp3` / `.ogg` / `.wav` | Played for each new message (volume and a minimum gap are in the dashboard) |
| `paid.mp3` | Played for Super Chats and Kicks instead of the message sound |

Custom CSS can use any stored picture or font by name, e.g. `url(/media/my-frame)` (**Copy CSS** on the Stored files page).

Sounds play inside OBS / XSplit without a click. A normal browser tab needs one click on the page first (browser rule).

## Settings (dashboard, URL parameter overrides)

| Setting | URL | What it does |
|---------|-----|--------------|
| Hide messages after | `?hide=12` | Seconds until a message fades out; 0 keeps them |
| Messages kept | — | How many rows stay on screen |
| Newest on top | `?top=1` | Flip the direction |
| Chatter pictures | `?avatars=1` | Show profile pictures (Kick, Twitch with Connect Twitch, YouTube) |
| Sounds | `?sound=0` | Mute this one browser source |
| Template | `?template=streamlabs` | `streamlabs`, `streamelements` or `jchat` (see above) |
| Saved stylesheet | `?css=twitch` | Use the stylesheet saved as "twitch" instead of the main one |

## Red-flagged chatters

Someone red-flagged on the dashboard (**Chat history → 🚩 Red flags**) never reaches this overlay: Core doesn't send their chat. When a person is flagged, Core sends `{"type": "chat_user_hidden", "data": {platform, id, username, display_name}}` once and the overlay removes that person's rows already on screen (`platform` `""` = a name flagged on every platform). Another overlay that keeps chat rows should do the same.
