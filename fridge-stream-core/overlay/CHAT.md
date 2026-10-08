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

## Markup and selectors

```html
<div id="chat-root" class="widget-ChatBox">
  <div id="log" class="sl__chat__layout">
    <div class="msg message-row" data-from="login" data-sender="login" data-id="…" data-platform="twitch" data-user-id="…">
      <div class="reply">↩ Replying to Name: what they said</div>   <!-- only on replies -->
      <img class="avatar" src="…">                                   <!-- only with chatter pictures on -->
      <span class="meta" style="color: #bf94ff">
        <span class="plat plat-twitch">T</span>
        <span class="badges"><span class="badge mod">Mod</span></span> <!-- <img class="badge mod"> with a picture -->
        <span class="name">Name</span>
        <span class="colon">:</span>
      </span>
      <span class="message text">hello <img class="emote" src="…"></span>
    </div>
  </div>
</div>
```

```
#log                      the list (Streamlabs / StreamElements id)
#log > div, .msg          one message; .paid on Super Chats / Kicks, .system on Core's own lines
[data-from="login"]       who sent it; [data-platform="kick|twitch|youtube"]
.meta                     badges + name (the chatter's colour is an inline style here, like Streamlabs)
.badges .badge            badge chips; .badge.mod .vip .sub .broadcaster .og .founder
.name                     the chatter's name          .colon   the ":" after it
.message                  the text                    .emote   emote pictures
.plat                     the K / T / Y letter        .reply   "Replying to …" line
.avatar                   chatter picture
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

Upload in **Admin → Chat overlay → Pictures and sounds**, or drop files in `overlay/assets/chat/`:

| File | What it does |
|------|--------------|
| `background.png` / `.jpg` / `.webp` / `.gif` | Picture behind the chat (stretched to cover) |
| `badge-mod.png`, `badge-vip.png`, `badge-sub.png`, `badge-broadcaster.png`, `badge-og.png`, `badge-founder.png` | Picture badges instead of the text chips |
| `message.mp3` / `.ogg` / `.wav` | Played for each new message (volume and a minimum gap are in the dashboard) |
| `paid.mp3` | Played for Super Chats and Kicks instead of the message sound |

Sounds play inside OBS / XSplit without a click. A normal browser tab needs one click on the page first (browser rule).

## Settings (dashboard, URL parameter overrides)

| Setting | URL | What it does |
|---------|-----|--------------|
| Hide messages after | `?hide=12` | Seconds until a message fades out; 0 keeps them |
| Messages kept | — | How many rows stay on screen |
| Newest on top | `?top=1` | Flip the direction |
| Chatter pictures | `?avatars=1` | Show profile pictures (Kick, Twitch with Connect Twitch, YouTube) |
| Sounds | `?sound=0` | Mute this one browser source |
