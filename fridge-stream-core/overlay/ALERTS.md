# Stream alerts overlay

Webpage source: `/overlay/alerts.html`  
Admin test tab fires the same overlay. Live alerts: Super Chat / bits from paid chat; subscribe / resub / gifted sub from Twitch, YouTube memberships and Kick subs. Preview: `/overlay/alerts.html?preview=1`

The HTML uses **Streamlabs Alert Box** ids and **StreamElements AlertBox** classes so CSS you already wrote (or bought as a pack) can move here with little or no rewriting.

## Skins

| Skin | What it is |
|------|------------|
| `classic` | Default streamer look: Montserrat, big shadowed name, accent colour, optional GIF |
| `card` | Boxed panel (the original Stream Core card) |
| `custom` | Chrome reset — your CSS is the look |

Set the skin in **Admin → Alert test**, or `?skin=classic|card|custom` on the overlay URL.
The Custom CSS only skin plays `fadeIn` / `fadeOut` unless your CSS or `?in=` / `?out=` says otherwise.

## Paste your CSS

1. Open **Alert test**.
2. Paste into **Custom CSS** (Streamlabs / StreamElements / OBS Custom CSS all work).
3. Save. The overlay reloads the file live — no Core restart.
4. If the pack still fights the default, switch skin to **Custom CSS only**.

You can also paste the same rules into OBS **Custom CSS** on the browser source.

## URL options (one OBS source per look)

Every option is also in the address builder (Sources & overlays → Stream alerts overlay → Customise).
Add several alert sources in OBS, each with its own filters and look.

| Option | Example | What it does |
|--------|---------|--------------|
| `platforms` / `platform` | `platforms=kick,twitch` | Only alerts from those platforms |
| `kinds` | `kinds=superchat,bits,kicks` | Only these kinds (Streamlabs words work too: `follower`, `sub`, `cheer`, `tip`, `sticker`) |
| `hide` | `hide=follow,host` | Every kind except these |
| `group` | `group=money` | `money` (Super Chats, stickers, YouTube gifts, bits, KICKs, donations), `subs` (subs, resubs, gifted subs, memberships) or `community` (follows, raids, hosts) |
| `min` | `min=5` | Money alerts below this amount are skipped (any currency) |
| `min_bits` / `min_kicks` | `min_bits=500` | The same for bits and KICKs |
| `tests` | `tests=0` | Ignore **Fire test** on this source |
| `duration` | `duration=8` | Seconds on screen, instead of the dashboard setting |
| `sound` / `volume` | `sound=0`, `volume=40` | Mute, or set this source's volume (%) |
| `image` / `message` | `image=0`, `message=0` | Hide the picture slot / the viewer's message |
| `layout` | `layout=side` | `above` (default), `side` or `banner` (text over the picture), the Streamlabs layout names |
| `align` | `align=left` | `left`, `center` or `right` |
| `in` / `out` | `in=bounceIn&out=fadeOutUp` | animate.css names for the entrance and exit (keyframes in `animate-lite.css`) |
| `letters` | `letters=wiggle` | Every letter of the name and amount moves (`wiggle`, `rubberBand`, `tada`, `pulse`, or a pack's own) |
| `tiers` | `tiers=5,20,100` | Where `tier-2`, `tier-3` and `tier-4` start (default from the Alerts tab) |
| `queue` | `queue=5` | The most alerts that wait in line; extra ones are dropped (default 50) |
| `css` | `css=money` | Load the stylesheet saved as "money" instead of the main custom CSS |
| `skin` / `preview` | `skin=custom` | As before |

## Selectors

```
#wrap / .widget-AlertBox     full source; [data-layout="above|side|banner"]
#alert-box                   the alert (plus kind classes below)
#alert-image-wrap            GIF / WebM / PNG slot
#alert-image                 <img>
#alert-video                 <video> for .webm packs
#alert-text-wrap             text column
  #alert-text                wraps the two lines below (Streamlabs)
    #alert-message           "{name} followed!" with the values wrapped (below)
    #alert-user-message      optional cheer / Super Chat comment
.name  .amount  .months  .viewers  .item
```

Values in `#alert-message` are wrapped the Streamlabs way, so `#alert-message > span > span`
and `[data-token]` rules land:

```html
<span class="name alertbox-message-name" data-token="name"><span>
  <span class="animated-letter">P</span><span class="animated-letter">i</span>…
</span></span> subscribed!
```

Tokens: `name`, `amount`, `months`, `count` (gifted subs, raid viewers), `item` (sticker / gift name).

While an alert shows, `#alert-box` also carries:

| What | Example | Use it for |
|------|---------|------------|
| `platform-*` class | `platform-twitch` | one stylesheet, a look per channel (purple Twitch, red YouTube) |
| `layout-*` class | `layout-side` | the `?layout=` choice |
| `tier-1` … `tier-4` | `tier-3` | bigger alerts for bigger amounts, like Streamlabs alert variations; bits and KICKs count 100 to 1.00 |
| `membership-alert` | YouTube subs | YouTube memberships apart from Twitch subs |
| `test-alert` | Fire test | |
| `animated` + entrance / exit | `animated fadeIn`, then `animated fadeOut` | animate.css-style packs |
| `data-kind`, `data-platform`, `data-amount`, `data-currency`, `data-tier` | `[data-kind="bits"][data-platform="twitch"]` | attribute selectors |

Streamlabs nests `#wrap` inside `#alert-box`; here `#wrap` is the whole source around it. A pack
that styles `#alert-box #wrap` needs that rule moved to `#alert-box`.

Tested with the Streamlabs default alert CSS and three free packs (kiznal subscription, Slykuiper
themes 1 and 3). Packs that bring their own HTML (extra `#alert-event`, `.letter` elements) only
bring their CSS.

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
| Super Sticker | `sticker-alert superchat-alert donation-alert kind-supersticker` |
| YouTube gift (Jewels) | `jewels-alert gift-alert donation-alert kind-jewels` |
| KICKs | `kicks-alert donation-alert kind-kicks` |
| YouTube new member | `member-alert subscriber-alert kind-member` |
| YouTube member milestone | `member-alert subscriber-alert resub-alert kind-member_milestone` |
| YouTube gifted memberships | `member-alert sub-gift-alert gift-alert kind-member_gift` |

Super Sticker, YouTube gift and KICKs use the Super Chat's / Super Chat's / Donation's picture and sound until you give them their own (`supersticker.png`, `jewels.mp3`, `kicks.webm` …). YouTube memberships have their own kinds too (`member`, `member_milestone`, `member_gift`) and use the Subscribe / Resub / Gifted sub picture and sound until you give them their own. `kinds=subscribe` (or `hide=subscribe`) still covers new members, `resub` covers milestones and `gift` gifted memberships; add `platforms=` to split them. A sticker or gift with no picture of its own shows the sticker or gift.

StreamElements aliases also present: `.alertbox-message`, `.alertbox-message-name`, `.alertbox-message-announcement`, `.alertbox-message-message`.

## Saved stylesheets

**Admin → Alerts → Look (CSS) → Stylesheet** keeps more than one custom CSS ("money", "twitch").
**Add stylesheet**, paste, **Save CSS**; then `?css=money` on a source loads it. Each one reloads
live like the main one. They are saved in `overlay/alerts-css/<name>.css` (the chat overlay's in
`overlay/chat-css/`). Template placeholders such as `{font_size}` are filled in on save (see
`CHAT.md`).

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
