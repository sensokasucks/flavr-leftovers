"""Regulars: !claim, !streak + titles, and your seat (!seat, !swap)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.models import ChatEvent

from .engine import Feature, name_key, speaker, user_key, user_ref


def title_for_streams(titles, streams: int) -> str:
    best = ""
    for t in titles:
        if streams >= int(t["streams"]):
            best = t["title"]
    return best


class Streaks(Feature):
    """Streams in a row (a stream = chat after a quiet gap). Titles at 5 / 10 / 25."""

    KEY = "streak"

    def __init__(self, g):
        super().__init__(g)
        self._seen: Dict[str, int] = {}        # ukey -> stream id already counted
        self._titles: Dict[str, str] = {}      # ukey -> title
        self._by_name: Dict[str, str] = {}     # "platform:username" -> title (credits)
        self._info: Dict[str, Dict[str, int]] = {}

    def forget(self) -> None:
        self._seen.clear()

    def commands(self, c):
        return {c["command"]: self.cmd}

    async def observe(self, event: ChatEvent) -> None:
        uk = user_key(event.user)
        s = await self.g.stream()
        if self._seen.get(uk) == s["id"]:
            return
        self._seen[uk] = s["id"]
        uid = await self.g.uid(event.user)
        if uid is None:
            return
        await self.g.store.attend(uid, s["id"])
        info = await self.g.store.stream_streaks(uid, s["id"])
        self._remember(event, info)

    def _remember(self, event: ChatEvent, info: Dict[str, int]) -> None:
        c = self.g.cfg["streak"]
        uk = user_key(event.user)
        self._info[uk] = info
        basis = info["best"] if c["title_from"] == "best" else info["current"]
        title = title_for_streams(c["titles"], basis)
        self._titles[uk] = title
        self._by_name[f"{event.user.platform.value}:{name_key(event.user.username)}"] = title

    def cached_title(self, user) -> str:
        return self._titles.get(user_key(user), "")

    def title_by_name(self, platform: str, username: str) -> str:
        return self._by_name.get(f"{platform}:{name_key(username)}", "")

    async def cmd(self, event: ChatEvent, args, c) -> None:
        if not self.g.store:
            return
        await self.observe(event)
        uid = await self.g.uid(event.user)
        s = await self.g.stream()
        info = await self.g.store.stream_streaks(uid, s["id"])
        self._remember(event, info)
        who = speaker(event.user)
        cur, best, total = info["current"], info["best"], info["total"]
        nxt = next((t for t in c["titles"] if t["streams"] > (best if c["title_from"] == "best" else cur)), None)
        title = self._titles.get(user_key(event.user), "")
        bits = [f"@{who} {cur} stream{'s' if cur != 1 else ''} in a row"]
        extra = [f"best {best}", f"{total} total"]
        bits.append("(" + ", ".join(extra) + ")")
        if title:
            bits.append(f"· {title}")
        if nxt:
            bits.append(f"· {nxt['title']} at {nxt['streams']}")
        await self.g.reply(event, " ".join(bits))

    def status(self):
        return {"people_seen": len(self._seen)}


class Claim(Feature):
    """Free points once per stream."""

    KEY = "claim"

    def commands(self, c):
        return {c["command"]: self.cmd}

    async def cmd(self, event: ChatEvent, args, c) -> None:
        if not await self.g.need_points(event, f"{self.g.prefix()}{c['command']}"):
            return
        uid = await self.g.uid(event.user)
        s = await self.g.stream()
        who = speaker(event.user)
        if not await self.g.store.claim_once(uid, s["id"]):
            await self.g.reply(event, f"@{who} you already claimed this stream. See you next time!")
            return
        bal = await self.g.give(uid, c["points"], "claim")
        streak = ""
        if self.g.on("streak"):
            info = await self.g.store.stream_streaks(uid, s["id"])
            streak = f" · {info['current']} in a row"
        await self.g.reply(event, f"@{who} +{c['points']} points (you have {bal}){streak}")


class Stage(Feature):
    """Mods: !curtain open | close | reveal | (nothing = toggle) for Stream Rooms' stage curtain."""

    KEY = "stage"
    WORDS = {"open": "open", "up": "open", "close": "close", "shut": "close", "down": "close",
             "reveal": "reveal", "show": "reveal", "toggle": "toggle"}

    def commands(self, c):
        return {c["command"]: self.cmd}

    async def cmd(self, event: ChatEvent, args, c) -> None:
        if not self.g.is_mod(event.user):
            return
        value = self.WORDS.get(args[0].lower() if args else "toggle")
        who = speaker(event.user)
        if value is None:
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['command']} open | close | reveal")
            return
        rx = self.g.reactions
        if rx is None or not await rx.send_stage("curtain", value):
            await self.g.reply(event, f"@{who} Stream Rooms isn't connected.")


