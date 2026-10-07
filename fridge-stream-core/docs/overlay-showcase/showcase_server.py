"""A stand-in for Stream Core that feeds the overlays made-up chat, for showcase screenshots.

Serves the real overlay pages from ../../overlay on 127.0.0.1:3899 and, on each /ws connection,
sends a scripted chat history (all three platforms, emotes, replies, a mention, paid chat and a
Super Sticker, badges), a Stream Core reply, a poll board and a test alert. Nothing here touches
the real Core or any platform.

    .venv\\Scripts\\python.exe docs\\overlay-showcase\\showcase_server.py
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI()

TW = "https://static-cdn.jtvnw.net/emoticons/v2/{}/default/dark/2.0"
BTTV = "https://cdn.betterttv.net/emote/{}/2x"
EMOJI = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{}.png"


def em(start: int, end: int, url: str, name: str) -> dict:
    return {"start": start, "end": end, "url": url, "name": name, "provider": "showcase"}


def user(platform: str, name: str, color: str, **flags) -> dict:
    return {"id": name.lower(), "username": name.lower(), "display_name": name, "color": color,
            "is_mod": flags.get("mod", False), "is_vip": flags.get("vip", False),
            "is_subscriber": flags.get("sub", False), "badges": flags.get("badges", [])}


def chat(platform: str, who: dict, text: str, emotes=None, reply_to=None, paid=None, mid=None) -> dict:
    d = {"platform": platform, "message_id": mid or f"m{int(time.time() * 1000) % 100000}{abs(hash(text)) % 1000}",
         "message": text, "timestamp": time.time(), "emotes": emotes or [], "user": who, "reply_to": reply_to}
    if paid:
        d.update({"is_paid": True, "paid_amount": paid[0], "paid_currency": paid[1]})
    return d


def script() -> list[dict]:
    kappa, lul, pog, hey, keepo = TW.format(25), TW.format(425618), TW.format(305954156), TW.format(30259), TW.format(1902)
    fire, heart = EMOJI.format("1f525"), EMOJI.format("2764")
    sticker = EMOJI.format("1f389")
    luna = user("kick", "LunaByte", "#53fc18", sub=True, badges=["subscriber"])
    pixel = user("twitch", "PixelPirate", "#bf94ff", mod=True, badges=["moderator", "subscriber"])
    marble = user("youtube", "MarbleMoth", "#ff4e45", sub=True, badges=["member"])
    retro = user("kick", "RetroRaccoon", "#2bd4a0", badges=["og"])
    velvet = user("twitch", "velvet_vole", "#e0a040", vip=True, badges=["vip"])
    doodle = user("youtube", "DoodleDuck", "#54b8ff")
    zesty = user("twitch", "ZestyZebra", "#9ad3ff", badges=["founder", "subscriber"])
    host = user("kick", "Sensoka_FlaVR", "#ff8a65", mod=True, badges=["broadcaster"])
    quiet = user("twitch", "quietfox", "#8fd18f")
    core = {"id": "stream-core", "username": "stream_core", "display_name": "Stream Core", "color": "#53fc18",
            "is_mod": True, "is_vip": False, "is_subscriber": False, "badges": ["system"]}
    rows = [
        chat("kick", luna, "hi everyone! first time seeing the 3D room, the seats are so cool", mid="k1"),
        chat("twitch", pixel, "the curtain reveal was clean Kappa", [em(29, 33, kappa, "Kappa")], mid="t1"),
        chat("youtube", marble, "love the podium lights", mid="y1"),
        chat("twitch", velvet, "LUL LUL the tomato landed right on his head", [em(0, 2, lul, "LUL"), em(4, 6, lul, "LUL")], mid="t2"),
        chat("kick", retro, "the theater room with the balcony is my favourite", mid="k2"),
        chat("twitch", zesty, "Keepo Keepo Keepo", [em(0, 4, keepo, "Keepo"), em(6, 10, keepo, "Keepo"), em(12, 16, keepo, "Keepo")], mid="t3"),
        chat("youtube", doodle, "wait what just happened, did the lights go out?", mid="y2"),
        chat("twitch", quiet, "!points", mid="t4"),
        {"platform": "twitch", "message_id": "sys-1", "message": "@quietfox: you have 25 points", "timestamp": time.time(),
         "is_system": True, "user": core, "emotes": [], "reply_to": None},
        chat("kick", luna, "the podium looks great from the back row", mid="k3",
             reply_to={"user": "MarbleMoth", "message": "love the podium lights", "message_id": "y1"}),
        chat("twitch", pixel, "@LunaByte it looks even better from the balcony, go up the stairs", mid="t5",
             reply_to={"user": "LunaByte", "message": "the podium looks great from the back row", "message_id": "k3"}),
        chat("youtube", marble, "[$5.00] best stream setup I've seen, keep it up", mid="y3", paid=(5.0, "USD")),
        chat("youtube", doodle, "[€2.00] 🎉", [em(8, 8, sticker, "Super Sticker")], mid="y4", paid=(2.0, "EUR")),
        chat("kick", host, "welcome in! type !help to see what chat can do here", mid="k4"),
        chat("twitch", velvet, "PogChamp the whole crowd just stood up", [em(0, 7, pog, "PogChamp")], mid="t6"),
        chat("youtube", marble, "🔥 that transition ❤️", [em(0, 0, fire, "fire"), em(18, 18, heart, "heart")], mid="y5"),
        chat("kick", retro, "HeyGuys can we go to the neon city room after this?", [em(0, 6, hey, "HeyGuys")], mid="k5"),
        chat("twitch", zesty, "!1", mid="t7"),
    ]
    return rows


REPLY = {"id": "r1", "message": "@quietfox: you have 25 points", "reply_to_user": "quietfox", "reply_to_message_id": "t4",
         "source": "command", "platform": "twitch", "timestamp": time.time(), "posted_to_chat": False}
BOARD = {"id": "poll", "kind": "bars", "title": "📊 Which room next?",
         "lines": [{"key": "1", "label": "1. Neon City", "value": 7, "pct": 0.58, "note": "7 (58%)", "win": False},
                   {"key": "2", "label": "2. Drive-In", "value": 3, "pct": 0.25, "note": "3 (25%)", "win": False},
                   {"key": "3", "label": "3. Old Classroom", "value": 2, "pct": 0.17, "note": "2 (17%)", "win": False}],
         "footer": "Vote: !1 !2 !3", "ends_at": time.time() + 95, "state": "open", "ts": time.time()}
ALERT = {"id": "a1", "kind": "subscribe", "title": "New subscriber", "headline": "PixelPirate subscribed!",
         "username": "pixelpirate", "display_name": "PixelPirate", "platform": "twitch", "amount": None, "currency": "",
         "amount_fmt": "", "months": 3, "qty": None, "viewers": None, "message": "three months of tomatoes",
         "duration_ms": 30000, "is_test": False, "css_classes": ["subscriber-alert", "kind-subscribe"]}


@app.get("/api/overlay/replies")
async def replies_cfg():
    return {"enabled": True}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    await sock.send_text(json.dumps({"type": "chat_history", "data": script()}))
    await sock.send_text(json.dumps({"type": "reply_history", "data": [REPLY]}))
    await sock.send_text(json.dumps({"type": "board_history", "data": [BOARD]}))
    await asyncio.sleep(0.8)
    await sock.send_text(json.dumps({"type": "alert", "data": ALERT}))
    try:
        while True:
            await sock.receive_text()
    except Exception:
        return


app.mount("/overlay", StaticFiles(directory=str(ROOT / "overlay"), html=True), name="overlay")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3899, log_level="warning")
