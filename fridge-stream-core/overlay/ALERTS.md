# Stream alerts overlay

Transparent Webpage source for OBS / XSplit.

URL: `http://127.0.0.1:3850/overlay/alerts.html`

Preview (checkerboard): add `?preview=1`

## Skins

- **classic** — default streamer look (Montserrat, text-shadow, accent name)
- **card** — boxed panel
- **custom** — chrome reset so a CSS pack can take over

Configure via Admin → Alert test tab, or edit `overlay/alerts-settings.json` and `overlay/alerts-custom.css`.

## Selectors (Streamlabs / StreamElements compatible)

- `#alert-box`
- `#alert-message`
- `#alert-user-message`
- `.name` / `.amount`
- kind classes: `follower-alert`, `cheer-alert`, `sub-alert`, etc.

CSS variables: `--alert-accent`, `--alert-font`, `--alert-name-size`, …

See CHANGELOG 0.8.0 / 0.9.0 for full details.
