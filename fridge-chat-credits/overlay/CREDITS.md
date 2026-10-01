# Credits overlay

Webpage source: `/overlay/credits.html`  
Style editor: **Admin → Credits** (Stream Core) or the Chat Credits control desk.

The overlay crawls with a pixel `requestAnimationFrame` loop (not CSS `@keyframes`) so it moves in XSplit / OBS CEF. Look is live-editable; **Save look** writes it to disk.

## Style editor

Tabs:

| Tab | What it covers |
|-----|----------------|
| **Motion** | How the roll plays, easing, intros, loop transitions |
| **Copy** | Title, subtitle, footer, section label |
| **Type** | Font preset / custom Google Font, sizes, weight, letter-spacing |
| **Color** | Title / names / muted / mods / VIPs, glow, shadow, backdrop |
| **Layout** | Columns, alignment, job-row style, divider, max width, **cast format** |
| **List** | Sort, platform grouping, dots, counts, mod / VIP highlight |

Presets along the top (Classic, Star Wars, Gold titles, Neon night, Teletype, End card, Name tape, Minimal) stamp a bundle of those keys. Tweak after.

Edits **preview live** on the overlay. Save look persists them (`config.yaml` in Core, `data/theme.json` in Chat Credits).

Cast format (Names / Movie / Studio Lot) is on the Layout tab. Job pins stay in the Movie / Pins card.

## Motions

| Id | Behaviour |
|----|-----------|
| `crawl` | Classic titles rolling up |
| `crawl-down` | Same, downward |
| `starwars` | Perspective tilt + crawl |
| `cards` | One block at a time, scale in |
| `fade` | One block at a time, crossfade |
| `slides` | One block at a time, slide |
| `ticker` | Horizontal name tape |
| `typewriter` | Names appear in order |

Page motions (`cards` / `fade` / `slides` / `typewriter`) use `page_duration_sec` and `page_transition_ms`. Crawl motions use `speed_px_per_sec` or `duration_sec` (0 = use px/s).

## Useful keys

Same keys the editor writes. Overlay query-string overrides still work, e.g.

`/overlay/credits.html?motion=starwars&title=THE%20CREW`

| Key | Meaning |
|-----|---------|
| `motion` | See table above |
| `easing` | `linear` · `ease-in` · `ease-out` · `ease-in-out` · `smooth` |
| `title_intro` | `none` · `fade` · `scale` · `wipe` · `letters` |
| `name_enter` | `none` · `fade` · `rise` · `slide` · `blur` (as names enter the frame) |
| `loop_transition` | `cut` · `fade` · `wipe` |
| `mask_fade_px` | Soft edge fade. `0` = hard crop |
| `vignette` | Inset shadow |
| `glow` / `glow_color` / `glow_px` | Title + name bloom |
| `job_layout` | `dots` · `stacked` · `inline` |
| `custom_font_url` | Stylesheet URL (Google Fonts). Needs network in OBS/XSplit |

Transparent Webpage source is still the default (`background: transparent`). Turn on **Opaque backdrop** in Color only for a preview card.
