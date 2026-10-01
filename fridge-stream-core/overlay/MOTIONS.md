# Credits motions

`overlay/credits.js` plays these `credits.motion` ids. Keys: [CREDITS.md](CREDITS.md).

| id | Preset | What you should see | End of a Play once |
| --- | --- | --- | --- |
| `crawl` | Classic / Gold / Minimal | Names scroll up | List held on screen |
| `crawl-down` | — | Names scroll down | List held on screen |
| `starwars` | Star Wars | Receding crawl on a tilted floor | Stops once the text has gone over the horizon |
| `cards` | Neon night | Pages scale / blur in | Last page held |
| `fade` | End card | Pages crossfade | Last page held |
| `slides` | — | Pages slide sideways | Last page held |
| `ticker` | Name tape | Horizontal name tape | Stops after one pass |
| `typewriter` | Teletype | Characters type with a caret, page by page | Last page held |
| `matrix` | Matrix | Glyph rain; names decode in place, a screen at a time | Last screen held |

With **Play once, then clear** (or `clear_when_done`) every motion ends on an empty screen instead.

## How the engine behaves

- One `requestAnimationFrame` loop drives every motion; OBS / CEF drop CSS keyframe crawls.
- Star Wars tilts `#sw-world` (perspective + `rotateX`) and moves `#sw-track`; every other crawl moves only `#sw-track`.
- A motion change, a motion-timing change or **Restart roll** hard-resets: timers, observers and leftover transforms are cleared before the new motion mounts, so a half-finished motion can't leave a black screen.
- Colour / font / copy / roster changes redraw in place: a crawl keeps its position, pages keep their page, the ticker keeps its offset.
- **Hold still** / **Pause** still mount the chosen motion (Matrix, Teletype, pages), frozen; they don't fall back to a crawl.
- Page motions paginate by screen height (rows that fit × columns), so a big chat becomes more pages instead of spilling off screen.
- Movie styles: opening `cards` → crawl → `end_hold_sec` → `stinger` → loop. Page and Matrix motions page through the same departments and groups.

## Checking a motion

Pick it in Admin → Credits → Style, then watch the Preview. `window.__credits.engine` in the overlay's devtools shows `motion` and `phase` (`crawl`, `cards`, `end`, `stinger`, `pages`, `typewriter`, `ticker`, `matrix`, `empty`).
