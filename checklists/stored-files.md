# Checklist — Stored files

Home: `fridge-stream-core/core/media_library.py`; slots in `core/overlay_style.py`; page **Overlays → Stored files**
(`#files`, `admin.js` "Stored files"); routes in `api/admin_routes.py` and `/media/` in `api/server.py`.

## Must keep

- [ ] One copy per upload: files in `data/media/<name>.<ext>` (git-ignored), `data/media/library.json` keeps each
      file's sha256 and added time. An identical upload is reused (`reused: true`), a taken name gets `-2`, `-3`.
- [ ] Type from the first bytes only (`overlay_style.sniff`): PNG, JPEG, GIF, WebP pictures; WebM, MP4 videos
      (an `ftyp` file is M4A only for the M4A / M4B / M4P brands); MP3, OGG, WAV, M4A sounds; WOFF2, WOFF, TTF, OTF
      fonts. No SVG, no HTML. 15 MB, videos 50 MB, at most 500 files.
- [ ] Places store the file's **name**, never a copy. Alerts / chat slots: `picks` in `overlay/<name>-settings.json`
      (`write_settings` keeps them). Chat picture slots take pictures only; alerts take pictures and videos.
- [ ] Replace keeps the name (a picture may become a video, never a sound or font), so every place and
      `url(/media/<name>)` in custom CSS show the new file. Rename and Delete update / empty every place
      (`media_refs` / `media_renamed` / `media_forgotten`) and bump the overlays' `css_version` so they re-read.
- [ ] Clearing a slot (`DELETE /api/admin/overlays/{name}/assets/{slot}`) keeps the stored file and removes a
      hand-dropped `overlay/assets/<name>/<slot>.*` so it doesn't come back.
- [ ] A slot with no pick still uses a file dropped into `overlay/assets/<name>/`; at start Core copies those into
      Stored files once (`import_legacy`, names `alerts-follow`, `alerts-follow-sound`) and leaves the originals.
- [ ] `/media/<name>` and `/media/<name>.<anything>` serve by name, read-only, with the right content type;
      `library.json`, paths and unknown names are 404. Overlay links carry `?v=<time>`.
- [ ] Overlay pages stay dumb: they get finished urls in `media` / `sounds` from the settings, as before.
- [ ] Reaction pictures: any stored picture is `img:<name>` (see [reactions.md](reactions.md)); reactions show in
      "Used by" (`overlay: "reactions"`), Rename rewrites their `img:` object, Delete resets it (unless a built-in
      has the name). Older `data/reaction_images/` uploads move in at start under the same names.
- [ ] Tests write to their own folders (`OverlayStyle(..., library=MediaLibrary(tmp))`), never `data/media`.

## Not yet (later steps)

- Custom chat flags, command sounds, Stream Rooms and game plugins could point at stored files next.

## After-change verify

- [ ] `python -m pytest tests/test_media_library.py tests/test_overlay_style.py`
- [ ] Stored files page: upload two files, use one in two alert kinds, "Used by" lists both, Replace shows in OBS.
