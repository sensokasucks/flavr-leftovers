"""Watch-along: polls, ratings, requests, moments (!clip) and trivia."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.models import ChatEvent

from .engine import Feature, clock, fmt_points, speaker, user_key, user_ref
from .wagers import _split_bar

log = logging.getLogger("core.chat_games")

_DURATION = re.compile(r"^(\d{1,4})\s*(s|sec|m|min)?$", re.IGNORECASE)


def _duration(word: str) -> Optional[int]:
    m = _DURATION.match((word or "").strip())
    if not m:
        return None
    n = int(m.group(1))
    return n * 60 if (m.group(2) or "").lower().startswith("m") else n


def normalize_answer(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = " ".join(t.split())
    for art in ("the ", "a ", "an "):
        if t.startswith(art):
            t = t[len(art):]
    return t.replace(" ", "")


class Poll(Feature):
    """Mods: !poll Question? | A | B | C (| 90s), !poll end. Chat: !1 !2 !3 (or !vote 2)."""

    KEY = "poll"

    def __init__(self, g):
        super().__init__(g)
        self.p: Optional[Dict[str, Any]] = None

    def commands(self, c):
        out = {c["command"]: self.cmd}
        if self.p:
            out[c["vote_command"]] = self.vote_cmd
            for i in range(len(self.p["options"])):
                out[str(i + 1)] = self._digit(i)
        return out

    def _digit(self, i: int):
        async def vote(event, args, c):
            await self.vote(event, i)
        return vote

    async def cmd(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        if not self.g.is_mod(event.user):
            if self.p:
                await self.g.reply(event, f"@{who} {self.p['question']} — vote with "
                                          + " ".join(f"{self.g.prefix()}{i + 1}" for i in range(len(self.p['options']))))
            return
        if not args:
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['command']} Question? | A | B   ·   "
                                      f"{self.g.prefix()}{c['command']} end")
            return
        if args[0].lower() in ("end", "close", "stop"):
            res = await self.end()
            if not res["ok"]:
                await self.g.reply(event, f"@{who} {res['message']}")
            return
        parts = [p for p in _split_bar(" ".join(args)) if p]
        secs = None
        if len(parts) > 3 and _duration(parts[-1]) is not None:
            secs = _duration(parts.pop())
        res = await self.open(parts[0], parts[1:], secs)
        if not res["ok"]:
            await self.g.reply(event, f"@{who} {res['message']}")

    async def open(self, question: str, options: List[str], seconds: Optional[int] = None) -> Dict[str, Any]:
        c = self.g.cfg["poll"]
        if self.p:
            return {"ok": False, "message": "a poll is already running."}
        options = [o.strip()[:40] for o in options if o.strip()][: c["max_options"]]
        if not question.strip() or len(options) < 2:
            return {"ok": False, "message": "a poll needs a question and at least 2 options."}
        secs = c["default_sec"] if seconds is None else seconds
        self.p = {"question": question.strip()[:120], "options": options, "votes": {},
                  "ends": self.g.now() + secs if secs else None}
        await self.show()
        await self.g.announce(f"📊 {self.p['question']} " + " · ".join(
            f"{self.g.prefix()}{i + 1} {o}" for i, o in enumerate(options)))
        return {"ok": True}

    async def vote_cmd(self, event, args, c):
        if self.p and args and args[0].isdigit():
            i = int(args[0]) - 1
            if 0 <= i < len(self.p["options"]):
                await self.vote(event, i)

    async def vote(self, event: ChatEvent, i: int) -> None:
        if not self.p:
            return
        self.p["votes"][user_key(event.user)] = i
        self.p["dirty"] = True

    def counts(self) -> List[int]:
        out = [0] * len(self.p["options"])
        for i in self.p["votes"].values():
            out[i] += 1
        return out

    async def show(self, state: str = "open", footer: str = "") -> None:
        p = self.p
        counts = self.counts()
        total = max(1, sum(counts))
        best = max(counts) if counts else 0
        lines = [{"key": str(i + 1), "label": f"{i + 1}. {o}", "value": counts[i], "pct": round(counts[i] / total, 3),
                  "note": f"{counts[i]} ({round(100 * counts[i] / total)}%)",
                  "win": state == "closed" and best > 0 and counts[i] == best}
                 for i, o in enumerate(p["options"])]
        if not footer:
            footer = "Vote: " + " ".join(f"{self.g.prefix()}{i + 1}" for i in range(len(p["options"])))
        await self.g.board("poll", kind="bars", title=f"📊 {p['question']}", lines=lines, footer=footer,
                           state=state, ends_at=p["ends"] if state == "open" else None)
        p["dirty"] = False

    async def end(self) -> Dict[str, Any]:
        p = self.p
        if not p:
            return {"ok": False, "message": "no poll is running."}
        counts = self.counts()
        total = sum(counts)
        best = max(counts)
        winners = [p["options"][i] for i, n in enumerate(counts) if n == best and n > 0]
        if not winners:
            footer, text = "No votes", f"📊 Poll closed: no votes for {p['question']}"
        elif len(winners) == 1:
            footer = f"{winners[0]} wins"
            text = f"📊 {winners[0]} wins with {best} vote{'s' if best != 1 else ''} ({round(100 * best / total)}%)"
        else:
            footer = "Tie: " + " & ".join(winners)
            text = f"📊 It's a tie: {' & '.join(winners)} ({best} each)"
        await self.show("closed", footer)
        await self.g.announce(text)
        self.p = None
        return {"ok": True, "counts": counts}

    async def tick(self, now: float) -> None:
        p = self.p
        if not p:
            return
        if p["ends"] and now >= p["ends"]:
            await self.end()
        elif p.get("dirty"):
            await self.show()

    async def admin(self, action, body):
        if action == "open":
            secs = body.get("seconds")
            return await self.open(str(body.get("question") or ""), [str(o) for o in body.get("options") or []],
                                   int(secs) if str(secs or "").isdigit() else None)
        if action == "end":
            return await self.end()
        return {"ok": False, "error": "unknown action"}

    def status(self):
        p = self.p
        return {"open": bool(p), "question": p["question"] if p else "", "options": p["options"] if p else [],
                "counts": self.counts() if p else []}


class Rate(Feature):
    """!rate 1-10. The first one opens voting (or mods: !rate open Title / !rate close).
    The average shows on screen and the latest one goes into the end credits."""

    KEY = "rate"

    def __init__(self, g):
        super().__init__(g)
        self.w: Optional[Dict[str, Any]] = None

    def commands(self, c):
        return {c["command"]: self.cmd}

    async def cmd(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        first = args[0].lower() if args else ""
        if self.g.is_mod(event.user) and first in ("open", "start"):
            await self.open(" ".join(args[1:]))
            return
        if self.g.is_mod(event.user) and first in ("close", "end", "stop"):
            await self.close()
            return
        m = re.match(r"^(\d{1,2}(?:\.\d)?)(?:/10)?$", first)
        score = float(m.group(1)) if m else None
        if score is None or not 1 <= score <= 10:
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['command']} 1-10")
            return
        if not self.w:
            if not c["open_on_first"]:
                await self.g.reply(event, f"@{who} ratings aren't open right now.")
                return
            await self.open("")
        self.w["votes"][user_key(event.user)] = score
        self.w["dirty"] = True

    async def open(self, title: str, seconds: Optional[int] = None) -> Dict[str, Any]:
        c = self.g.cfg["rate"]
        if self.w:
            await self.close()
        secs = seconds or c["window_sec"]
        self.w = {"title": title.strip()[:80], "votes": {}, "ends": self.g.now() + secs}
        await self.show()
        return {"ok": True}

    def average(self) -> float:
        v = list(self.w["votes"].values())
        return round(sum(v) / len(v), 1) if v else 0.0

    async def show(self, state: str = "open") -> None:
        w = self.w
        avg = self.average()
        n = len(w["votes"])
        await self.g.board("rate", kind="rating", title=f"⭐ Rate {w['title'] or 'this'}", state=state,
                           lines=[{"key": "avg", "label": "Average", "value": avg, "pct": round(avg / 10, 3),
                                   "note": f"{avg:.1f}/10 · {n} vote{'s' if n != 1 else ''}"}],
                           footer=f"{self.g.prefix()}{self.g.cfg['rate']['command']} 1-10" if state == "open" else "",
                           ends_at=w["ends"] if state == "open" else None)
        w["dirty"] = False

    async def close(self) -> Dict[str, Any]:
        w = self.w
        if not w:
            return {"ok": False, "message": "no rating is open."}
        avg, n = self.average(), len(w["votes"])
        await self.show("closed")
        self.w = None
        if n:
            s = await self.g.stream()
            ratings = self.g.saved.setdefault("ratings", [])
            ratings.append({"title": w["title"], "avg": avg, "votes": n, "ts": self.g.now(), "stream": s.get("id")})
            del ratings[:-200]
            self.g.mark_dirty()
            await self.g.announce(f"⭐ Chat rated {w['title'] or 'it'} {avg:.1f}/10 ({n} vote{'s' if n != 1 else ''})")
        return {"ok": True, "avg": avg, "votes": n}

    def credits_line(self, stream_id: Any) -> str:
        """"Chat rated <title> 8.4 / 10" for this stream's latest rating, or ""."""
        for r in reversed(self.g.saved.get("ratings") or []):
            if r.get("stream") == stream_id:
                what = f" {r['title']}" if r.get("title") else ""
                return f"Chat rated{what} {float(r['avg']):.1f} / 10 ({r['votes']} votes)"
        return ""

    async def tick(self, now: float) -> None:
        w = self.w
        if not w:
            return
        if now >= w["ends"]:
            await self.close()
        elif w.get("dirty"):
            await self.show()

    async def admin(self, action, body):
        if action == "open":
            secs = body.get("seconds")
            return await self.open(str(body.get("title") or ""), int(secs) if str(secs or "").isdigit() else None)
        if action == "close":
            return await self.close()
        return {"ok": False, "error": "unknown action"}

    def status(self):
        w = self.w
        return {"open": bool(w), "title": w["title"] if w else "", "average": self.average() if w else 0,
                "votes": len(w["votes"]) if w else 0, "history": (self.g.saved.get("ratings") or [])[-10:][::-1]}


