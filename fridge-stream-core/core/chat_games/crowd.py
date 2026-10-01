"""Crowd moments: emote combos, the hype meter, cheer vs boo, the group launch."""

from __future__ import annotations

import re
from collections import Counter, deque
from typing import Any, Dict, List, Optional

from core.models import ChatEvent

from .engine import Feature, clock, speaker, user_key, user_ref

_KICK_EMOTE = re.compile(r"\[emote:(\d+):([^\]]+)\]")


def _vs16(s: str) -> str:
    return (s or "").replace("️", "")


def message_tokens(event: ChatEvent) -> Dict[str, Any]:
    """Words and emote names in a message, lower case, without YouTube's ":" around names."""
    text = event.message or ""
    names: List[str] = []
    for em in event.emotes or []:
        n = str((em or {}).get("name") or "").strip().strip(":")
        if n:
            names.append(n)
    for m in _KICK_EMOTE.finditer(text):
        names.append(m.group(2))
    plain = _KICK_EMOTE.sub(" ", text)
    words = [w.strip(":").strip() for w in plain.split()]
    return {
        "names": names,                                        # real emotes, original case
        "tokens": {w.lower() for w in words if w} | {n.lower() for n in names},
        "plain": _vs16(plain),
    }


class Combos(Feature):
    """3+ people use emotes from the same mood within a few seconds -> the room reacts."""

    KEY = "combos"

    def __init__(self, g):
        super().__init__(g)
        self.hits: Dict[str, deque] = {}        # mood id -> deque[(ts, ukey, ref, emote name or "")]
        self.last_fired: List[Dict[str, Any]] = []

    def moods_hit(self, event: ChatEvent, moods: List[Dict[str, Any]]) -> List[tuple]:
        t = message_tokens(event)
        out = []
        for m in moods:
            if not m["enabled"] or not m["effects"]:
                continue
            emote = ""
            for name in m["emotes"]:
                if name.strip(":").lower() in t["tokens"]:
                    emote = next((n for n in t["names"] if n.lower() == name.strip(":").lower()), name.strip(":"))
                    break
            hit = bool(emote) or any(_vs16(e) and _vs16(e) in t["plain"] for e in m["emoji"])
            if hit:
                out.append((m, emote))
        return out

    async def observe(self, event: ChatEvent) -> None:
        c = self.g.cfg["combos"]
        now = self.g.now()
        for mood, emote in self.moods_hit(event, c["moods"]):
            q = self.hits.setdefault(mood["id"], deque())
            q.append((now, user_key(event.user), user_ref(event.user), emote))
            while q and now - q[0][0] > c["window_sec"]:
                q.popleft()
            people = {h[1]: h[2] for h in q}
            if len(people) < c["min_people"]:
                continue
            gkey = f"combo|{mood['id']}"
            if not self.g.gate.allow(gkey, c["cooldown_sec"]):
                continue
            await self.fire(mood, list(people.values()), [h[3] for h in q if h[3]])
            self.g.gate.touch(gkey)
            q.clear()

    async def fire(self, mood: Dict[str, Any], crowd: List[Dict[str, Any]], emotes: List[str]) -> None:
        c = self.g.cfg["combos"]
        top = Counter(emotes).most_common(1)[0][0] if emotes else (mood["emoji"][0] if mood["emoji"] else "✨")
        effects = []
        for e in mood["effects"]:
            params = {k: (top if v == "{emote}" else v) for k, v in (e.get("params") or {}).items()}
            effects.append({"effect": e["effect"], "params": params})
        n = len(crowd)
        scale = max(1.0, min(3.0, n / max(1, c["min_people"])))
        await self.g.play_list(effects, scale=scale, crowd=crowd, from_user=crowd[-1], count=n,
                               label=mood["label"], reaction=f"combo_{mood['id']}")
        self.g.stats["combos"] += 1
        self.last_fired.insert(0, {"mood": mood["id"], "people": n, "emote": top, "ts": self.g.now()})
        del self.last_fired[10:]

    def status(self) -> Dict[str, Any]:
        return {"recent": list(self.last_fired)}


