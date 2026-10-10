"""
SQLite store: chat history, unified users, cross-platform links, chat points.

All platform identities map to one internal user so points follow the person
whether they chat on Kick today or YouTube tomorrow.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import io
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from core.models import ChatEvent, Platform
from core.csv_safe import SafeWriter

log = logging.getLogger("core.store")

SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name  TEXT NOT NULL DEFAULT '',
    points        INTEGER NOT NULL DEFAULT 0,
    notes         TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS identities (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform         TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    username         TEXT NOT NULL DEFAULT '',
    display_name     TEXT NOT NULL DEFAULT '',
    last_seen        REAL NOT NULL,
    UNIQUE(platform, platform_user_id)
);

CREATE INDEX IF NOT EXISTS idx_identities_user ON identities(user_id);
CREATE INDEX IF NOT EXISTS idx_identities_username ON identities(platform, username);

CREATE TABLE IF NOT EXISTS chat_messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    platform         TEXT NOT NULL,
    platform_user_id TEXT NOT NULL DEFAULT '',
    username         TEXT NOT NULL DEFAULT '',
    display_name     TEXT NOT NULL DEFAULT '',
    message          TEXT NOT NULL,
    message_id       TEXT,
    is_command       INTEGER NOT NULL DEFAULT 0,
    timestamp        REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_platform ON chat_messages(platform);

CREATE TABLE IF NOT EXISTS points_ledger (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delta         INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'system',
    created_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ledger_user ON points_ledger(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS market_holdings (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol       TEXT NOT NULL,
    milli_shares INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON market_holdings(symbol);

-- Chat games: a "stream" starts when chat comes back after a quiet gap; attendance per stream
-- drives !streak, regular titles and the once-per-stream !claim.
CREATE TABLE IF NOT EXISTS streams (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started       REAL NOT NULL,
    last_activity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS stream_attendance (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stream_id INTEGER NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
    claimed   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, stream_id)
);
CREATE INDEX IF NOT EXISTS idx_attendance_user ON stream_attendance(user_id, stream_id DESC);

-- Red flags (core/red_flags.py): chatters kept off the overlays. platform '' = a name flagged
-- by hand on every platform; username is lower-case.
CREATE TABLE IF NOT EXISTS red_flagged (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL DEFAULT '',
    platform_user_id TEXT NOT NULL DEFAULT '',
    username         TEXT NOT NULL DEFAULT '',
    display_name     TEXT NOT NULL DEFAULT '',
    phrase           TEXT NOT NULL DEFAULT '',
    message          TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT 'phrase',
    flagged_at       REAL NOT NULL
);
"""

# chat_messages row is from a red-flagged chatter (same rule as RedFlags.is_flagged)
FLAGGED_SQL = (
    "EXISTS (SELECT 1 FROM red_flagged f WHERE (f.platform='' OR f.platform=chat_messages.platform) AND ("
    "(f.platform_user_id!='' AND f.platform_user_id=chat_messages.platform_user_id) OR "
    "(f.username!='' AND (f.username=lower(chat_messages.username) OR f.username=lower(chat_messages.display_name)))))"
)


# platform_user_id for identities created from an alert that only had a name
NAME_ID_PREFIX = "name:"

# Chat writer: wait this long after the first queued line to gather more, write at most
# CHAT_BATCH_MAX per transaction, and keep at most CHAT_QUEUE_MAX waiting (then lines are
# dropped from the database, never from the overlays).
CHAT_BATCH_WAIT = 0.25
CHAT_BATCH_MAX = 500
CHAT_QUEUE_MAX = 50_000


def _chat_row(event: ChatEvent) -> tuple:
    """chat_messages columns after user_id."""
    return (
        event.platform.value,
        event.user.id,
        event.user.username,
        event.user.display_name,
        event.message,
        event.message_id or None,
        1 if event.is_command else 0,
        event.timestamp,
    )