class Requests(Feature):
    """!request <link or title> queues it; !bump spends points to move yours up; !queue shows it."""

    KEY = "request"

    def commands(self, c):
        return {c["command"]: self.add, c["bump_command"]: self.bump, c["queue_command"]: self.queue}

    @property
    def items(self) -> List[Dict[str, Any]]:
        return self.g.saved.setdefault("requests", [])

    def _sort(self) -> None:
        self.items.sort(key=lambda r: (0 if r.get("bumped") else 1, r.get("bumped") or r["ts"]))

    async def add(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        text = " ".join(args).strip()
        if not text:
            await self.g.reply(event, f"@{who} {self.g.prefix()}{c['command']} <link or title>")
            return
        url = ""
        if re.match(r"^https?://\S+$", args[0], re.IGNORECASE):
            url = args[0][:300]
            text = " ".join(args[1:]).strip() or url
        text = text[:100]
        uk = user_key(event.user)
        if sum(1 for r in self.items if r["ukey"] == uk) >= c["max_per_user"]:
            await self.g.reply(event, f"@{who} you have {c['max_per_user']} in the queue already.")
            return
        if len(self.items) >= c["max_queue"]:
            await self.g.reply(event, f"@{who} the queue is full.")
            return
        if any((r["url"] and r["url"] == url) or r["text"].lower() == text.lower() for r in self.items):
            await self.g.reply(event, f"@{who} that's already in the queue.")
            return
        self.items.append({"id": uuid.uuid4().hex[:8], "text": text, "url": url, "ukey": uk,
                           "by": {"display_name": who, "platform": event.user.platform.value,
                                  "username": event.user.username},
                           "ts": self.g.now(), "bumped": 0})
        self._sort()
        self.g.mark_dirty()
        pos = next(i for i, r in enumerate(self.items) if r["ukey"] == uk and r["text"] == text) + 1
        tip = f" {self.g.prefix()}{c['bump_command']} moves it up ({c['bump_cost']} pts)" if (
            self.g.points_on() and c["bump_cost"]) else ""
        await self.g.reply(event, f"@{who} added: {text} (#{pos}).{tip}")

    async def bump(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        uk = user_key(event.user)
        mine = next((r for r in self.items if r["ukey"] == uk and not r.get("bumped")), None)
        if not mine:
            await self.g.reply(event, f"@{who} you have nothing to bump.")
            return
        if c["bump_cost"]:
            if not await self.g.need_points(event, "Bumping"):
                return
            uid = await self.g.uid(event.user)
            ok, bal = await self.g.spend(uid, c["bump_cost"], "request bump")
            if not ok:
                await self.g.reply(event, f"@{who} a bump costs {c['bump_cost']} — you have {bal}.")
                return
        mine["bumped"] = self.g.now()
        self._sort()
        self.g.mark_dirty()
        pos = self.items.index(mine) + 1
        await self.g.reply(event, f"@{who} bumped {mine['text']} to #{pos}.")

    async def queue(self, event: ChatEvent, args, c) -> None:
        if not self.items:
            await self.g.reply(event, f"@{speaker(event.user)} the request queue is empty.")
            return
        bits = [f"{i + 1}. {r['text']} ({r['by']['display_name']})" for i, r in enumerate(self.items[:3])]
        more = f" +{len(self.items) - 3} more" if len(self.items) > 3 else ""
        await self.g.reply(event, "Up next: " + " · ".join(bits) + more)

    async def admin(self, action, body):
        rid = str(body.get("id") or "")
        if action in ("remove", "played"):
            before = len(self.items)
            self.g.saved["requests"] = [r for r in self.items if r["id"] != rid]
            self.g.mark_dirty()
            return {"ok": len(self.items) < before}
        if action == "clear":
            self.g.saved["requests"] = []
            self.g.mark_dirty()
            return {"ok": True}
        return {"ok": False, "error": "unknown action"}

    def status(self):
        return {"queue": list(self.items)}


class Moments(Feature):
    """!clip / !moment [note] marks the stream time. Marks close together count as one."""

    KEY = "moment"

    def commands(self, c):
        return {name: self.mark for name in c["commands"]}

    @property
    def items(self) -> List[Dict[str, Any]]:
        return self.g.saved.setdefault("moments", [])

    async def mark(self, event: ChatEvent, args, c) -> None:
        who = speaker(event.user)
        uk = user_key(event.user)
        if not self.g.gate.allow(f"moment|{uk}", c["cooldown_sec"]):
            return
        self.g.gate.touch(f"moment|{uk}")
        now = self.g.now()
        s = await self.g.stream()
        note = " ".join(args).strip()[:80]
        last = self.items[-1] if self.items else None
        if last and last.get("stream") == s.get("id") and now - last["ts"] <= c["merge_sec"]:
            if who not in last["users"]:
                last["users"].append(who)
            last["count"] += 1
            if note and not last["note"]:
                last["note"] = note
            self.g.mark_dirty()
            return          # one reply per moment is enough
        m = {"id": uuid.uuid4().hex[:8], "ts": now, "offset": round(now - float(s.get("started") or now), 1),
             "stream": s.get("id"), "users": [who], "count": 1, "note": note}
        self.items.append(m)
        del self.items[:-500]
        self.g.mark_dirty()
        await self.g.reply(event, f"📌 @{who} marked {clock(m['offset'])} into the stream.")

    def csv(self) -> str:
        import io

        from core.csv_safe import SafeWriter
        import time as _t
        buf = io.StringIO()
        w = SafeWriter(buf)
        w.writerow(["stream", "stream_time", "clock_time", "people", "marked_by", "note"])
        for m in self.items:
            w.writerow([m.get("stream"), clock(m["offset"]), _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(m["ts"])),
                        m["count"], " ".join(m["users"]), m["note"]])
        return buf.getvalue()

    async def admin(self, action, body):
        if action == "clear":
            self.g.saved["moments"] = []
            self.g.mark_dirty()
            return {"ok": True}
        return {"ok": False, "error": "unknown action"}

    def status(self):
        return {"moments": list(reversed(self.items[-50:]))}


class Trivia(Feature):
    """Mods: !trivia (ask), !trivia stop. Chat: !answer <guess>. First right answer wins."""

    KEY = "trivia"

    def __init__(self, g):
        super().__init__(g)
        self.q: Optional[Dict[str, Any]] = None
        self._bank: Optional[List[Dict[str, Any]]] = None
        self._bank_mtime = None
        self.next_auto: Optional[float] = None

    def commands(self, c):
        out = {c["command"]: self.cmd}
        if self.q:
            out[c["answer_command"]] = self.answer
        return out

    def bank(self) -> List[Dict[str, Any]]:
        d = self.g.config_dir
        if not d:
            return self._bank or []
        path = d / "trivia.json"
        if not path.exists():
            path = d / "trivia.example.json"
        try:
            mt = (path, path.stat().st_mtime)
        except OSError:
            return []
        if mt != self._bank_mtime:
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                items = raw.get("questions", raw) if isinstance(raw, dict) else raw
                self._bank = [q for q in items if isinstance(q, dict) and q.get("q") and q.get("a")]
            except Exception:
                log.exception("could not read %s", path)
                self._bank = []
            self._bank_mtime = mt
        return self._bank or []

    async def cmd(self, event: ChatEvent, args, c) -> None:
        if not self.g.is_mod(event.user):
            if self.q:
                await self.g.reply(event, f"@{speaker(event.user)} ❓ {self.q['q']} — "
                                          f"{self.g.prefix()}{c['answer_command']} <guess>")
            return
        if args and args[0].lower() in ("stop", "end", "skip"):
            await self.timeout(skipped=True)
            return
        res = await self.ask()
        if not res["ok"]:
            await self.g.reply(event, f"@{speaker(event.user)} {res['message']}")

    async def ask(self) -> Dict[str, Any]:
        if self.q:
            return {"ok": False, "message": "a question is already up."}
        bank = self.bank()
        if not bank:
            return {"ok": False, "message": "no trivia questions (config/trivia.json)."}
        asked = set(self.g.saved.get("trivia_asked") or [])
        left = [i for i in range(len(bank)) if i not in asked]
        if not left:
            asked, left = set(), list(range(len(bank)))
        i = self.g.rng.choice(left)
        asked.add(i)
        self.g.saved["trivia_asked"] = sorted(asked)
        self.g.mark_dirty()
        item = bank[i]
        answers = item["a"] if isinstance(item["a"], list) else [item["a"]]
        c = self.g.cfg["trivia"]
        self.q = {"q": str(item["q"])[:200], "show": str(answers[0]), "answers": {normalize_answer(a) for a in answers},
                  "ends": self.g.now() + c["time_sec"]}
        await self.g.board("trivia", kind="question", title="❓ Trivia", state="open",
                           lines=[{"key": "q", "label": self.q["q"], "value": 0, "pct": 0, "note": ""}],
                           footer=f"{self.g.prefix()}{c['answer_command']} <guess>"
                                  + (f" · {c['points']} pts" if c["points"] and self.g.points_on() else ""),
                           ends_at=self.q["ends"])
        await self.g.announce(f"❓ {self.q['q']} — {self.g.prefix()}{c['answer_command']} <guess>")
        return {"ok": True, "question": self.q["q"]}

    async def answer(self, event: ChatEvent, args, c) -> None:
        q = self.q
        if not q or not args:
            return
        if normalize_answer(" ".join(args)) not in q["answers"]:
            return
        self.q = None
        who = speaker(event.user)
        prize = ""
        if c["points"] and self.g.points_on():
            uid = await self.g.uid(event.user)
            await self.g.give(uid, c["points"], "trivia")
            prize = f" +{fmt_points(c['points'])}"
        await self.g.play("spotlight", {"duration_sec": 6}, from_user=user_ref(event.user),
                          target={"type": "user", "name": event.user.username}, label="Trivia", reaction="trivia")
        await self.g.play("confetti", {"count": 70}, target={"type": "user", "name": event.user.username},
                          from_user=user_ref(event.user), label="Trivia", reaction="trivia")
        await self.g.board("trivia", kind="question", title="❓ Trivia", state="closed",
                           lines=[{"key": "q", "label": q["q"], "value": 0, "pct": 0, "note": ""},
                                  {"key": "a", "label": q["show"], "value": 1, "pct": 1, "note": f"@{who}", "win": True}],
                           footer=f"@{who} got it!{prize}")
        await self.g.announce(f"✅ @{who} got it: {q['show']}!{prize}")

    async def timeout(self, skipped: bool = False) -> None:
        q = self.q
        if not q:
            return
        self.q = None
        await self.g.board("trivia", kind="question", title="❓ Trivia", state="closed",
                           lines=[{"key": "q", "label": q["q"], "value": 0, "pct": 0, "note": ""},
                                  {"key": "a", "label": q["show"], "value": 1, "pct": 1, "note": "answer"}],
                           footer="Skipped" if skipped else "Time's up!")
        await self.g.announce(f"⏰ {'Skipped' if skipped else 'Time'}! It was {q['show']}.")

    async def tick(self, now: float) -> None:
        if self.q and now >= self.q["ends"]:
            await self.timeout()
        every = self.g.cfg["trivia"]["auto_every_min"]
        if every <= 0:
            self.next_auto = None
            return
        if self.next_auto is None:
            self.next_auto = now + every * 60
        elif now >= self.next_auto and not self.q:
            self.next_auto = now + every * 60
            await self.ask()

    async def admin(self, action, body):
        if action == "ask":
            return await self.ask()
        if action == "stop":
            await self.timeout(skipped=True)
            return {"ok": True}
        return {"ok": False, "error": "unknown action"}

    def status(self):
        return {"open": bool(self.q), "question": self.q["q"] if self.q else "", "bank": len(self.bank())}