class Seats(Feature):
    """!seat front|back moves you (front costs points); !swap @name trades with someone."""

    KEY = "seat"

    def __init__(self, g):
        super().__init__(g)
        self.offers: Dict[str, Dict[str, Any]] = {}     # target name key -> offer

    def commands(self, c):
        return {c["command"]: self.seat, c["swap_command"]: self.swap}

    def _room_open(self) -> bool:
        r = self.g.reactions
        return bool(r and r.game_clients)

    async def seat(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        where = (args[0].lower() if args else "")
        if where not in ("front", "back"):
            cost = f" (front costs {c['front_cost']})" if c["front_cost"] and self.g.points_on() else ""
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['command']} front or "
                                      f"{self.g.prefix()}{c['command']} back{cost}")
            return
        if not self._room_open():
            await self.g.reply(event, f"@{who} the room isn't open right now.")
            return
        uk = user_key(event.user)
        wait = self.g.gate.remaining(f"seat|{uk}", c["cooldown_sec"])
        if wait > 0:
            await self.g.reply(event, f"@{who} you can move again in {int(wait) + 1}s.")
            return
        charge = None
        cost = c["front_cost"] if where == "front" and self.g.points_on() else 0
        if cost:
            uid = await self.g.uid(event.user)
            ok, bal = await self.g.spend(uid, cost, "front row seat")
            if not ok:
                await self.g.reply(event, f"@{who} the front row costs {cost} points — you have {bal}.")
                return
            charge = {"uid": uid, "amount": cost}
        rid = await self.g.play("seat_move", {"where": where}, from_user=user_ref(event.user), charge=charge,
                                label="Seat", reaction="seat")
        if not rid:
            await self.g.reply(event, f"@{who} the room isn't open right now.")
            return
        self.g.gate.touch(f"seat|{uk}")
        paid = f" ({cost} pts, back if no seat is free)" if cost else ""
        await self.g.reply(event, f"@{who} moving you to the {where}{paid}.")

    async def swap(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        me = name_key(event.user.username)
        mine = self.offers.get(me)
        named = name_key(args[0]) if args else ""
        # accepting: "!swap" or "!swap @whoever-asked"
        if mine and (not named or named in (name_key(mine["from"]["username"]), name_key(mine["from"]["display_name"]))):
            self.offers.pop(me, None)
            if not self._room_open():
                await self.g.reply(event, f"@{who} the room isn't open right now.")
                return
            await self.g.play("seat_swap", {}, from_user=mine["from"],
                              target={"type": "user", "name": event.user.username},
                              label="Swap seats", reaction="swap")
            await self.g.reply(event, f"@{who} and @{mine['from']['display_name'].lstrip('@')} swap seats!")
            return
        if not named:
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['swap_command']} @name offers them a seat swap.")
            return
        if named == me:
            return
        self.offers[named] = {"from": user_ref(event.user), "expires": self.g.now() + c["swap_sec"]}
        await self.g.reply(event, f"@{args[0].lstrip('@')} — @{who} wants to swap seats. "
                                  f"Type {self.g.prefix()}{c['swap_command']} to accept ({int(c['swap_sec'])}s).")

    async def tick(self, now: float) -> None:
        for k, o in list(self.offers.items()):
            if now >= o["expires"]:
                self.offers.pop(k, None)

    def status(self):
        return {"swap_offers": len(self.offers)}
