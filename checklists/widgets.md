# Checklist — Chat widgets

Home: `fridge-stream-core/core/widget_store.py`; pages `overlay/widget.html` (+ `widget.js`,
`widget-bridge.js`, `widget-frame.js`); dashboard **Overlays → Chat widgets** (`#widgets`); routes in
`api/admin_routes.py` (`/api/admin/widgets*`) and `api/server.py` (`/widget-frame/<name>`,
`/api/overlay/widget/<name>`). Notes: [overlay/WIDGETS.md](../fridge-stream-core/overlay/WIDGETS.md).

## Must keep

- [ ] The widget's code only ever runs in `/widget-frame/<name>`, served with `FRAME_CSP`
      (`sandbox allow-scripts`, no `allow-same-origin`) and framed with `sandbox="allow-scripts"`.
      It must not get the dashboard token, the admin API, `/ws` or Core's storage. Core's own page
      (`widget.html`) is the only thing that talks to `/ws`, and passes events in by `postMessage`.
- [ ] Import takes StreamElements' export zip (`widget.ini` + html/css/js/fields/data `.txt`), their
      GitHub layout (`widget.html/.css/.js/.json`) and loose `.html` / `.css` / `.js` / fields `.json`;
      zip ≤ 20 MB, each part ≤ 5 MB (checked before reading), ≤ 100 widgets. Bad JSON in fields / data
      is refused with a plain message.
- [ ] Widgets live in `data/widgets/<name>/` (git-ignored); names via `media_library.clean_name`, a
      taken name gets `-2`. Saving settings or code bumps `version`; open pages reload the frame.
- [ ] Settings fill `{{key}}` and `{key}` (StreamElements) or `{{key}}` (Streamlabs) only for keys the
      widget has; other braces (CSS rules, JS, Streamlabs' `{from}`) stay. Then `css_templates`.
- [ ] Widget code can't close its own `<script>` / `<style>` (`</script` → `<\/script`).
- [ ] StreamElements events keep SE's shapes (`listener` + `event`, `event.data` for messages,
      `widget-button` with `event.field`); Streamlabs chat items are HTML-escaped before the template.
- [ ] Kick / YouTube chat is translated (emote tokens, badges), never dropped; red-flag hides and mod
      deletions reach the widget as delete events.

## After-change verify

- [ ] `python -m pytest tests/test_widgets.py` (the bridge tests need `node`)
- [ ] Import a real StreamElements zip, change a colour, Save, the open OBS source updates; press one of
      its test buttons; a Kick and a Twitch line and a test follow show in it.
