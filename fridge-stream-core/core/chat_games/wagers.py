"""Points games: predictions, duels, slots, heists. All stakes go through the one points
ledger (Store.spend_points / adjust_points, source="game"); nothing goes below zero."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.models import ChatEvent

from .engine import Feature, fmt_points, name_key, parse_amount, speaker, user_key, user_ref


def _match_option(word: str, options: List[str]) -> Optional[int]:
    w = str(word or "").strip().lower().lstrip("#")
    if not w:
        return None
    if w.isdigit() and 1 <= int(w) <= len(options):
        return int(w) - 1
    for i, o in enumerate(options):
        if o.lower() == w:
            return i
    hits = [i for i, o in enumerate(options) if o.lower().startswith(w)]
    return hits[0] if len(hits) == 1 else None


def _split_bar(text: str) -> List[str]:
    return [p.strip() for p in text.split("|")]


class Predict(Feature):
    """Mods: !predict open Question? | A | B, !predict lock, !predict win A, !predict cancel.
    Chat: !predict A 50. Winners split the whole pot by how much they put in."""

    KEY = "predict"

    def __init__(self, g):
        super().__init__(g)
        self.p: Optional[Dict[str, Any]] = None

    def commands(self, c):
        return {c["command"]: self.cmd}

    async def cmd(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        first = (args[0].lower() if args else "")
        mod = self.g.is_mod(event.user)
        if mod and first in ("open", "start"):
            text = " ".join(args[1:])
            parts = _split_bar(text)
            res = await self.open(parts[0], [p for p in parts[1:] if p])
            if not res["ok"]:
                await self.g.reply(event, f"@{who} {res['message']}")
            return
        if mod and first in ("lock", "close"):
            res = await self.lock()
            if not res["ok"]:
                await self.g.reply(event, f"@{who} {res['message']}")
            return
        if mod and first in ("win", "winner", "result"):
            res = await self.resolve(" ".join(args[1:]))
            if not res["ok"]:
                await self.g.reply(event, f"@{who} {res['message']}")
            return
        if mod and first in ("cancel", "refund"):
            res = await self.cancel()
            if not res["ok"]:
                await self.g.reply(event, f"@{who} {res['message']}")
            return
        p = self.p
        if not p:
            await self.g.reply(event, f"@{who} no prediction is open right now.")
            return
        if len(args) < 2:
            opts = " · ".join(f"{i + 1}. {o}" for i, o in enumerate(p["options"]))
            await self.g.reply(event, f"@{who} {p['question']} {opts} — {self.g.prefix()}{c['command']} 1 50")
            return
        await self.bet(event, args, c)

    async def open(self, question: str, options: List[str]) -> Dict[str, Any]:
        if self.p and self.p["state"] in ("open", "locked"):
            return {"ok": False, "message": "a prediction is already running."}
        question = (question or "").strip()[:120]
        if not question:
            return {"ok": False, "message": f"{self.g.prefix()}predict open Question? | A | B"}
        options = [o[:40] for o in options][:9] or ["Yes", "No"]
        if len(options) < 2:
            options.append("No" if options[0].lower() != "no" else "Yes")
        c = self.g.cfg["predict"]
        self.p = {"question": question, "options": options, "bets": {}, "state": "open", "opened": self.g.now(),
                  "lock_at": self.g.now() + c["auto_lock_sec"] if c["auto_lock_sec"] else None}
        await self.show()
        await self.g.announce(f"🔮 {question} " + " · ".join(f"{i + 1}. {o}" for i, o in enumerate(options))
                              + f" — {self.g.prefix()}{c['command']} 1 50")
        return {"ok": True, "message": "prediction open."}

    async def bet(self, event: ChatEvent, args, c) -> None:
        p = self.p
        who = speaker(event.user)
        if p["state"] != "open":
            await self.g.reply(event, f"@{who} bets are locked.")
            return
        if not await self.g.need_points(event, "Predicting"):
            return
        uid = await self.g.uid(event.user)
        bal = await self.g.balance(uid)
        # "!predict 1 50", "!predict yes 50", "!predict 50 yes"
        opt = _match_option(args[0], p["options"])
        amt_word = args[1]
        if opt is None or (args[0].isdigit() and int(args[0]) > len(p["options"])):
            opt, amt_word = _match_option(args[1], p["options"]), args[0]
        if opt is None:
            await self.g.reply(event, f"@{who} pick 1-{len(p['options'])}.")
            return
        amount = parse_amount(amt_word, bal, c["min_bet"], c["max_bet"])
        uk = user_key(event.user)
        mine = p["bets"].get(uk)
        if mine and mine["option"] != opt:
            await self.g.reply(event, f"@{who} you're already on {p['options'][mine['option']]}.")
            return
        have = mine["amount"] if mine else 0
        if amount is None or amount < c["min_bet"]:
            await self.g.reply(event, f"@{who} bet at least {c['min_bet']}.")
            return
        amount = min(amount, c["max_bet"] - have)
        if amount <= 0:
            await self.g.reply(event, f"@{who} the most you can bet is {c['max_bet']}.")
            return
        ok, bal = await self.g.spend(uid, amount, "prediction bet")
        if not ok:
            await self.g.reply(event, f"@{who} you have {bal} points.")
            return
        p["bets"][uk] = {"uid": uid, "ref": user_ref(event.user), "option": opt, "amount": have + amount}
        await self.show()

    def pots(self) -> List[Dict[str, int]]:
        p = self.p
        out = [{"pot": 0, "people": 0} for _ in p["options"]]
        for b in p["bets"].values():
            out[b["option"]]["pot"] += b["amount"]
            out[b["option"]]["people"] += 1
        return out

    async def show(self, winner: Optional[int] = None, footer: str = "") -> None:
        p = self.p
        c = self.g.cfg["predict"]
        pots = self.pots()
        total = max(1, sum(x["pot"] for x in pots))
        lines = [{"key": str(i + 1), "label": f"{i + 1}. {o}", "value": pots[i]["pot"],
                  "pct": round(pots[i]["pot"] / total, 3),
                  "note": f"{fmt_points(pots[i]['pot'])} pts · {pots[i]['people']}", "win": winner == i}
                 for i, o in enumerate(p["options"])]
        state = {"open": "open", "locked": "locked"}.get(p["state"], "closed")
        if not footer:
            footer = (f"{self.g.prefix()}{c['command']} 1 50" if state == "open"
                      else "Locked — waiting for the result" if state == "locked" else "")
        await self.g.board("predict", kind="bars", title=f"🔮 {p['question']}", lines=lines, footer=footer,
                           state=state, ends_at=p.get("lock_at") if state == "open" else None)

    async def lock(self) -> Dict[str, Any]:
        if not self.p or self.p["state"] != "open":
            return {"ok": False, "message": "no open prediction."}
        self.p["state"] = "locked"
        await self.show()
        await self.g.announce(f"🔒 Bets are locked: {self.p['question']}")
        return {"ok": True, "message": "locked."}

    async def resolve(self, word: str) -> Dict[str, Any]:
        p = self.p
        if not p or p["state"] not in ("open", "locked"):
            return {"ok": False, "message": "no prediction to settle."}
        opt = _match_option(word, p["options"])
        if opt is None:
            return {"ok": False, "message": f"which one won? 1-{len(p['options'])}"}
        pot = sum(b["amount"] for b in p["bets"].values())
        winners = [b for b in p["bets"].values() if b["option"] == opt]
        p["state"] = "done"
        if not winners:
            for b in p["bets"].values():
                await self.g.give(b["uid"], b["amount"], "prediction refund (no winners)")
            await self.show(opt, f"{p['options'][opt]} — nobody picked it, bets refunded")
            await self.g.announce(f"🔮 {p['options'][opt]}! Nobody picked it, so everyone gets their points back.")
            self.p = None
            return {"ok": True, "winners": 0}
        stake = sum(b["amount"] for b in winners)
        paid, best = 0, None
        for b in winners:
            share = pot * b["amount"] // stake
            b["won"] = share
            paid += share
            if best is None or share > best["won"]:
                best = b
        best["won"] += pot - paid        # rounding leftovers
        for b in winners:
            await self.g.give(b["uid"], b["won"], "prediction win")
        await self.show(opt, f"{p['options'][opt]} wins!")
        await self.g.play("confetti", {"count": 100}, label="Prediction", reaction="predict")
        name = best["ref"]["display_name"].lstrip("@")
        await self.g.announce(f"🔮 {p['options'][opt]} wins! {len(winners)} "
                              f"{'person splits' if len(winners) == 1 else 'people split'} {fmt_points(pot)} points. "
                              f"Biggest win: @{name} +{fmt_points(best['won'])}")
        self.p = None
        return {"ok": True, "winners": len(winners), "pot": pot}

    async def cancel(self) -> Dict[str, Any]:
        p = self.p
        if not p or p["state"] not in ("open", "locked"):
            return {"ok": False, "message": "no prediction to cancel."}
        for b in p["bets"].values():
            await self.g.give(b["uid"], b["amount"], "prediction cancelled")
        p["state"] = "done"
        await self.show(None, "Cancelled — points refunded")
        await self.g.announce("🔮 Prediction cancelled. Everyone got their points back.")
        self.p = None
        return {"ok": True}

    async def tick(self, now: float) -> None:
        p = self.p
        if p and p["state"] == "open" and p.get("lock_at") and now >= p["lock_at"]:
            await self.lock()

    async def admin(self, action: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if action == "open":
            return await self.open(str(body.get("question") or ""), [str(o) for o in body.get("options") or [] if str(o).strip()])
        if action == "lock":
            return await self.lock()
        if action == "win":
            return await self.resolve(str(body.get("option") or ""))
        if action == "cancel":
            return await self.cancel()
        return {"ok": False, "error": "unknown action"}

    def status(self):
        p = self.p
        if not p:
            return {"open": False}
        return {"open": True, "state": p["state"], "question": p["question"], "options": p["options"],
                "pots": self.pots()}


class Duel(Feature):
    """!duel @name 50 -> they !accept -> coin flip, winner takes both stakes and throws at the loser."""

    KEY = "duel"

    def __init__(self, g):
        super().__init__(g)
        self.pending: Dict[str, Dict[str, Any]] = {}     # challenged name key -> duel

    def commands(self, c):
        return {c["command"]: self.cmd, c["accept_command"]: self.accept, c["decline_command"]: self.decline}

    async def cmd(self, event: ChatEvent, args, c) -> None:
        if args and args[0].lower() in ("accept", "yes"):
            return await self.accept(event, args[1:], c)
        if args and args[0].lower() in ("decline", "no"):
            return await self.decline(event, args[1:], c)
        who = speaker(event.user)
        target = next((a for a in args if a.startswith("@")), None) or next(
            (a for a in args if not a.replace(",", "").rstrip("kK").replace(".", "").isdigit() and a.lower() not in ("all", "max")), None)
        amt_word = next((a for a in args if a is not target), None)
        if not target or not amt_word:
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['command']} @name {c['min_bet']}")
            return
        if not await self.g.need_points(event, "Duelling"):
            return
        tkey = name_key(target)
        if tkey in (name_key(event.user.username), name_key(event.user.display_name)):
            await self.g.reply(event, f"@{who} you can't duel yourself.")
            return
        uk = user_key(event.user)
        if any(d["from_key"] == uk for d in self.pending.values()):
            await self.g.reply(event, f"@{who} you already have a duel waiting.")
            return
        if tkey in self.pending:
            await self.g.reply(event, f"@{target.lstrip('@')} already has a duel waiting.")
            return
        wait = self.g.gate.remaining(f"duel|{uk}", c["cooldown_sec"])
        if wait > 0:
            await self.g.reply(event, f"@{who} duel again in {int(wait) + 1}s.")
            return
        uid = await self.g.uid(event.user)
        bal = await self.g.balance(uid)
        amount = parse_amount(amt_word, bal, c["min_bet"], c["max_bet"])
        if amount is None or amount < c["min_bet"] or amount > c["max_bet"]:
            await self.g.reply(event, f"@{who} duels are {c['min_bet']}-{c['max_bet']} points.")
            return
        ok, bal = await self.g.spend(uid, amount, "duel stake")
        if not ok:
            await self.g.reply(event, f"@{who} you have {bal} points.")
            return
        self.g.gate.touch(f"duel|{uk}")
        self.pending[tkey] = {"from": user_ref(event.user), "from_key": uk, "uid": uid, "amount": amount,
                              "target": target.lstrip("@"), "expires": self.g.now() + c["accept_sec"]}
        p = self.g.prefix()
        await self.g.reply(event, f"⚔️ @{target.lstrip('@')} — @{who} challenges you to a {fmt_points(amount)}-point duel! "
                                  f"{p}{c['accept_command']} or {p}{c['decline_command']} ({int(c['accept_sec'])}s)")

    def _mine(self, event: ChatEvent) -> Optional[str]:
        for k in (name_key(event.user.username), name_key(event.user.display_name)):
            if k in self.pending:
                return k
        return None

    async def accept(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        k = self._mine(event)
        if not k:
            await self.g.reply(event, f"@{who} nobody has challenged you.")
            return
        d = self.pending[k]
        uid = await self.g.uid(event.user)
        ok, bal = await self.g.spend(uid, d["amount"], "duel stake")
        if not ok:
            await self.g.reply(event, f"@{who} you need {d['amount']} points (you have {bal}).")
            return
        self.pending.pop(k, None)
        me = user_ref(event.user)
        if self.g.rng.random() < 0.5:
            win_ref, win_uid, lose_ref = d["from"], d["uid"], me
        else:
            win_ref, win_uid, lose_ref = me, uid, d["from"]
        pot = d["amount"] * 2
        await self.g.give(win_uid, pot, "duel win")
        await self.g.play("throw", {"object": c["loser_object"], "impact": "splat"}, from_user=win_ref,
                          target={"type": "user", "name": lose_ref["username"]}, label="Duel", reaction="duel")
        await self.g.announce(f"⚔️ @{win_ref['display_name'].lstrip('@')} beats @{lose_ref['display_name'].lstrip('@')} "
                              f"and takes {fmt_points(pot)} points!")

    async def decline(self, event: ChatEvent, args, c) -> None:
        k = self._mine(event)
        if not k:
            return
        d = self.pending.pop(k)
        await self.g.give(d["uid"], d["amount"], "duel declined")
        await self.g.reply(event, f"@{d['from']['display_name'].lstrip('@')} @{speaker(event.user)} "
                                  f"declined the duel. Points refunded.")

    async def tick(self, now: float) -> None:
        for k, d in list(self.pending.items()):
            if now >= d["expires"]:
                self.pending.pop(k, None)
                await self.g.give(d["uid"], d["amount"], "duel expired")
                await self.g.announce(f"@{d['from']['display_name'].lstrip('@')} @{d['target']} didn't answer. "
                                      f"Points refunded.")

    def status(self):
        return {"waiting": len(self.pending)}


class Slots(Feature):
    """Three reels. About 93% comes back on average; big wins set off confetti."""

    KEY = "slots"
    REELS = [("🍒", 30), ("🍋", 24), ("🔔", 16), ("⭐", 12), ("💎", 6), ("7️⃣", 3)]
    TRIPLE = {"🍒": 4, "🍋": 8, "🔔": 15, "⭐": 25, "💎": 60, "7️⃣": 200}
    CHERRY_PAIR = 1.5
    OTHER_PAIR = 0.5

    def commands(self, c):
        return {c["command"]: self.cmd}

    def spin(self) -> List[str]:
        syms = [s for s, _ in self.REELS]
        weights = [w for _, w in self.REELS]
        return [self.g.rng.choices(syms, weights)[0] for _ in range(3)]

    @classmethod
    def multiplier(cls, reels: List[str]) -> float:
        a, b, c = reels
        if a == b == c:
            return float(cls.TRIPLE[a])
        pairs = [s for s in set(reels) if reels.count(s) == 2]
        if pairs:
            return cls.CHERRY_PAIR if pairs[0] == "🍒" else cls.OTHER_PAIR
        return 0.0

    async def cmd(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        if not args:
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['command']} {c['min_bet']}-{c['max_bet']}")
            return
        if not await self.g.need_points(event, "Slots"):
            return
        uk = user_key(event.user)
        wait = self.g.gate.remaining(f"slots|{uk}", c["cooldown_sec"])
        if wait > 0:
            await self.g.reply(event, f"@{who} the machine is warm — {int(wait) + 1}s.")
            return
        uid = await self.g.uid(event.user)
        bal = await self.g.balance(uid)
        bet = parse_amount(args[0], bal, c["min_bet"], c["max_bet"])
        if bet is None or bet < c["min_bet"] or bet > c["max_bet"]:
            await self.g.reply(event, f"@{who} bets are {c['min_bet']}-{c['max_bet']}.")
            return
        ok, bal = await self.g.spend(uid, bet, "slots")
        if not ok:
            await self.g.reply(event, f"@{who} you have {bal} points.")
            return
        self.g.gate.touch(f"slots|{uk}")
        reels = self.spin()
        mult = self.multiplier(reels)
        win = int(bet * mult)
        if win:
            bal = await self.g.give(uid, win, "slots win")
        show = " | ".join(reels)
        if mult >= 25:
            await self.g.play_list([{"effect": "fireworks", "params": {"count": 6}},
                                    {"effect": "confetti", "params": {"count": 200}}],
                                   from_user=user_ref(event.user), label="Jackpot", reaction="slots")
            text = f"JACKPOT! +{fmt_points(win)}"
        elif mult >= 4:
            await self.g.play("confetti", {"count": 90}, from_user=user_ref(event.user), label="Slots", reaction="slots")
            text = f"win! +{fmt_points(win)}"
        elif mult >= 1:
            text = f"+{fmt_points(win)}"
        elif mult > 0:
            text = f"half back ({fmt_points(win)})"
        else:
            text = f"no luck (-{fmt_points(bet)})"
        await self.g.reply(event, f"@{who} 🎰 {show} — {text} · {fmt_points(bal)} pts")


class Heist(Feature):
    """!heist 50 starts a crew; !join 50 joins. After the join time the story plays out."""

    KEY = "heist"

    def __init__(self, g):
        super().__init__(g)
        self.h: Optional[Dict[str, Any]] = None
        self.running = False

    def commands(self, c):
        return {c["command"]: self.start, c["join_command"]: self.join}

    async def start(self, event: ChatEvent, args, c) -> None:
        if self.h:
            return await self.join(event, args, c)
        who = speaker(event.user)
        if self.running:
            return
        if not args:
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['command']} {c['min_bet']}-{c['max_bet']}")
            return
        if not await self.g.need_points(event, "A heist"):
            return
        wait = self.g.gate.remaining("heist", c["cooldown_sec"])
        if wait > 0:
            await self.g.reply(event, f"@{who} the city is on alert — next heist in {int(wait // 60) + 1} min.")
            return
        self.h = {"crew": {}, "ends": self.g.now() + c["join_sec"], "stake": 0}
        if await self._add(event, args[0], c):
            p = self.g.prefix()
            await self.g.announce(f"💼 @{who} is planning a heist! {p}{c['join_command']} <points> within "
                                  f"{int(c['join_sec'])}s to get in.")
        else:
            self.h = None

    async def join(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        if not self.h:
            if not self.running:
                await self.g.reply(event, f"@{who} no heist is forming. {self.g.prefix()}{c['command']} <points> starts one.")
            return
        if user_key(event.user) in self.h["crew"]:
            return
        if not await self.g.need_points(event, "A heist"):
            return
        await self._add(event, args[0] if args else str(self.h["stake"]), c)

    async def _add(self, event: ChatEvent, word: str, c) -> bool:
        who = speaker(event.user)
        uid = await self.g.uid(event.user)
        bal = await self.g.balance(uid)
        amount = parse_amount(word, bal, c["min_bet"], c["max_bet"])
        if amount is None or amount < c["min_bet"] or amount > c["max_bet"]:
            await self.g.reply(event, f"@{who} stakes are {c['min_bet']}-{c['max_bet']} points.")
            return False
        ok, bal = await self.g.spend(uid, amount, "heist stake")
        if not ok:
            await self.g.reply(event, f"@{who} you have {bal} points.")
            return False
        self.h["crew"][user_key(event.user)] = {"uid": uid, "ref": user_ref(event.user), "stake": amount}
        self.h["stake"] = self.h["stake"] or amount
        await self.show(c)
        return True

    async def show(self, c, state="open", results: Optional[Dict[str, int]] = None, footer: str = ""):
        h = self.h
        crew = list(h["crew"].items())
        top = max([m["stake"] for _, m in crew] or [1])
        lines = []
        for k, m in crew[:12]:
            note = f"{fmt_points(m['stake'])}"
            if results is not None:
                r = results.get(k, 0)
                note = f"+{fmt_points(r)}" if r > 0 else "caught 🚨"
            lines.append({"key": k, "label": m["ref"]["display_name"].lstrip("@"), "value": m["stake"],
                          "pct": round(m["stake"] / top, 3), "note": note,
                          "win": bool(results and results.get(k, 0) > 0)})
        if len(crew) > 12:
            lines.append({"key": "more", "label": f"+{len(crew) - 12} more", "value": 0, "pct": 0, "note": ""})
        await self.g.board("heist", kind="list", title=f"💼 Heist crew ({len(crew)})", lines=lines,
                           footer=footer or f"{self.g.prefix()}{c['join_command']} <points>", state=state,
                           ends_at=h["ends"] if state == "open" else None)

    def chance(self, n: int) -> float:
        c = self.g.cfg["heist"]
        return min(c["max_success"], c["base_success"] + c["per_member"] * max(0, n - 1))

    async def tick(self, now: float) -> None:
        if not self.h or now < self.h["ends"]:
            return
        c = self.g.cfg["heist"]
        h = self.h
        crew = h["crew"]
        n = len(crew)
        self.running = True
        self.g.gate.touch("heist")
        await self.show(c, "locked", footer="The heist is on…")
        success = self.g.rng.random() < self.chance(n)
        results: Dict[str, int] = {}
        for k, m in crew.items():
            caught = (not success) or self.g.rng.random() < c["caught_chance"]
            results[k] = 0 if caught else int(m["stake"] * c["payout"])
        await self.g.announce(f"💼 The crew of {n} slips into the vault…")

        async def middle():
            await self.g.announce("🔓 The lock clicks open…" if success else "🚨 Alarms! Run!")
            if not success:
                await self.g.play("lights", {"mode": "police", "duration_sec": 4}, label="Heist", reaction="heist")

        async def end():
            got = [crew[k] for k, v in results.items() if v > 0]
            for k, v in results.items():
                if v > 0:
                    await self.g.give(crew[k]["uid"], v, "heist haul")
            self.h = h
            if got:
                total = sum(results.values())
                await self.show(c, "closed", results, footer=f"{len(got)} got away with {fmt_points(total)} points")
                await self.g.play_list([{"effect": "confetti", "params": {"count": 140}},
                                        {"effect": "fireworks", "params": {"count": 4}}],
                                       crowd=[m["ref"] for m in got], label="Heist", reaction="heist")
                names = ", ".join("@" + m["ref"]["display_name"].lstrip("@") for m in got[:5])
                await self.g.announce(f"💰 Clean getaway! {names}{' …' if len(got) > 5 else ''} split "
                                      f"{fmt_points(total)} points.")
            else:
                await self.show(c, "closed", results, footer="Everyone got caught")
                await self.g.announce("🚓 The whole crew got caught. The stakes are gone.")
            self.h = None
            self.running = False

        self.h = None
        self.g.later(3, middle)
        self.g.later(6, end)

    def status(self):
        return {"forming": bool(self.h), "crew": len(self.h["crew"]) if self.h else 0, "running": self.running}
