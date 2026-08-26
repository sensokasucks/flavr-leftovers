# Stream alerts overlay

Webpage source: `/overlay/alerts.html`  
Admin test tab fires the same overlay. Preview: `/overlay/alerts.html?preview=1`

The HTML uses **Streamlabs Alert Box** ids and **StreamElements AlertBox** classes so CSS you already wrote (or bought as a pack) can move here with little or no rewriting.

## Skins

| Skin | What it is |
|------|------------|
| `classic` | Default streamer look: Montserrat, big shadowed name, accent colour, optional GIF |
| `card` | Boxed panel (the original Stream Core card) |
| `custom` | Chrome reset — your CSS is the look |

Set the skin in **Admin → Alert test**, or `?skin=classic|card|custom` on the overlay URL.

## Paste your CSS

1. Open **Alert test**.
2. Paste into **Custom CSS** (Streamlabs / StreamElements / OBS Custom CSS all work).
3. Save. The overlay reloads the file live — no Core restart.
4. If the pack still fights the default, switch skin to **Custom CSS only**.

You can also paste the same rules into OBS **Custom CSS** on the browser source.

## Selectors

```
#wrap / .widget-AlertBox     full source
#alert-box                   the alert (plus kind classes below)
#alert-image-wrap            GIF / WebM / PNG slot
#alert-image                 <img>
#alert-video                 <video> for .webm packs
#alert-text-wrap             text column
#alert-message               "{name} followed!" with .name / .amount wrapped
#alert-user-message          optional cheer / Super Chat comment
.name  .amount  .months  .viewers
```

Kind classes on `#alert-box` (Streamlabs names):

| Event | Classes |
|-------|---------|
| Follow | `follower-alert kind-follow` |
| Subscribe | `subscriber-alert kind-subscribe` |
| Resub | `subscriber-alert resub-alert kind-resub` |
| Gifted sub | `sub-gift-alert gift-alert kind-gift` |
| Raid | `raid-alert kind-raid` |
| Host | `host-alert kind-host` |
| Bits / cheer | `cheer-alert bits-alert kind-bits` |
| Super Chat | `superchat-alert donation-alert kind-superchat` |
| Donation | `donation-alert kind-donation` |

StreamElements aliases also present: `.alertbox-message`, `.alertbox-message-name`, `.alertbox-message-announcement`, `.alertbox-message-message`.

## CSS variables

```css
:root {
  --alert-accent: #53fc18;
  --alert-font: "Montserrat", sans-serif;
  --alert-name-size: 34px;
  --alert-msg-size: 18px;
  --alert-image-size: 96px;
}
```

## Images / WebM

Drop files in `overlay/assets/alerts/` named after the kind:

`follow.gif` `subscribe.png` `raid.webm` `superchat.webp` …

The overlay picks WebM, then GIF / WebP / PNG / SVG. If none exist, a glowing tile is shown (hidden in the custom skin).

## Tokens in the headline

Same idea as Streamlabs `{name}` `{amount}` `{months}`: the overlay wraps those values in `.name` / `.amount` / `.months` / `.viewers` so pack CSS colours the right words.
