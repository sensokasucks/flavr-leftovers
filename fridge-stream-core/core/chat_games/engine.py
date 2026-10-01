"""ChatGames — the chat-driven crowd moments and games (see docs/CHAT_GAMES.md).

Core owns every rule here, like chat reactions: who can do what, cooldowns, the points
ledger (source="game"), timers. What people see goes out two ways:
  - effects through the reaction path (`ReactionEngine.play`), so Stream Rooms or the
    fallback overlay draw them,
  - "board" packets (polls, predictions, the hype meter, heists, trivia ...) that the
    reply screen, Stream Rooms' board and /overlay/replies.html draw:

    {"type":"board","data":{id, kind, title, lines:[{key,label,value,pct,note,win}],
                            footer, ends_at, state:"open"|"locked"|"closed", ts}}
    {"type":"board_clear","data":{id}}
    new sockets get {"type":"board_history","data":[...open boards...]}

`tick()` runs every half second from main.py and does everything time-based, so tests can
drive the clock (`now=` in the constructor).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from core.models import ChatEvent, ChatUser, PermissionLevel

from .config import normalize_config

log = logging.getLogger("core.chat_games")

ReplyFn = Callable[[Optional[ChatEvent], str], Awaitable[None]]
BroadcastFn = Callable[[dict], Awaitable[None]]
Handler = Callable[[ChatEvent, List[str], Dict[str, Any]], Awaitable[None]]


def speaker(user: ChatUser) -> str:
    return (user.display_name or user.username or "").lstrip("@")


def user_key(user: ChatUser) -> str:
    return f"{user.platform.value}:{(user.id or user.username or '').lower()}"


def name_key(name: Any) -> str:
    """Names compare without case, "@", spaces, _ - or dots (same as reaction targets)."""
    return "".join(ch for ch in str(name or "").strip().lower() if ch not in " _-.@\t")


def user_ref(user: ChatUser) -> Dict[str, Any]:
    return {
        "platform": user.platform.value,
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "color": user.color,
        "profile_image_url": user.profile_image_url,
    }


def parse_amount(word: Any, balance: Optional[int], lo: int, hi: int) -> Optional[int]:
    """"50", "1k", "all" (= as much as allowed) -> points, or None."""
    w = str(word or "").strip().lower().replace(",", "")
    if not w:
        return None
    if w in ("all", "allin", "max"):
        if balance is None:
            return None
        return max(0, min(int(balance), hi))
    mult = 1
    if w.endswith("k"):
        mult, w = 1000, w[:-1]
    try:
        n = int(float(w) * mult)
    except ValueError:
        return None
    return n


def fmt_points(n: int) -> str:
    return f"{int(n):,}"


def clock(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class Gate:
    """Cooldowns on the engine's clock (tests move the clock)."""

    def __init__(self, now: Callable[[], float]):
        self._now = now
        self._last: Dict[str, float] = {}

    def remaining(self, key: str, cooldown_sec: float) -> float:
        cd = float(cooldown_sec or 0)
        if cd <= 0 or key not in self._last:
            return 0.0
        return max(0.0, cd - (self._now() - self._last[key]))

    def allow(self, key: str, cooldown_sec: float) -> bool:
        return self.remaining(key, cooldown_sec) <= 0

    def touch(self, key: str, at: Optional[float] = None) -> None:
        self._last[key] = self._now() if at is None else at