class Hype(Feature):
    """Different people chatting in the last minute. Each level sets off a crowd moment."""

    KEY = "hype"

    def __init__(self, g):
        super().__init__(g)
        self.seen: deque = deque()     # (ts, ukey)
        self.fired_level = 0
        self._shown: Optional[tuple] = None
        self._board_at = 0.0

    async def observe(self, event: ChatEvent) -> None:
        self.seen.append((self.g.now(), user_key(event.user)))
        await self._check()

    def people(self) -> int:
        c = self.g.cfg["hype"]
        now = self.g.now()
        while self.seen and now - self.seen[0][0] > c["window_sec"]:
            self.seen.popleft()
        return len({k for _, k in self.seen})

    def level_of(self, people: int) -> int:
        return sum(1 for n in self.g.cfg["hype"]["levels"] if people >= n)

    async def _check(self) -> None:
        c = self.g.cfg["hype"]
        n = self.people()
        level = self.level_of(n)
        if level < self.fired_level:
            self.fired_level = level
        if level > self.fired_level:
            key = f"hype|{level}"
            if self.g.gate.allow(key, c["cooldown_sec"]):
                self.g.gate.touch(key)
                effects = c["level_effects"][level - 1] if level - 1 < len(c["level_effects"]) else []
                await self.g.play_list(effects, label=f"Hype level {level}", reaction=f"hype_{level}")
                await self.g.announce(f"🔥 Hype level {level}! {n} people chatting.")
            self.fired_level = level

    async def tick(self, now: float) -> None:
        await self._check()
        c = self.g.cfg["hype"]
        n = self.people()
        if not c["show_meter"] or n < 2:
            if "hype" in self.g.boards:
                await self.g.clear_board("hype")
            self._shown = None
            return
        levels = c["levels"]
        level = self.level_of(n)
        nxt = levels[level] if level < len(levels) else levels[-1]
        prev = levels[level - 1] if level > 0 else 0
        pct = 1.0 if level >= len(levels) else (n - prev) / max(1, nxt - prev)
        state = (n, level)
        if state == self._shown and now - self._board_at < 10:
            return
        self._shown, self._board_at = state, now
        await self.g.board("hype", kind="meter", title="🔥 Hype",
                           lines=[{"key": "hype", "label": f"Level {level}", "value": n, "pct": round(pct, 3),
                                   "note": f"{n} chatting"}],
                           footer=("Max level!" if level >= len(levels) else f"Level {level + 1} at {nxt} people"))

    def status(self) -> Dict[str, Any]:
        n = self.people()
        return {"people": n, "level": self.level_of(n)}


class Tug(Feature):
    """!cheer vs !boo: a round of tug of war; the winning side gets a reveal."""

    KEY = "tug"

    def __init__(self, g):
        super().__init__(g)
        self.round: Optional[Dict[str, Any]] = None
        self._dirty = False

    def commands(self, c):
        return {c["cheer_command"]: self.cheer, c["boo_command"]: self.boo}

    async def cheer(self, event, args, c):
        await self.vote(event, c, "cheer")

    async def boo(self, event, args, c):
        await self.vote(event, c, "boo")

    async def vote(self, event: ChatEvent, c: Dict[str, Any], side: str) -> None:
        now = self.g.now()
        r = self.round
        if r is None:
            wait = self.g.gate.remaining("tug", c["cooldown_sec"])
            if wait > 0:
                if self.g.gate.allow(f"tug-say|{user_key(event.user)}", 15):
                    self.g.gate.touch(f"tug-say|{user_key(event.user)}")
                    await self.g.reply(event, f"@{speaker(event.user)} next cheer-vs-boo round in {int(wait) + 1}s.")
                return
            r = self.round = {"cheer": 0, "boo": 0, "ends": now + c["round_sec"], "last": {}, "people": set()}
            await self.g.announce(f"📣 Cheer vs boo! {self.g.prefix()}{c['cheer_command']} or "
                                  f"{self.g.prefix()}{c['boo_command']} — {int(c['round_sec'])}s")
        uk = user_key(event.user)
        if now - r["last"].get(uk, -1e9) < c["per_user_gap_sec"]:
            return
        r["last"][uk] = now
        r["people"].add(uk)
        r[side] += 1
        self._dirty = True
        await self._show(c)

    async def _show(self, c, state="open", winner=None, hold=None):
        r = self.round
        total = max(1, r["cheer"] + r["boo"])
        lines = [
            {"key": "cheer", "label": "📣 Cheer", "value": r["cheer"], "pct": round(r["cheer"] / total, 3),
             "note": str(r["cheer"]), "win": winner == "cheer"},
            {"key": "boo", "label": "👎 Boo", "value": r["boo"], "pct": round(r["boo"] / total, 3),
             "note": str(r["boo"]), "win": winner == "boo"},
        ]
        footer = (f"{self.g.prefix()}{c['cheer_command']} or {self.g.prefix()}{c['boo_command']}" if state == "open"
                  else {"cheer": "Cheers win!", "boo": "Boos win!"}.get(winner, "It's a tie!"))
        kw = {"hold": hold} if hold else {}
        await self.g.board("tug", kind="tug", title="Cheer vs boo", lines=lines, footer=footer,
                           ends_at=r["ends"] if state == "open" else None, state=state, **kw)
        self._dirty = False

    async def tick(self, now: float) -> None:
        r = self.round
        if r is None:
            return
        c = self.g.cfg["tug"]
        if now < r["ends"]:
            if self._dirty:
                await self._show(c)
            return
        winner = "cheer" if r["cheer"] > r["boo"] else "boo" if r["boo"] > r["cheer"] else ""
        await self._show(c, "closed", winner)
        self.round = None
        self.g.gate.touch("tug")
        score = f"{r['cheer']}–{r['boo']}"
        if winner == "cheer":
            await self.g.play_list([{"effect": "confetti", "params": {"count": 160}},
                                    {"effect": "crowd_motion", "params": {"style": "cheer", "who": "all", "duration_sec": 4}}],
                                   label="Cheers win", reaction="tug_cheer")
            await self.g.announce(f"📣 Cheers win {score}!")
        elif winner == "boo":
            await self.g.play_list([{"effect": "rain", "params": {"object": "🍅", "count": 30, "duration_sec": 4}},
                                    {"effect": "lights", "params": {"mode": "dim", "duration_sec": 2}}],
                                   label="Boos win", reaction="tug_boo")
            await self.g.announce(f"👎 Boos win {score}!")
        else:
            await self.g.play("camera_shake", {"strength": 0.2, "duration_sec": 0.4}, label="Tie", reaction="tug_tie")
            await self.g.announce(f"It's a tie, {score}!")

    def status(self):
        r = self.round
        return {"open": bool(r), "cheer": r["cheer"] if r else 0, "boo": r["boo"] if r else 0}


