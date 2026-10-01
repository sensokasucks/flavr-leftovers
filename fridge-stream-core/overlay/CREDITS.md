# Credits overlay

Webpage source: `/overlay/credits.html`  
Style editor: **Admin → Credits → Style**.

Every motion runs on one `requestAnimationFrame` loop (not CSS `@keyframes`), so it moves in XSplit / OBS CEF. The look is live-editable; **Save look** writes it to `config.yaml` (`credits:`). This engine is the merge of Core's credits and the standalone Chat Credits engine: same keys, and the file also runs under Chat Credits (it tries `/api/credits/*` first, then `/api/*`).

Motion ids, what each looks like and how they end: [MOTIONS.md](MOTIONS.md).

## Style editor

| Tab | What it covers |
|-----|----------------|
| **Motion** | Motion, easing, intros, loop transition, page / typewriter / matrix timing, vignette, letterbox, film grain, "leave the screen empty after Play once" |
| **Copy** | Title, subtitle, footer, section label |
| **Type** | Font preset / custom Google Font, sizes, weight, letter-spacing |
| **Color** | Title / names / muted / mods / VIPs, glow, shadow, backdrop |
| **Layout** | Columns, alignment, job-row style, divider, max width, **cast format** |
| **List** | Sort, platform grouping, dots, counts, mod / VIP highlight |

Presets along the top: Classic, Star Wars, Gold titles, Neon night, Teletype, End card, Name tape, **Matrix**, Minimal. Each one stamps a bundle of keys (and resets letterbox, grain and the backdrop first). Tweak after. Old preset names `teletype` / `nametape` still work.

Look edits **preview live** without restarting the roll: the overlay redraws where it is. Changing the motion or its timing (typewriter speed / unit, matrix density, page time, easing, name enter, title intro) restarts it.

## Roll controls (Admin → Credits → Feature + roll)

| Button | Does |
|--------|------|
| Roll credits (freeze list) | Freeze the current list and loop it from the top |
| Live list | Unfreeze; new chatters join the roll where it is |
| Loop / Play once / Hold still | Play mode. Hold still shows the list where it can be read |
| Play once, then clear | Play once, then leave the screen empty (`mode: clear`) |
| Pause / Play | Freeze / resume in place |
| Restart roll | Start the current motion over |
| Download CSV | `platform, username, display_name, messages, first_seen, mod` |

The list under the preview updates live and shows mods (★), message counts, sub / VIP / paid and movie jobs.

Roster filters are in **Admin → Config → Chat credits**: leave your own channel out, shortest message that counts, and names to ignore (one per line; the built-in bot list applies when it's empty).

## Useful keys

Same keys the editor writes. Query-string overrides still work, e.g.
`/overlay/credits.html?motion=matrix&title=THE%20CREW`

| Key | Meaning |
|-----|---------|
| `motion` | `crawl` · `crawl-down` · `starwars` · `cards` · `fade` · `slides` · `ticker` · `typewriter` · `matrix` (aliases `teletype`, `nametape`) |
| `mode` | `loop` · `once` · `hold` · `clear` |
| `easing` | `linear` · `ease-in` · `ease-out` · `ease-in-out` · `smooth` (crawls) |
| `title_intro` | `none` · `fade` · `scale` · `wipe` · `letters` |
| `title_hold_sec` | Crawl: wait before it starts. Pages: extra time on the first page |
| `name_enter` / `name_stagger_ms` | `none` · `fade` · `rise` · `slide` · `blur` as names enter the frame (crawls) |
| `loop_transition` | `cut` · `fade` · `wipe` (crawl up / down) |
| `tilt_deg` / `perspective_px` | Star Wars floor angle and depth (Star Wars preset: 32° / 320 px) |
| `page_duration_sec` / `page_transition_ms` | Page motions and Matrix: time per page, crossfade time |
| `title_own_page` | Page motions: title on its own page (default) or on top of the first page |
| `typewriter_unit` | `line` (type a line, short pause) · `card` · `page` · `name` (whole names every `type_ms`) |
| `typewriter_cps` | Typing speed, characters per second |
| `matrix_density` | Rain density 0.4 – 2.2 |
| `clear_when_done` | Play once ends on an empty screen |
| `letterbox` / `grain` / `vignette` | Film look |
| `mask_fade_px` | Soft top / bottom edge. `0` = hard crop |
| `glow` / `glow_color` / `glow_px` | Title + name bloom |
| `job_layout` | `dots` · `stacked` · `inline`. With 2+ columns and 4+ rows, dotted crews sit in two columns |
| `custom_font_url` | Stylesheet URL (Google Fonts). Needs network in OBS / XSplit |

Standalone Chat Credits names are accepted and converted when saved: `sw_tilt_deg` → `tilt_deg`, `sw_perspective_px` → `perspective_px`, `page_hold_sec` → `page_duration_sec`, `page_fade_sec` → `page_transition_ms`. Numbers are clamped and unknown enum values fall back (`core/credits_theme.py` `sanitize_look`); keys it doesn't know are kept.

Transparent Webpage source is the default (`background: transparent`). With a solid backdrop the edges fade into that colour, Teletype gets its paper + scanlines, and Matrix rain paints on it. On a transparent overlay Matrix rain falls over your scene.

## Movie extras (cast style JSON)

A movie cast style (`config/cast/*.json`, Layout → Cast format) can add these; anything missing is skipped. `{count}` becomes the number of unique chatters.

```json
{
  "cards": ["A Chat Production", {"type": "mpaa", "line": "Rated C for {count} chatters", "hold_sec": 3}],
  "starring": ["Starring", "Co-starring"],
  "thanks": ["Snacks: Mom", {"job": "Moral support", "display_name": "The Cat"}],
  "legal": ["No chatters were harmed in the making of this stream"],
  "end_hold_sec": 3,
  "stinger": {"kicker": "After the credits", "line": "Same time tomorrow", "hold_sec": 4},
  "look": {"letterbox": true, "grain": true}
}
```

- `cards` play before a crawl (they replace the title). Card `type`: `mpaa` draws a rating box; `association`, `location`, `studio`, `runtime` use the small line.
- `starring` bills the top talkers, one label each.
- `end_hold_sec` holds the end of the crawl; `stinger` shows after it.
- `look` turns on letterbox / grain / vignette for this style (the editor switches still work).

Each person appears once in a movie roll: the first department or group that lists them wins.