class Store:
    def __init__(
        self,
        db_path: Path | str,
        points_cfg: dict | None = None,
        chat_log_cfg: dict | None = None,
    ):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cfg = points_cfg or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.per_message = int(cfg.get("per_message", 1))
        self.cooldown_sec = float(cfg.get("cooldown_sec", 30))
        self.log_chat = False
        self.log_only_flagged = False   # chat_log.only_flagged: keep just red-flagged chatters' lines
        self.configure_chat_log(chat_log_cfg)
        self._last_award: dict[int, float] = {}  # user_id -> last award time
        self._lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()   # one chat batch, or one link / merge, at a time
        # (platform, platform user id) -> [user id, username, display name, last_seen written];
        # repeat chatters do no database lookup at all. Cleared when identities move (link / merge).
        self._uid_cache: dict[tuple[str, str], list] = {}
        self._uid_cache_max = 50_000
        self._days_seen: set[tuple[int, str]] = set()   # (user id, day) already in chatter_stream_days
        # Chat writer: chat lines queue up and one task writes them in batches (start_writer)
        self._queue: Optional[asyncio.Queue] = None
        self._writer_task: Optional[asyncio.Task] = None
        self._writing: Optional[asyncio.Future] = None   # the batch being written now (stop_writer waits for it)
        self._writer_conn: Optional[sqlite3.Connection] = None
        self._dropped = 0
        self._dropped_logged = 0.0
        self._init_db()

    def configure_chat_log(self, cfg: dict | None) -> None:
        """Follow ``chat_log:`` in config (admin save applies it without a restart)."""
        cfg = cfg if isinstance(cfg, dict) else {}
        self.log_chat = bool(cfg.get("enabled", False))
        self.log_only_flagged = bool(cfg.get("only_flagged", False))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        # WAL + NORMAL: a commit no longer waits for the disk (still crash-safe for the database;
        # at worst the last moment of chat is lost on a power cut)
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        last_err: Optional[Exception] = None
        for journal in ("WAL", "DELETE"):
            try:
                with self._connect() as conn:
                    try:
                        conn.execute(f"PRAGMA journal_mode={journal}")
                    except sqlite3.OperationalError:
                        if journal == "WAL":
                            raise
                    conn.executescript(SCHEMA)
                log.info("Store ready at %s (journal=%s)", self.path, journal)
                return
            except sqlite3.OperationalError as exc:
                last_err = exc
                log.warning("Store init journal=%s failed: %s", journal, exc)
                # Stale WAL leftovers on flaky filesystems
                for suffix in ("-wal", "-shm"):
                    leftover = Path(str(self.path) + suffix)
                    try:
                        leftover.unlink(missing_ok=True)
                    except OSError:
                        pass
        if last_err:
            raise last_err

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    # ------------------------------------------------------------------
    # Users / identities
    # ------------------------------------------------------------------

    def _get_or_create_user_sync(
        self,
        platform: str,
        platform_user_id: str,
        username: str,
        display_name: str,
    ) -> int:
        with self._connect() as conn:
            uid = self._get_or_create_in(conn, platform, platform_user_id, username, display_name)
            conn.commit()
        return uid

    def _remember_uid(self, platform: str, platform_user_id: str, uid: int, username: str,
                      display_name: str, now: float) -> None:
        if len(self._uid_cache) >= self._uid_cache_max:
            self._uid_cache.clear()
        self._uid_cache[(platform, platform_user_id)] = [uid, username, display_name, now]

    def forget_identities(self) -> None:
        """Identities moved between users (link / merge): look everyone up again."""
        self._uid_cache.clear()

    def _get_or_create_in(
        self,
        conn: sqlite3.Connection,
        platform: str,
        platform_user_id: str,
        username: str,
        display_name: str,
    ) -> int:
        """User id for an identity, created when new. No commit (the caller's transaction)."""
        now = time.time()
        key = (platform, platform_user_id)
        hit = self._uid_cache.get(key)
        if hit is not None:
            uid, old_name, old_display, written = hit
            # names changed, or last_seen is more than a minute old: refresh the row
            if old_name != username or old_display != (display_name or username) or now - written > 60:
                conn.execute(
                    "UPDATE identities SET username=?, display_name=?, last_seen=? "
                    "WHERE platform=? AND platform_user_id=?",
                    (username, display_name or username, now, platform, platform_user_id),
                )
                hit[1], hit[2], hit[3] = username, display_name or username, now
            return uid
        uid = self._get_or_create_uncached(conn, platform, platform_user_id, username, display_name, now)
        self._remember_uid(platform, platform_user_id, uid, username, display_name or username, now)
        return uid

    def _get_or_create_uncached(
        self,
        conn: sqlite3.Connection,
        platform: str,
        platform_user_id: str,
        username: str,
        display_name: str,
        now: float,
    ) -> int:
        row = conn.execute(
            "SELECT user_id FROM identities WHERE platform=? AND platform_user_id=?",
            (platform, platform_user_id),
        ).fetchone()
        if not row and not platform_user_id.startswith(NAME_ID_PREFIX):
            # Claim an identity an alert created by name (e.g. a Kick sub before
            # their first chat line) so the points land on this viewer.
            placeholder = NAME_ID_PREFIX + (username or "").lower()
            row = conn.execute(
                "SELECT user_id FROM identities WHERE platform=? AND platform_user_id=?",
                (platform, placeholder),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE identities SET platform_user_id=? WHERE platform=? AND platform_user_id=?",
                    (platform_user_id, platform, placeholder),
                )
        if row:
            uid = int(row["user_id"])
            conn.execute(
                "UPDATE identities SET username=?, display_name=?, last_seen=? "
                "WHERE platform=? AND platform_user_id=?",
                (username, display_name or username, now, platform, platform_user_id),
            )
            # Keep primary display name fresh if empty
            conn.execute(
                "UPDATE users SET display_name=CASE WHEN display_name='' "
                "THEN ? ELSE display_name END, updated_at=? WHERE id=?",
                (display_name or username, now, uid),
            )
            return uid

        cur = conn.execute(
            "INSERT INTO users (display_name, points, created_at, updated_at) VALUES (?,?,?,?)",
            (display_name or username, 0, now, now),
        )
        uid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO identities (user_id, platform, platform_user_id, username, display_name, last_seen) "
            "VALUES (?,?,?,?,?,?)",
            (uid, platform, platform_user_id, username, display_name or username, now),
        )
        return uid

    async def get_or_create_user(
        self, platform: str, platform_user_id: str, username: str, display_name: str = ""
    ) -> int:
        hit = self._uid_cache.get((platform, platform_user_id))
        if hit is not None and hit[1] == username:
            return int(hit[0])   # a repeat chatter: no database trip
        return await self._run(
            self._get_or_create_user_sync, platform, platform_user_id, username, display_name
        )

    def _user_for_alert_sync(
        self, platform: str, platform_user_id: str, username: str, display_name: str
    ) -> int:
        """Platform id when the alert has one; else an identity with that name on the
        platform; else a new `name:` placeholder identity the viewer claims on first chat."""
        if platform_user_id:
            return self._get_or_create_user_sync(platform, platform_user_id, username, display_name)
        name = (username or "").lower().strip()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM identities WHERE platform=? AND lower(username)=? "
                "ORDER BY last_seen DESC LIMIT 1",
                (platform, name),
            ).fetchone()
        if row:
            return int(row["user_id"])
        return self._get_or_create_user_sync(platform, NAME_ID_PREFIX + name, name, display_name)

    def _has_ledger_source_sync(self, user_id: int, source: str) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM points_ledger WHERE user_id=? AND source=? LIMIT 1", (user_id, source)
            ).fetchone() is not None

    async def award_for_alert(
        self,
        platform: str,
        platform_user_id: str,
        username: str,
        display_name: str,
        delta: int,
        reason: str,
        source: str,
        once: bool = False,
    ) -> Optional[dict]:
        """Sub / follow / gift points. `once` skips viewers already paid for `source`
        (follows: unfollow + refollow must not farm points). None when nothing was paid."""
        if delta <= 0 or not (username or platform_user_id):
            return None
        uid = await self._run(
            self._user_for_alert_sync, platform, platform_user_id, username, display_name
        )
        if once and await self._run(self._has_ledger_source_sync, uid, source):
            return None
        balance = await self._run(self._award_points_sync, uid, delta, reason, source)
        return {"user_id": uid, "delta": delta, "balance": balance}

    # ------------------------------------------------------------------
    # Chat logging + points
    # ------------------------------------------------------------------

    def _log_chat_in(self, conn: sqlite3.Connection, row: tuple, user_id: int) -> None:
        conn.execute(
            "INSERT INTO chat_messages "
            "(user_id, platform, platform_user_id, username, display_name, message, message_id, is_command, timestamp) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, *row),
        )

    def _award_in(self, conn: sqlite3.Connection, user_id: int, delta: int, reason: str, source: str) -> int:
        now = time.time()
        row = conn.execute("SELECT points FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return 0
        new_bal = int(row["points"]) + delta
        if new_bal < 0:
            new_bal = 0
            delta = new_bal - int(row["points"])
        conn.execute(
            "UPDATE users SET points=?, updated_at=? WHERE id=?",
            (new_bal, now, user_id),
        )
        conn.execute(
            "INSERT INTO points_ledger (user_id, delta, balance_after, reason, source, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, delta, new_bal, reason, source, now),
        )
        return new_bal

    def _award_points_sync(self, user_id: int, delta: int, reason: str, source: str) -> int:
        with self._connect() as conn:
            bal = self._award_in(conn, user_id, delta, reason, source)
            conn.commit()
            return bal

    # --- chat lines: queued, written in batches by one task -----------------------------

    def start_writer(self) -> None:
        """Start the chat writer. Until then (tests, tools) process_chat writes straight away."""
        if self._writer_task and not self._writer_task.done():
            return
        self._queue = asyncio.Queue(maxsize=CHAT_QUEUE_MAX)
        self._writer_task = asyncio.create_task(self._writer_loop(), name="chat-db-writer")

    async def stop_writer(self) -> None:
        """Write what is still queued, then stop."""
        task, self._writer_task = self._writer_task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        writing, self._writing = self._writing, None
        if writing is not None:
            await writing           # (never raises: _write catches errors)
        await self._drain()
        self._queue = None
        conn, self._writer_conn = self._writer_conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def submit_chat(self, event: ChatEvent, award: bool = True, flagged: bool = False) -> None:
        """Queue a chat line for the writer and return at once (the chat read loop never waits
        for the disk). Without a running writer (tests, tools; Core always starts one) the
        line is written straight away."""
        item = self._chat_item(event, award, flagged, None)
        if self._queue is None:
            self._write_batch_sync([item])
            return
        self._put(item)

    async def process_chat(self, event: ChatEvent, award: bool = True, flagged: bool = False) -> dict:
        """Ensure user exists, optionally log message, maybe award chat points
        (``flagged``: a red-flagged chatter, logged even with ``chat_log.only_flagged``;
        ``award`` False: they earn nothing). Waits until the line is written."""
        if self._queue is None:
            item = self._chat_item(event, award, flagged, None)
            return (await self._run(self._write_batch_sync, [item]))[0]
        fut = asyncio.get_running_loop().create_future()
        self._put(self._chat_item(event, award, flagged, fut))
        return await fut

    def _chat_item(self, event: ChatEvent, award: bool, flagged: bool, fut) -> tuple:
        # copied now: the event object is shared with the rest of the chat pipeline
        return (event.platform.value, str(event.user.id), event.user.username or "",
                event.user.display_name or "", _chat_row(event), bool(award), bool(flagged), fut)

    def _put(self, item: tuple) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped += 1
            now = time.time()
            if now - self._dropped_logged > 60:
                self._dropped_logged = now
                log.warning("Chat database is behind: %d chat lines not saved so far", self._dropped)
            fut = item[-1]
            if fut is not None and not fut.done():
                fut.set_result({"user_id": None, "awarded": 0, "balance": None, "logged": False})

    async def _writer_loop(self) -> None:
        while True:
            first = await self._queue.get()     # (stopped here: nothing taken, nothing lost)
            batch = [first]
            try:
                # gather what else arrives for a moment: one transaction for the lot
                await asyncio.sleep(CHAT_BATCH_WAIT)
            finally:
                # also when stop_writer cancels the wait: lines already taken off the queue are
                # written, not lost. The write itself can't be cut off halfway (shield);
                # stop_writer waits for it before writing the rest.
                while len(batch) < CHAT_BATCH_MAX:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                self._writing = asyncio.ensure_future(self._write(batch))
            await asyncio.shield(self._writing)
            self._writing = None

    async def _drain(self) -> None:
        if self._queue is None:
            return
        while not self._queue.empty():
            batch = []
            while len(batch) < CHAT_BATCH_MAX and not self._queue.empty():
                batch.append(self._queue.get_nowait())
            await self._write(batch)

    async def _write(self, batch: list) -> None:
        try:
            async with self._write_lock:
                results = await self._run(self._write_batch_sync, batch, True)
        except Exception as exc:
            log.exception("Writing %d chat lines failed", len(batch))
            results = [{"user_id": None, "awarded": 0, "balance": None, "logged": False, "error": str(exc)}] * len(batch)
        for item, res in zip(batch, results):
            fut = item[-1]
            if fut is not None and not fut.done():
                fut.set_result(res)

    def _write_batch_sync(self, batch: list, keep_conn: bool = False) -> list[dict]:
        """One transaction for many chat lines: user lookups, chat log, chat points, stream days."""
        if keep_conn:
            if self._writer_conn is None:
                self._writer_conn = self._connect()
            conn = self._writer_conn
        else:
            conn = self._connect()
        results: list[dict] = []
        day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        try:
            for platform, pid, username, display, row, award, flagged, _fut in batch:
                try:
                    results.append(self._process_one(conn, platform, pid, username, display, row,
                                                     award, flagged, day))
                except sqlite3.Error as exc:
                    # one bad line (a user merged away mid-batch ...) must not lose the others
                    log.warning("Chat line not saved: %s", exc)
                    self.forget_identities()
                    results.append({"user_id": None, "awarded": 0, "balance": None, "logged": False})
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            if not keep_conn:
                conn.close()
        return results

    def _process_one(self, conn, platform, pid, username, display, row, award, flagged, day) -> dict:
        uid = self._get_or_create_in(conn, platform, pid, username, display)
        logged = self.log_chat and (flagged or not self.log_only_flagged)
        if logged:
            self._log_chat_in(conn, row, uid)
        awarded = 0
        balance = None
        if award and self.enabled and self.per_message > 0:
            now = time.time()
            if now - self._last_award.get(uid, 0) >= self.cooldown_sec:
                balance = self._award_in(conn, uid, self.per_message, "chat message", "chat")
                self._last_award[uid] = now
                awarded = self.per_message
        if (uid, day) not in self._days_seen:
            self._ensure_days_table(conn)
            conn.execute("INSERT OR IGNORE INTO chatter_stream_days (user_id, day) VALUES (?,?)", (uid, day))
            if len(self._days_seen) > 200_000:
                self._days_seen.clear()
            self._days_seen.add((uid, day))
        return {"user_id": uid, "awarded": awarded, "balance": balance, "logged": logged}

    _days_table_ready = False

    def _ensure_days_table(self, conn: sqlite3.Connection) -> None:
        if self._days_table_ready:
            return
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chatter_stream_days (
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                PRIMARY KEY (user_id, day)
            )
            """
        )
        self._days_table_ready = True

    def _streak_sync(self, user_id: int) -> int:
        import datetime as _dt
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chatter_stream_days (
                    user_id INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    PRIMARY KEY (user_id, day)
                )
                """
            )
            rows = conn.execute(
                "SELECT day FROM chatter_stream_days WHERE user_id=? ORDER BY day DESC",
                (user_id,),
            ).fetchall()
        days = {r["day"] for r in rows}
        if not days:
            return 0
        streak = 0
        cur = _dt.datetime.utcnow().date()
        # allow yesterday as start if they have not chatted yet today
        if cur.isoformat() not in days:
            cur = cur - _dt.timedelta(days=1)
        while cur.isoformat() in days:
            streak += 1
            cur = cur - _dt.timedelta(days=1)
        return streak

    async def chatter_streak(self, user_id: int) -> int:
        return await self._run(self._streak_sync, user_id)

    # ------------------------------------------------------------------
    # Streams + attendance (chat games: !streak, titles, !claim)
    # ------------------------------------------------------------------

    def _current_stream_sync(self, gap_sec: float, now: float, force_new: bool) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT id, started, last_activity FROM streams ORDER BY id DESC LIMIT 1").fetchone()
            if row and not force_new and now - float(row["last_activity"]) <= gap_sec:
                conn.execute("UPDATE streams SET last_activity=? WHERE id=?", (max(now, float(row["last_activity"])), row["id"]))
                conn.commit()
                return {"id": int(row["id"]), "started": float(row["started"]), "new": False}
            cur = conn.execute("INSERT INTO streams (started, last_activity) VALUES (?,?)", (now, now))
            conn.commit()
            return {"id": int(cur.lastrowid), "started": now, "new": True}

    async def current_stream(self, gap_sec: float, now: float | None = None, force_new: bool = False) -> dict:
        """This stream's {id, started, new}; a new one after `gap_sec` without chat."""
        return await self._run(self._current_stream_sync, float(gap_sec), float(now or time.time()), force_new)

    def _attend_sync(self, user_id: int, stream_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO stream_attendance (user_id, stream_id, claimed) VALUES (?,?,0)",
                (user_id, stream_id),
            )
            conn.commit()
            return cur.rowcount > 0

    async def attend(self, user_id: int, stream_id: int) -> bool:
        """Marks the user as here this stream. True the first time."""
        return await self._run(self._attend_sync, user_id, stream_id)

    def _claim_sync(self, user_id: int, stream_id: int) -> bool:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO stream_attendance (user_id, stream_id, claimed) VALUES (?,?,0)",
                (user_id, stream_id),
            )
            cur = conn.execute(
                "UPDATE stream_attendance SET claimed=1 WHERE user_id=? AND stream_id=? AND claimed=0",
                (user_id, stream_id),
            )
            conn.commit()
            return cur.rowcount > 0

    async def claim_once(self, user_id: int, stream_id: int) -> bool:
        """True the first time this user claims in this stream."""
        return await self._run(self._claim_sync, user_id, stream_id)

    def _streaks_sync(self, user_id: int, stream_id: int) -> dict:
        with self._connect() as conn:
            ids = [int(r["id"]) for r in conn.execute(
                "SELECT id FROM streams WHERE id<=? ORDER BY id DESC", (stream_id,)).fetchall()]
            mine = {int(r["stream_id"]) for r in conn.execute(
                "SELECT stream_id FROM stream_attendance WHERE user_id=?", (user_id,)).fetchall()}
        current = 0
        seq = ids if (ids and ids[0] in mine) else ids[1:]   # not here yet today: count up to last stream
        for sid in seq:
            if sid not in mine:
                break
            current += 1
        best = run = 0
        for sid in reversed(ids):
            run = run + 1 if sid in mine else 0
            best = max(best, run)
        return {"current": current, "best": best, "total": len(mine)}

    async def stream_streaks(self, user_id: int, stream_id: int) -> dict:
        """{current, best, total}: streams in a row, best run ever, streams attended."""
        return await self._run(self._streaks_sync, user_id, stream_id)

    async def get_balance_for_platform(
        self, platform: str, platform_user_id: str, username: str = ""
    ) -> Optional[int]:
        """Return points balance for a platform identity, or None if unknown."""

        def _sync():
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT u.points FROM identities i "
                    "JOIN users u ON u.id = i.user_id "
                    "WHERE i.platform=? AND i.platform_user_id=?",
                    (platform, str(platform_user_id)),
                ).fetchone()
                if row:
                    return int(row["points"])
                if username:
                    row = conn.execute(
                        "SELECT u.points FROM identities i "
                        "JOIN users u ON u.id = i.user_id "
                        "WHERE i.platform=? AND lower(i.username)=lower(?) "
                        "ORDER BY i.last_seen DESC LIMIT 1",
                        (platform, username),
                    ).fetchone()
                    if row:
                        return int(row["points"])
                return None

        return await self._run(_sync)

    async def adjust_points(
        self, user_id: int, delta: int, reason: str = "admin adjust", source: str = "admin"
    ) -> dict:
        balance = await self._run(self._award_points_sync, user_id, delta, reason, source)
        return {"user_id": user_id, "delta": delta, "balance": balance}

    def _spend_points_sync(
        self, user_id: int, unit_cost: int, max_count: int, reason: str, source: str
    ) -> tuple[int, int]:
        """
        Check-and-debit in one transaction. Buys as many units (1..max_count)
        as the balance covers. Never goes negative and never takes a partial
        unit. Returns (units_bought, balance_after); (0, balance) = refused.
        """
        unit_cost = max(1, int(unit_cost))
        max_count = max(1, int(max_count))
        now = time.time()
        conn = self._connect()
        try:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT points FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return 0, 0
            have = int(row["points"])
            units = min(max_count, have // unit_cost)
            if units < 1:
                conn.execute("ROLLBACK")
                return 0, have
            total = units * unit_cost
            new_bal = have - total
            conn.execute(
                "UPDATE users SET points=?, updated_at=? WHERE id=?",
                (new_bal, now, user_id),
            )
            conn.execute(
                "INSERT INTO points_ledger (user_id, delta, balance_after, reason, source, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (user_id, -total, new_bal, reason, source, now),
            )
            conn.execute("COMMIT")
            return units, new_bal
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    async def spend_points(
        self, user_id: int, unit_cost: int, max_count: int = 1,
        reason: str = "spend", source: str = "system",
    ) -> tuple[int, int]:
        """Atomic spend (see _spend_points_sync). Used by chat reactions."""
        async with self._lock:
            return await self._run(
                self._spend_points_sync, user_id, unit_cost, max_count, reason, source
            )

    async def set_points(
        self, user_id: int, value: int, reason: str = "set", source: str = "system"
    ) -> dict:
        user = await self.get_user(user_id)
        current = int((user or {}).get("points") or 0)
        delta = int(value) - current
        if delta == 0:
            return {"user_id": user_id, "delta": 0, "balance": current}
        return await self.adjust_points(user_id, delta, reason, source)

    # ------------------------------------------------------------------
    # Linking / merging accounts
    # ------------------------------------------------------------------

    def _link_identity_sync(
        self,
        target_user_id: int,
        platform: str,
        platform_user_id: str,
        username: str = "",
        display_name: str = "",
    ) -> dict:
        """Attach an identity to target_user. Merges if identity already belongs elsewhere."""
        now = time.time()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT user_id FROM identities WHERE platform=? AND platform_user_id=?",
                (platform, platform_user_id),
            ).fetchone()

            if existing:
                old_uid = int(existing["user_id"])
                if old_uid == target_user_id:
                    conn.execute(
                        "UPDATE identities SET username=?, display_name=?, last_seen=? "
                        "WHERE platform=? AND platform_user_id=?",
                        (username or "", display_name or username or "", now, platform, platform_user_id),
                    )
                    conn.commit()
                    return {"ok": True, "merged": False, "user_id": target_user_id}

                # Merge old_uid → target_user_id
                pts = conn.execute("SELECT points FROM users WHERE id=?", (old_uid,)).fetchone()
                extra = int(pts["points"]) if pts else 0
                if extra:
                    row = conn.execute("SELECT points FROM users WHERE id=?", (target_user_id,)).fetchone()
                    new_bal = int(row["points"]) + extra
                    conn.execute(
                        "UPDATE users SET points=?, updated_at=? WHERE id=?",
                        (new_bal, now, target_user_id),
                    )
                    conn.execute(
                        "INSERT INTO points_ledger (user_id, delta, balance_after, reason, source, created_at) "
                        "VALUES (?,?,?,?,?,?)",
                        (target_user_id, extra, new_bal, f"merge from user {old_uid}", "merge", now),
                    )
                conn.execute(
                    "UPDATE identities SET user_id=?, username=COALESCE(NULLIF(?,''), username), "
                    "display_name=COALESCE(NULLIF(?,''), display_name), last_seen=? WHERE user_id=?",
                    (target_user_id, username, display_name, now, old_uid),
                )
                conn.execute(
                    "UPDATE chat_messages SET user_id=? WHERE user_id=?",
                    (target_user_id, old_uid),
                )
                conn.execute(
                    "UPDATE points_ledger SET user_id=? WHERE user_id=?",
                    (target_user_id, old_uid),
                )
                conn.execute("DELETE FROM users WHERE id=?", (old_uid,))
                conn.commit()
                return {"ok": True, "merged": True, "from_user_id": old_uid, "user_id": target_user_id}

            # New identity
            conn.execute(
                "INSERT INTO identities (user_id, platform, platform_user_id, username, display_name, last_seen) "
                "VALUES (?,?,?,?,?,?)",
                (target_user_id, platform, platform_user_id, username, display_name or username, now),
            )
            conn.commit()
            return {"ok": True, "merged": False, "user_id": target_user_id}

    def _find_identity_by_name_sync(self, platform: str, username: str) -> Optional[dict]:
        name = (username or "").strip().lstrip("@").lower()
        if not name:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM identities WHERE platform=? AND (lower(username)=? OR lower(display_name)=?) "
                "ORDER BY last_seen DESC LIMIT 1",
                (platform, name, name),
            ).fetchone()
            return dict(row) if row else None

    async def find_identity_by_name(self, platform: str, username: str) -> Optional[dict]:
        """The account Core has seen with this login or display name on that platform (newest), or None."""
        return await self._run(self._find_identity_by_name_sync, platform, username)

    async def link_identity(
        self,
        target_user_id: int,
        platform: str,
        platform_user_id: str,
        username: str = "",
        display_name: str = "",
    ) -> dict:
        async with self._write_lock:
            self.forget_identities()
            try:
                return await self._run(
                    self._link_identity_sync,
                    target_user_id,
                    platform,
                    platform_user_id,
                    username,
                    display_name,
                )
            finally:
                self.forget_identities()

    def _merge_users_sync(self, keep_id: int, absorb_id: int) -> dict:
        if keep_id == absorb_id:
            return {"ok": False, "error": "same user"}
        now = time.time()
        with self._connect() as conn:
            a = conn.execute("SELECT id, points FROM users WHERE id=?", (absorb_id,)).fetchone()
            k = conn.execute("SELECT id, points FROM users WHERE id=?", (keep_id,)).fetchone()
            if not a or not k:
                return {"ok": False, "error": "user not found"}
            extra = int(a["points"])
            new_bal = int(k["points"]) + extra
            conn.execute(
                "UPDATE users SET points=?, updated_at=? WHERE id=?",
                (new_bal, now, keep_id),
            )
            if extra:
                conn.execute(
                    "INSERT INTO points_ledger (user_id, delta, balance_after, reason, source, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (keep_id, extra, new_bal, f"merge user {absorb_id}", "merge", now),
                )
            conn.execute("UPDATE identities SET user_id=? WHERE user_id=?", (keep_id, absorb_id))
            conn.execute("UPDATE chat_messages SET user_id=? WHERE user_id=?", (keep_id, absorb_id))
            conn.execute("UPDATE points_ledger SET user_id=? WHERE user_id=?", (keep_id, absorb_id))
            conn.execute("DELETE FROM users WHERE id=?", (absorb_id,))
            conn.commit()
            return {"ok": True, "user_id": keep_id, "balance": new_bal}

    async def merge_users(self, keep_id: int, absorb_id: int) -> dict:
        # not while a chat batch is being written: it may still name the absorbed user
        async with self._write_lock:
            self.forget_identities()
            try:
                return await self._run(self._merge_users_sync, keep_id, absorb_id)
            finally:
                self.forget_identities()

    # ------------------------------------------------------------------
    # Queries for dashboard
    # ------------------------------------------------------------------

    def _list_users_sync(self, q: str = "", limit: int = 100, offset: int = 0) -> list[dict]:
        with self._connect() as conn:
            if q:
                like = f"%{q.lower()}%"
                rows = conn.execute(
                    """
                    SELECT u.id, u.display_name, u.points, u.notes, u.created_at, u.updated_at,
                           GROUP_CONCAT(i.platform || ':' || i.username, ', ') AS accounts
                    FROM users u
                    LEFT JOIN identities i ON i.user_id = u.id
                    WHERE lower(u.display_name) LIKE ?
                       OR u.id IN (
                         SELECT user_id FROM identities
                         WHERE lower(username) LIKE ? OR lower(display_name) LIKE ?
                            OR platform_user_id LIKE ?
                       )
                    GROUP BY u.id
                    ORDER BY u.points DESC, u.updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (like, like, like, like, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT u.id, u.display_name, u.points, u.notes, u.created_at, u.updated_at,
                           GROUP_CONCAT(i.platform || ':' || i.username, ', ') AS accounts
                    FROM users u
                    LEFT JOIN identities i ON i.user_id = u.id
                    GROUP BY u.id
                    ORDER BY u.points DESC, u.updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            return [dict(r) for r in rows]

    async def list_users(self, q: str = "", limit: int = 100, offset: int = 0) -> list[dict]:
        return await self._run(self._list_users_sync, q, limit, offset)

    def _get_user_sync(self, user_id: int) -> Optional[dict]:
        with self._connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not u:
                return None
            identities = conn.execute(
                "SELECT * FROM identities WHERE user_id=? ORDER BY platform",
                (user_id,),
            ).fetchall()
            ledger = conn.execute(
                "SELECT * FROM points_ledger WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
                (user_id,),
            ).fetchall()
            return {
                **dict(u),
                "identities": [dict(i) for i in identities],
                "ledger": [dict(l) for l in ledger],
            }

    async def get_user(self, user_id: int) -> Optional[dict]:
        return await self._run(self._get_user_sync, user_id)

    def _search_chat_sync(
        self,
        user_id: Optional[int] = None,
        platform: str = "",
        q: str = "",
        limit: int = 200,
        offset: int = 0,
        flagged_only: bool = False,
    ) -> list[dict]:
        clauses = []
        args: list[Any] = []
        if user_id:
            clauses.append("user_id=?")
            args.append(user_id)
        if platform:
            clauses.append("platform=?")
            args.append(platform)
        if q:
            clauses.append("lower(message) LIKE ?")
            args.append(f"%{q.lower()}%")
        if flagged_only:
            clauses.append(FLAGGED_SQL)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        args.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT *, {FLAGGED_SQL} AS flagged FROM chat_messages {where} "
                "ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                args,
            ).fetchall()
            return [dict(r) for r in rows]

    def iter_chat_sync(self, batch: int = 5000):
        """Every saved chat line, oldest first, a batch at a time (for "Check past chat")."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT platform, platform_user_id, username, display_name, message, timestamp "
                "FROM chat_messages ORDER BY timestamp, id"
            )
            while True:
                rows = cur.fetchmany(batch)
                if not rows:
                    return
                for r in rows:
                    yield dict(r)
        finally:
            conn.close()

    async def search_chat(
        self,
        user_id: Optional[int] = None,
        platform: str = "",
        q: str = "",
        limit: int = 200,
        offset: int = 0,
        flagged_only: bool = False,
    ) -> list[dict]:
        return await self._run(self._search_chat_sync, user_id, platform, q, limit, offset, flagged_only)

    # ------------------------------------------------------------------
    # Red flags (core/red_flags.py keeps the lookup; this is the table)
    # ------------------------------------------------------------------

    def list_red_flagged_sync(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT f.*, (SELECT COUNT(*) FROM chat_messages c WHERE c.platform=f.platform "
                "AND f.platform_user_id!='' AND c.platform_user_id=f.platform_user_id) AS messages "
                "FROM red_flagged f ORDER BY flagged_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def _add_red_flag_sync(self, row: dict) -> dict:
        with self._connect() as conn:
            # one row per person: the same account (or name) again only refreshes nothing
            if row["platform_user_id"]:
                found = conn.execute(
                    "SELECT * FROM red_flagged WHERE platform=? AND platform_user_id=?",
                    (row["platform"], row["platform_user_id"]),
                ).fetchone()
            else:
                found = conn.execute(
                    "SELECT * FROM red_flagged WHERE platform=? AND platform_user_id='' AND username=?",
                    (row["platform"], row["username"]),
                ).fetchone()
            if found:
                return dict(found)
            cur = conn.execute(
                "INSERT INTO red_flagged (platform, platform_user_id, username, display_name, phrase, message, source, flagged_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (row["platform"], row["platform_user_id"], row["username"], row["display_name"],
                 row["phrase"], row["message"], row["source"], time.time()),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM red_flagged WHERE id=?", (cur.lastrowid,)).fetchone())

    async def add_red_flag(self, *, platform: str, platform_user_id: str, username: str, display_name: str,
                           phrase: str = "", message: str = "", source: str = "phrase") -> dict:
        row = {"platform": platform, "platform_user_id": platform_user_id, "username": username,
               "display_name": display_name[:120], "phrase": phrase[:200], "message": message[:500],
               "source": source}
        return await self._run(self._add_red_flag_sync, row)

    def _remove_red_flag_sync(self, flag_id: int) -> Optional[dict]:
        with self._connect() as conn:
            found = conn.execute("SELECT * FROM red_flagged WHERE id=?", (flag_id,)).fetchone()
            if not found:
                return None
            conn.execute("DELETE FROM red_flagged WHERE id=?", (flag_id,))
            conn.commit()
            return dict(found)

    async def remove_red_flag(self, flag_id: int) -> Optional[dict]:
        return await self._run(self._remove_red_flag_sync, flag_id)

    def _export_chat_csv_sync(self, user_id: Optional[int] = None, platform: str = "", q: str = "",
                              flagged_only: bool = False) -> str:
        rows = self._search_chat_sync(user_id=user_id, platform=platform, q=q, limit=1_000_000, offset=0,
                                      flagged_only=flagged_only)
        buf = io.StringIO()
        w = SafeWriter(buf)
        w.writerow(
            [
                "id",
                "timestamp",
                "user_id",
                "platform",
                "platform_user_id",
                "username",
                "display_name",
                "message",
                "message_id",
                "is_command",
            ]
        )
        for r in reversed(rows):  # chronological
            w.writerow(
                [
                    r["id"],
                    r["timestamp"],
                    r["user_id"],
                    r["platform"],
                    r["platform_user_id"],
                    r["username"],
                    r["display_name"],
                    r["message"],
                    r["message_id"],
                    r["is_command"],
                ]
            )
        return buf.getvalue()

    async def export_chat_csv(self, user_id: Optional[int] = None, platform: str = "", q: str = "",
                              flagged_only: bool = False) -> str:
        """The chat log as CSV, with the same filters as the Chat history search."""
        return await self._run(self._export_chat_csv_sync, user_id, platform, q, flagged_only)

    # ------------------------------------------------------------------
    # Market holdings / dividends
    # ------------------------------------------------------------------

    def _holdings_for_symbol_sync(self, symbol: str) -> list[dict]:
        sym = symbol.upper().strip()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, milli_shares FROM market_holdings WHERE symbol=? AND milli_shares > 0",
                (sym,),
            ).fetchall()
            return [dict(r) for r in rows]

    def _pay_dividend_sync(self, symbol: str, total_points: int, reason: str) -> dict:
        """Split total_points across holders of symbol. Dust is burned."""
        total_points = int(max(0, total_points))
        holders = self._holdings_for_symbol_sync(symbol)
        pool = sum(int(h["milli_shares"]) for h in holders)
        paid = []
        burned = total_points
        if total_points <= 0 or pool <= 0:
            return {
                "symbol": symbol.upper(),
                "total": total_points,
                "holders": 0,
                "paid": [],
                "burned": burned,
                "reason": reason,
            }
        remaining = total_points
        for h in holders:
            share = int(h["milli_shares"])
            cut = (total_points * share) // pool
            if cut <= 0:
                continue
            bal = self._award_points_sync(
                int(h["user_id"]),
                cut,
                reason or f"dividend {symbol}",
                "dividend",
            )
            paid.append({"user_id": int(h["user_id"]), "points": cut, "balance": bal})
            remaining -= cut
        return {
            "symbol": symbol.upper(),
            "total": total_points,
            "holders": len(paid),
            "paid": paid,
            "burned": max(0, remaining),
            "reason": reason,
        }

    async def pay_dividend(self, symbol: str, total_points: int, reason: str = "vault") -> dict:
        return await self._run(self._pay_dividend_sync, symbol, total_points, reason)

    def _adjust_holding_sync(self, user_id: int, symbol: str, milli_delta: int) -> int:
        sym = symbol.upper().strip()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT milli_shares FROM market_holdings WHERE user_id=? AND symbol=?",
                (user_id, sym),
            ).fetchone()
            current = int(row["milli_shares"]) if row else 0
            nxt = max(0, current + int(milli_delta))
            conn.execute(
                "INSERT INTO market_holdings (user_id, symbol, milli_shares) VALUES (?,?,?) "
                "ON CONFLICT(user_id, symbol) DO UPDATE SET milli_shares=excluded.milli_shares",
                (user_id, sym, nxt),
            )
            conn.commit()
            return nxt

    async def adjust_holding(self, user_id: int, symbol: str, milli_delta: int) -> int:
        return await self._run(self._adjust_holding_sync, user_id, symbol, milli_delta)

    def _list_holdings_sync(self, symbol: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if symbol:
                rows = conn.execute(
                    "SELECT user_id, symbol, milli_shares FROM market_holdings "
                    "WHERE symbol=? AND milli_shares > 0 ORDER BY milli_shares DESC",
                    (symbol.upper(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT user_id, symbol, milli_shares FROM market_holdings "
                    "WHERE milli_shares > 0 ORDER BY symbol, milli_shares DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    async def list_holdings(self, symbol: str | None = None) -> list[dict]:
        return await self._run(self._list_holdings_sync, symbol)

    async def holdings_for_user(self, user_id: int) -> list[dict]:
        def _fn():
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT user_id, symbol, milli_shares FROM market_holdings "
                    "WHERE user_id=? AND milli_shares > 0 ORDER BY symbol",
                    (user_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        return await self._run(_fn)

    def _stats_sync(self) -> dict:
        with self._connect() as conn:
            users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            msgs = conn.execute("SELECT COUNT(*) AS c FROM chat_messages").fetchone()["c"]
            pts = conn.execute("SELECT COALESCE(SUM(points),0) AS s FROM users").fetchone()["s"]
            return {"users": users, "messages": msgs, "total_points": pts}

    async def stats(self) -> dict:
        return await self._run(self._stats_sync)

    async def set_notes(self, user_id: int, notes: str) -> None:
        def _fn():
            with self._connect() as conn:
                conn.execute(
                    "UPDATE users SET notes=?, updated_at=? WHERE id=?",
                    (notes, time.time(), user_id),
                )
                conn.commit()

        await self._run(_fn)