class Launch(Feature):
    """Enough people type !launch within the window -> countdown, lights down, fireworks."""

    KEY = "launch"

    def __init__(self, g):
        super().__init__(g)
        self.window: Optional[Dict[str, Any]] = None
        self.flying = False

    def commands(self, c):
        return {c["command"]: self.cmd}

    async def cmd(self, event: ChatEvent, args, c) -> None:
        if self.flying:
            return
        now = self.g.now()
        if self.window is None:
            wait = self.g.gate.remaining("launch", c["cooldown_sec"])
            if wait > 0:
                if self.g.gate.allow(f"launch-say|{user_key(event.user)}", 20):
                    self.g.gate.touch(f"launch-say|{user_key(event.user)}")
                    await self.g.reply(event, f"@{speaker(event.user)} the launch pad is recharging ({clock(wait)}).")
                return
            self.window = {"people": {}, "ends": now + c["window_sec"]}
            await self.g.announce(f"🚀 Launch sequence! {c['people']} people type {self.g.prefix()}{c['command']} "
                                  f"within {int(c['window_sec'])}s.")
        self.window["people"][user_key(event.user)] = user_ref(event.user)
        n = len(self.window["people"])
        if n >= c["people"]:
            await self.go(c)
        else:
            await self._show(c)

    async def _show(self, c, state="open", title="🚀 Launch", footer=None):
        w = self.window
        n = len(w["people"]) if w else c["people"]
        await self.g.board("launch", kind="count", title=title, state=state,
                           lines=[{"key": "people", "label": "Crew", "value": n,
                                   "pct": round(min(1.0, n / c["people"]), 3), "note": f"{n}/{c['people']}"}],
                           footer=footer or f"Type {self.g.prefix()}{c['command']} to join",
                           ends_at=w["ends"] if (w and state == "open") else None)

    async def go(self, c) -> None:
        crowd = list(self.window["people"].values())
        self.window = None
        self.flying = True
        self.g.gate.touch("launch")
        await self.g.play("lights", {"mode": "dim", "duration_sec": 7}, label="Launch", reaction="launch")
        await self.g.play("spotlight", {"duration_sec": 7}, target={"type": "stage", "name": ""},
                          label="Launch", reaction="launch")

        async def count(n: int):
            await self.g.board("launch", kind="count", title=f"🚀 {n}…", state="locked",
                               lines=[{"key": "t", "label": "Liftoff in", "value": n, "pct": round((4 - n) / 3, 3),
                                       "note": str(n)}], footer="Hold on!")

        await count(3)
        self.g.later(1, lambda: count(2))
        self.g.later(2, lambda: count(1))

        async def liftoff():
            self.flying = False
            await self.g.board("launch", kind="count", title="🚀 LIFTOFF!", state="closed",
                               lines=[{"key": "t", "label": "Crew", "value": len(crowd), "pct": 1.0,
                                       "note": f"{len(crowd)} people"}], footer="")
            await self.g.play_list([{"effect": "fireworks", "params": {"count": 10, "duration_sec": 5}},
                                    {"effect": "confetti", "params": {"count": 250}},
                                    {"effect": "camera_shake", "params": {"strength": 0.6, "duration_sec": 0.8}},
                                    {"effect": "crowd_motion", "params": {"style": "cheer", "who": "all",
                                                                          "duration_sec": 4}}],
                                   crowd=crowd, label="Liftoff", reaction="launch")
            await self.g.announce(f"🚀 Liftoff! {len(crowd)} people launched the room.")

        self.g.later(3, liftoff)

    async def tick(self, now: float) -> None:
        w = self.window
        if w and now >= w["ends"]:
            c = self.g.cfg["launch"]
            n = len(w["people"])
            await self._show(c, "closed", "🚀 Launch fizzled", f"{n}/{c['people']} — try again soon")
            self.window = None
            # a fizzle only waits a minute (or the full recharge, if that's shorter)
            self.g.gate.touch("launch", now - max(0.0, c["cooldown_sec"] - min(60.0, c["cooldown_sec"])))

    def status(self):
        return {"open": bool(self.window), "people": len(self.window["people"]) if self.window else 0,
                "flying": self.flying}