class ChatGames:
    SAVE_FILE = "chat_games.json"

    def __init__(
        self,
        get_config: Callable[[], dict],
        store=None,
        perms=None,
        reactions=None,
        data_dir: Optional[Path] = None,
        config_dir: Optional[Path] = None,
        reply: Optional[ReplyFn] = None,
        broadcast: Optional[BroadcastFn] = None,
        groups_active: Optional[Callable[[], Iterable[str]]] = None,
        command_prefix: Callable[[], str] | str = "!",
        now: Optional[Callable[[], float]] = None,
        rng: Optional[random.Random] = None,
    ):
        from .crowd import Combos, Hype, Launch, Tug
        from .regulars import Claim, Seats, Stage, Streaks
        from .wagers import Duel, Heist, Predict, Slots
        from .watch import Moments, Poll, Rate, Requests, Trivia

        self._get_config = get_config
        self.store = store
        self.perms = perms
        self.reactions = reactions
        self.data_dir = Path(data_dir) if data_dir else None
        self.config_dir = Path(config_dir) if config_dir else None
        self._reply = reply
        self._broadcast = broadcast
        self._groups_active = groups_active
        self._prefix = command_prefix
        self.now = now or time.time
        self.rng = rng or random.Random()
        self.gate = Gate(self.now)
        self.boards: Dict[str, Dict[str, Any]] = {}
        self._board_drop: Dict[str, float] = {}         # id -> when to clear a closed board
        self._jobs: List[Tuple[float, int, Callable[[], Awaitable[None]]]] = []
        self._job_seq = 0
        self._stream: Optional[Dict[str, Any]] = None
        self._stream_checked = 0.0
        self._cfg_cache: Optional[Dict[str, Any]] = None
        self._cfg_at = 0.0
        self._dirty = False
        self.saved: Dict[str, Any] = self._load()
        self.stats = {"commands": 0, "combos": 0, "points_in": 0, "points_out": 0}
        # features (order = the order commands are looked up)
        self.combos = Combos(self)
        self.hype = Hype(self)
        self.tug = Tug(self)
        self.launch = Launch(self)
        self.claim = Claim(self)
        self.streaks = Streaks(self)
        self.seats = Seats(self)
        self.predict = Predict(self)
        self.duel = Duel(self)
        self.slots = Slots(self)
        self.heist = Heist(self)
        self.trivia = Trivia(self)
        self.poll = Poll(self)
        self.rate = Rate(self)
        self.requests = Requests(self)
        self.moments = Moments(self)
        self.stage = Stage(self)
        self.features = [self.stage, self.combos, self.hype, self.tug, self.launch, self.claim, self.streaks, self.seats,
                         self.predict, self.duel, self.slots, self.heist, self.trivia, self.poll, self.rate,
                         self.requests, self.moments]

    # ---------------- config ----------------

    @property
    def cfg(self) -> Dict[str, Any]:
        t = time.monotonic()
        if self._cfg_cache is None or t - self._cfg_at > 1.0:
            full = self._get_config() or {}
            self._cfg_cache = normalize_config(full.get("chat_games"))
            self._cfg_at = t
        return self._cfg_cache

    def invalidate(self) -> None:
        """After an admin save: read the settings again right away."""
        self._cfg_cache = None

    def prefix(self) -> str:
        p = self._prefix() if callable(self._prefix) else self._prefix
        return p or "!"

    def active(self) -> bool:
        if not self.cfg["enabled"]:
            return False
        if self._groups_active is not None:
            try:
                return "chat_games" in set(self._groups_active())
            except Exception:
                return True
        return True

    def on(self, feature: str) -> bool:
        block = self.cfg.get(feature)
        return self.active() and isinstance(block, dict) and bool(block.get("enabled"))

    def points_on(self) -> bool:
        full = self._get_config() or {}
        return bool((full.get("points") or {}).get("enabled")) and self.store is not None

    # ---------------- chat ----------------

    def command_table(self) -> Dict[str, Tuple[Any, Handler]]:
        table: Dict[str, Tuple[Any, Handler]] = {}
        for f in self.features:
            if not self.on(f.KEY):
                continue
            for name, handler in f.commands(self.cfg[f.KEY]).items():
                if name:
                    table.setdefault(name, (f, handler))
        return table

    def command_names(self) -> List[str]:
        return sorted(self.command_table()) if self.active() else []

    async def handle_chat(self, event: ChatEvent, command_taken: bool = False) -> bool:
        """Watches every message (combos, hype); runs a game command unless someone else
        (a chat command or a reaction) already took it. True when it ran a command."""
        if "system" in (event.user.badges or []):
            return False
        if not self.active():
            return False
        await self.observe_user(event)
        for f in (self.combos, self.hype):
            if self.on(f.KEY):
                try:
                    await f.observe(event)
                except Exception:
                    log.exception("%s observe failed", f.KEY)
        if not event.is_command or command_taken:
            return False
        name = (event.command_name or "").lower()
        hit = self.command_table().get(name)
        if not hit:
            return False
        feature, handler = hit
        self.stats["commands"] += 1
        try:
            await handler(event, list(event.args or []), self.cfg[feature.KEY])
        except Exception:
            log.exception("chat game %s failed: %s", feature.KEY, event.message)
        return True

    async def observe_user(self, event: ChatEvent) -> None:
        """Attendance for streaks / titles (once per person per stream)."""
        if not self.store or not self.on("streak"):
            return
        try:
            await self.streaks.observe(event)
        except Exception:
            log.exception("attendance failed")

    def title_for(self, user: ChatUser) -> str:
        """Regular's title for name tags ("" when none / off)."""
        if not self.on("streak") or not self.cfg["streak"]["show_titles"]:
            return ""
        return self.streaks.cached_title(user)

    def title_by_name(self, platform: str, username: str) -> str:
        if not self.on("streak") or not self.cfg["streak"]["show_titles"]:
            return ""
        return self.streaks.title_by_name(platform, username)

    # ---------------- helpers for features ----------------

    def is_mod(self, user: ChatUser) -> bool:
        if user.is_mod:
            return True
        return bool(self.perms and (self.perms.has_permission(user, PermissionLevel.MOD)
                                    or self.perms.has_permission(user, PermissionLevel.ADMIN)))

    async def reply(self, event: Optional[ChatEvent], text: str) -> None:
        if not text or not self._reply or not self.cfg["replies"]:
            return
        try:
            await self._reply(event, text)
        except Exception:
            log.exception("chat game reply failed")

    async def announce(self, text: str) -> None:
        await self.reply(None, text)

    async def play(self, effect: str, params: Optional[Dict[str, Any]] = None, **kw) -> Optional[str]:
        if self.reactions is None:
            return None
        try:
            return await self.reactions.play(effect, params or {}, **kw)
        except Exception:
            log.exception("chat game effect %s failed", effect)
            return None

    async def play_list(self, effects: List[Dict[str, Any]], scale: float = 1.0, **kw) -> int:
        """Plays [{effect, params}] together; numbers named count are scaled."""
        played = 0
        for e in effects or []:
            params = dict(e.get("params") or {})
            if scale != 1.0 and isinstance(params.get("count"), (int, float)):
                params["count"] = max(1, int(round(params["count"] * scale)))
            if await self.play(str(e.get("effect")), params, **kw):
                played += 1
        return played

    # points ------------------------------------------------------------

    async def uid(self, user: ChatUser) -> Optional[int]:
        if not self.store:
            return None
        return await self.store.get_or_create_user(user.platform.value, user.id, user.username, user.display_name)

    async def balance(self, uid: int) -> int:
        u = await self.store.get_user(uid)
        return int((u or {}).get("points") or 0)

    async def spend(self, uid: int, amount: int, reason: str) -> Tuple[bool, int]:
        """All or nothing. (ok, balance after / balance now)."""
        amount = int(amount)
        if amount <= 0:
            return True, await self.balance(uid)
        got, bal = await self.store.spend_points(uid, amount, 1, reason, "game")
        if got:
            self.stats["points_in"] += amount
        return bool(got), int(bal)

    async def give(self, uid: int, amount: int, reason: str) -> int:
        amount = int(amount)
        if amount == 0:
            return await self.balance(uid)
        res = await self.store.adjust_points(uid, amount, reason, "game")
        if amount > 0:
            self.stats["points_out"] += amount
        return int(res.get("balance") or 0)

    async def need_points(self, event: ChatEvent, what: str) -> bool:
        """False (and says so) when points are off."""
        if self.points_on():
            return True
        await self.reply(event, f"@{speaker(event.user)} {what} needs points, and points are off.")
        return False

    # streams -----------------------------------------------------------

    async def stream(self) -> Dict[str, Any]:
        """{id, started} of this stream (chat quiet for streak.gap_hours = a new stream)."""
        now = self.now()
        if self._stream and now - self._stream_checked < 60:
            return self._stream
        gap = float(self.cfg["streak"]["gap_hours"]) * 3600
        if self.store:
            self._stream = await self.store.current_stream(gap, now)
        elif not self._stream or now - self._stream_checked > gap:
            self._stream = {"id": 0, "started": now, "new": True}
        self._stream_checked = now
        return self._stream

    async def new_stream(self) -> Dict[str, Any]:
        """Admin "Start a new stream" (streaks, claims and moments count from here)."""
        now = self.now()
        if self.store:
            self._stream = await self.store.current_stream(0, now, force_new=True)
        else:
            self._stream = {"id": int((self._stream or {}).get("id", 0)) + 1, "started": now, "new": True}
        self._stream_checked = now
        self.streaks.forget()
        return self._stream

    # boards ------------------------------------------------------------

    async def board(self, bid: str, **data) -> Dict[str, Any]:
        """Shows / updates a board. state "closed" keeps it up for board_hold_sec, then clears."""
        b = {"id": bid, "kind": "bars", "title": "", "lines": [], "footer": "", "ends_at": None,
             "state": "open", **data, "ts": self.now()}
        self.boards[bid] = b
        if b["state"] == "closed":
            self._board_drop[bid] = self.now() + float(data.get("hold", self.cfg["board_hold_sec"]))
        else:
            self._board_drop.pop(bid, None)
        await self._send({"type": "board", "data": b})
        return b

    async def clear_board(self, bid: str) -> None:
        self._board_drop.pop(bid, None)
        if self.boards.pop(bid, None) is not None:
            await self._send({"type": "board_clear", "data": {"id": bid}})

    def board_state(self) -> List[Dict[str, Any]]:
        return list(self.boards.values())

    async def _send(self, payload: dict) -> None:
        if self._broadcast:
            try:
                await self._broadcast(payload)
            except Exception:
                log.exception("board broadcast failed")

    # timers ------------------------------------------------------------

    def later(self, delay: float, fn: Callable[[], Awaitable[None]]) -> None:
        self._job_seq += 1
        self._jobs.append((self.now() + max(0.0, float(delay)), self._job_seq, fn))

    async def tick(self) -> None:
        now = self.now()
        due = sorted(j for j in self._jobs if j[0] <= now)
        if due:
            self._jobs = [j for j in self._jobs if j[0] > now]
            for _, _, fn in due:
                try:
                    await fn()
                except Exception:
                    log.exception("chat game timer failed")
        for bid, when in list(self._board_drop.items()):
            if now >= when:
                await self.clear_board(bid)
        if self.active():
            for f in self.features:
                if hasattr(f, "tick") and self.on(f.KEY):
                    try:
                        await f.tick(now)
                    except Exception:
                        log.exception("%s tick failed", f.KEY)
        if self._dirty:
            self._save()

    # persistence (requests, moments, ratings, trivia progress) --------------

    def _path(self) -> Optional[Path]:
        return self.data_dir / self.SAVE_FILE if self.data_dir else None

    def _load(self) -> Dict[str, Any]:
        p = self._path()
        if p and p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                log.exception("could not read %s", p)
        return {}

    def mark_dirty(self) -> None:
        self._dirty = True

    def tick_save(self) -> None:
        """Write pending changes now (Core shutting down)."""
        if self._dirty:
            self._save()

    def _save(self) -> None:
        self._dirty = False
        p = self._path()
        if not p:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.saved, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(p)
        except Exception:
            log.exception("could not save %s", p)

    # ---------------- admin ----------------

    def status(self) -> Dict[str, Any]:
        out = {
            "enabled": self.cfg["enabled"],
            "active": self.active(),
            "points_enabled": self.points_on(),
            "game_connected": bool(self.reactions and self.reactions.game_clients),
            "stream": self._stream,
            "boards": self.board_state(),
            "stats": dict(self.stats),
            "commands": self.command_names(),
        }
        for f in self.features:
            if hasattr(f, "status"):
                out[f.KEY] = f.status()
        return out

    async def admin_action(self, feature: str, action: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Buttons on the admin page: {feature, action, ...}."""
        if feature == "stream" and action == "new":
            s = await self.new_stream()
            return {"ok": True, "stream": s}
        if feature == "boards" and action == "clear":
            for bid in list(self.boards):
                await self.clear_board(bid)
            return {"ok": True}
        for f in self.features:
            if f.KEY == feature and hasattr(f, "admin"):
                return await f.admin(action, body or {})
        return {"ok": False, "error": f"unknown action {feature}/{action}"}


class Feature:
    """Base for one chat game."""

    KEY = ""

    def __init__(self, g: ChatGames):
        self.g = g

    def commands(self, c: Dict[str, Any]) -> Dict[str, Handler]:
        return {}
