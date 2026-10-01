# Checklist — Alerts

Home: `core/alerts.py`, `overlay/alerts.html` + `alerts.js` + `alerts.css`. Notes: `overlay/ALERTS.md`.

## Must keep

- [ ] Overlay stays Streamlabs / StreamElements compatible: `#alert-box`, `#alert-message`, `#alert-user-message`, `.name`, `.amount`, kind classes (`follower-alert`, `cheer-alert`, …).
- [ ] Skins: Classic (default), Card, Custom CSS only.
- [ ] Default look is Classic (Montserrat, text-shadow, accent name) — not Card-only.
- [ ] Custom CSS editor on Admin → Alert test writes `overlay/alerts-custom.css` and is picked up live (no restart).
- [ ] CSS variables (`--alert-accent`, `--alert-font`, `--alert-name-size`, …) still exist.
- [ ] Optional per-kind media path: `overlay/assets/alerts/{kind}.gif|.webm|…`
- [ ] Duration comes from `overlay.alert_duration_ms` (paid chat in `_alert_from_paid_chat`; adapter sub alerts with `source:"platform"` in `StreamCore._on_alert`).
- [ ] Live sub / resub / gift alerts come from the adapters (see `adapters-chat.md`); Super Chat / bits from paid chat.
- [ ] Follow / sub / raid / bits / Super Chat / donation kinds still testable from the Alert test tab.

## Drop risks

- Restyling by changing selector names (breaks existing OBS Custom CSS packs).
- Saving settings only in memory and losing them on restart (`alerts-settings.json`).

## After-change verify

- [ ] `overlay/ALERTS.md` still matches the selectors you ship.
- [ ] Admin → Alert test still fires a sample of each kind.
- [ ] Sources list still includes `/overlay/alerts.html`.
