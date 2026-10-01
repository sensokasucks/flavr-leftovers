# Credits motions (standalone)

The overlay engine in `credits.js` plays these `theme.motion` ids:

| id | Preset chip | What you should see |
| --- | --- | --- |
| `crawl` | Classic / Gold / Neon | Names scroll up |
| `crawl-down` | (motion dropdown) | Names scroll down |
| `starwars` | Star Wars | Receding crawl on a 3D floor |
| `cards` | End card | Paginated name cards |
| `fade` | Minimal | Pages fade |
| `slides` | (motion dropdown) | Pages slide |
| `ticker` | Name tape | Horizontal name tape |
| `typewriter` | Teletype | Characters type with a caret; scanline terminal panel |
| `matrix` | Matrix | Glyph rain + names decode in place |

## Why Teletype used to look like Classic

Three things had to be true at once:

1. `/overlay/credits.js` booted `/api/credits/theme` (Stream Core path). Standalone serves `/api/theme`. Boot failed, motion stayed `crawl`, and only colors/font arrived later over the websocket.
2. Hold / Pause short-circuited `startMotion()` into a parked crawl reel, so picking Matrix or Teletype only restyled Classic.
3. A look sanitizer that dropped unknown motions would persist Teletype as Classic after Save.

Fixes:

- Overlay probes `/api/theme` then `/api/credits/theme` (same for roster + play).
- Hold still mounts Matrix / Teletype / pages instead of forcing a crawl.
- Preset chips POST `/api/play` `{playing:true, restart:true}` after save.
- `core/look.py` `sanitize_look()` keeps `matrix` and `typewriter`.

Wire the sanitizer into the theme PUT handler:

```python
from core.look import sanitize_look, merge_look
theme = merge_look(current_theme, body)
```

Cache-bust query on `credits.html` / `control.html` is `?v=20260928n`. Hard-refresh Control and the OBS browser source after copying files.
