# Checklist — Phone remote

Home: `fridge-stream-core/core/phone_remote.py` (pairing + keys, `data/phone_remote.json`), `api/phone_server.py` (the phone door: a second uvicorn server, its own small app), `api/phone_admin_routes.py` (the dashboard's Setup → Phone remote page), `phone/` (the page the phone opens), admin.js "Phone remote". Wired in `main.py _run`. User guide: [docs/PHONE_REMOTE.md](../fridge-stream-core/docs/PHONE_REMOTE.md).

## Must keep

- [ ] **Off by default** (`phone_remote.enabled: false`). With it off nothing listens on 3860. `stop_on_exit` (default on) turns it off again when Core starts, so it only runs on streams where it was switched on.
- [ ] Port **3860** is the phone door only. It listens on the PC's **home-network address** (`find_home_address()`, or `phone_remote.host` when set), never `0.0.0.0` and never the 127.0.0.1:3850 dashboard. `host` must pass `is_home_address`.
- [ ] Every request whose caller isn't a home-network address (`is_home_address`: 192.168 / 10 / 172.16-31, IPv6 link-local / unique-local; never loopback) gets 403 before anything else runs.
- [ ] The dashboard (3850) stays loopback-only and its LocalGuard is untouched. The phone page is served only on 3860.
- [ ] Pairing: only from the PC dashboard (**Add a phone**). One code at a time, 6 digits + a QR token, good for `PAIR_SECONDS` (120) and one phone; 5 wrong codes close it, 15 wrong in a row lock pairing for 5 minutes; the door also rate-limits `/phone/api/pair` per address. No mod or chat command can pair a phone (Sen's choice).
- [ ] Each phone has its own key (32 random bytes). Only its SHA-256 is saved; **Remove** on the Setup page stops that phone straight away. At most `MAX_PHONES` (10).
- [ ] The phone's key goes in the `X-Phone-Key` header (from the page's localStorage), never in a URL. No cookies, no CORS headers, so other web pages can't use a paired phone's browser.
- [ ] The phone reaches dashboard actions only through `/phone/api/admin/<path>`, checked against `ALLOWED` in `api/phone_server.py` (highlight, curtain, credits play, chat game buttons, user search + points, red-flag add / remove, reaction test, Stream events). Settings, config, sign-ins, uploads, restart, history clearing, the red-flag phrase list and anything else are refused (403). Adding to `ALLOWED` is a security change: think about it, test it.
- [ ] Allowed calls are run inside Core (httpx ASGITransport to the main app) with the admin token added by Core; the token never reaches the phone. They carry `X-Fridge-From: phone` so the Stream events window can say "from the phone".
- [ ] The phone sees red-flagged chatters' names only (`/phone/api/flagged`), never the flag phrases.
- [ ] A failure to open 3860 (address in use, address gone) is shown on the Setup page and never stops Core. The two servers don't fight over Ctrl+C (`_QuietServer`).
- [ ] Risky phone presses (red flag, taking points, clearing boards) are hold-to-confirm; points changes show an Undo for 30 s.
- [ ] Platform timeouts / bans from the phone are **planned only, not built** (Sen, 2026-11-03).

## After-change verify

- [ ] `python -m pytest tests/test_phone_remote.py -q`
- [ ] Setup → Phone remote: tick **Phone remote on**, the address shows; **Add a phone** shows a QR and a code; a phone on the same Wi-Fi pairs, sees chat, can highlight a line and give points; **Remove** stops it.
- [ ] `http://127.0.0.1:3860/` does not answer, and the phone page isn't served on 3850.
