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
- [ ] Super Sticker (`supersticker`), YouTube gift (`jewels`) and KICKs (`kicks`) have their own kinds with `falls_back` (superchat / superchat / donation): the overlay uses the fallback's picture and sound until the kind has its own, and a sticker / gift's own `image` before the fallback's. Their classes keep the older names too (`donation-alert`, `superchat-alert`, `gift-alert`) so existing CSS still styles them. `build_alert(item=..., image=..., amount_text=...)`: an amount Core can't read shows the platform's own text, never a default.

## Drop risks

- Restyling by changing selector names (breaks existing OBS Custom CSS packs).
- Saving settings only in memory and losing them on restart (`alerts-settings.json`).

## After-change verify

- [ ] `overlay/ALERTS.md` still matches the selectors you ship.
- [ ] Admin → Alert test still fires a sample of each kind.
- [ ] Sources list still includes `/overlay/alerts.html`.
