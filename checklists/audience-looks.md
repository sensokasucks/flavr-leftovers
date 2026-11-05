# Checklist — Audience looks (Stream Rooms)

Home: `fridge-stream-core/core/audience_looks.py` (data in `data/audience_looks.json`, git-ignored with `data/`);
page **Overlays → Audience looks** (`#looks`, `admin/audience-looks.js`, loaded before `admin.js`); routes
`GET` / `PUT /api/admin/audience-looks` in `api/admin_routes.py`; `/ws` message in `api/server.py` and `main.py`
(`_send_audience_looks`). Stream Rooms' side: `core/audience/core_looks.gd` and `core/audience/audience_style.gd`.

## Must keep

- [ ] Core only keeps the settings; Stream Rooms draws. Style keys, presets, shapes and groups are Stream Rooms'
      (`AudienceStyle` in `audience_style.gd`): `BUBBLE_KEYS` / `FIGURE_KEYS` / `GROUPS` in `audience_looks.py` and
      the copies at the top of `audience-looks.js` change together with it.
- [ ] `/ws` sends `{"type": "audience_looks", "data": payload}` to every client on connect and after every save.
      The payload is the looks plus `pictures` ({stored name: {url, version}}) and `edited` (the file exists).
      Stream Rooms ignores the packet while `edited` is false, so a fresh Core never resets its looks.
- [ ] Saving normalizes: only known keys with plain values, preset names without `|` (the random-mix separator),
      at most 200 presets per kind, and the file stays under 512 KB (400 otherwise).
- [ ] Silhouette pictures are stored files written `media:<name>` in a style's `file`. The class is a stored-files
      user (`_media_users`): "Used by" lists the main silhouette and saved looks; Rename follows; Delete puts the
      classic shape back; Replace re-sends the payload so Stream Rooms downloads the new version.
- [ ] The page saves on its own (no Save button, so no page-saver section) and the preview copies Stream Rooms'
      drawing (speech_bubble.gd, `_layers`). Every control has a `title`.
- [ ] PNG / JPEG / WebP / GIF stored pictures are offered. Stream Rooms keeps up to 32 frames of an animated GIF and moves them when Paint is the picture itself (since Stream Rooms' Co-stream batch 2; older Stream Rooms builds show a GIF as the classic bust).

## After-change verify

- [ ] `python -m pytest tests/test_audience_looks.py tests/test_media_library.py`
- [ ] Open `#looks`, pick a preset, upload a picture, set a group mix; Stream Rooms (connected) changes straight away
      and its `_tests/test_audience_looks` passes.
