"""
SQLite store: chat history, unified users, cross-platform links, chat points.

All platform identities map to one internal user so points follow the person
whether they chat on Kick today or YouTube tomorrow.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from core.models import ChatEvent, Platform

log = logging.getLogger("core.store")

SCHEMA = """
PRAGMA journal_mode=WAL;
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
"""


class Store:
    def __init__(self, db_path: Path | str, points_cfg: dict | None = None):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cfg = points_cfg or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.per_message = int(cfg.get("per_message", 1))
        self.cooldown_sec = float(cfg.get("cooldown_sec", 30))
        self._last_award: dict[int, float] = {}  # user_id -> last award time
        self._lock = asyncio.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
        log.info("Store ready at %s", self.path)

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
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM identities WHERE platform=? AND platform_user_id=?",
                (platform, platform_user_id),
            ).fetchone()
            if row:
                uid = int(row["user_id"])
                conn.execute(
                    "UPDATE identities SET username=?, display_name=?, last_seen=? "
                    "WHERE platform=? AND platform_user_id=?",
                    (username, display_name or username, now, platform, platform_user_id),
                )
                # Keep primary display name fresh if empty
                conn.execute(
                    "UPDATE users SET display_name=CASE WHEN display_name='' OR display_name=username "
                    "THEN ? ELSE display_name END, updated_at=? WHERE id=?",
                    (display_name or username, now, uid),
                )
                conn.commit()
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
            conn.commit()
            return uid

    async def get_or_create_user(
        self, platform: str, platform_user_id: str, username: str, display_name: str = ""
    ) -> int:
        return await self._run(
            self._get_or_create_user_sync, platform, platform_user_id, username, display_name
        )

    # ------------------------------------------------------------------
    # Chat logging + points
    # ------------------------------------------------------------------

    def _log_chat_sync(self, event: ChatEvent, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages "
                "(user_id, platform, platform_user_id, username, display_name, message, message_id, is_command, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    user_id,
                    event.platform.value,
                    event.user.id,
                    event.user.username,
                    event.user.display_name,
                    event.message,
                    event.message_id or None,
                    1 if event.is_command else 0,
                    event.timestamp,
                ),
            )
            conn.commit()

    def _award_points_sync(self, user_id: int, delta: int, reason: str, source: str) -> int:
        now = time.time()
        with self._connect() as conn:
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
            conn.commit()
            return new_bal

    async def process_chat(self, event: ChatEvent) -> dict:
        """Log message, ensure user exists, maybe award chat points."""
        platform = event.platform.value
        uid = await self.get_or_create_user(
            platform,
            event.user.id,
            event.user.username,
            event.user.display_name,
        )
        await self._run(self._log_chat_sync, event, uid)

        awarded = 0
        balance = None
        if self.enabled and self.per_message > 0:
            now = time.time()
            last = self._last_award.get(uid, 0)
            if now - last >= self.cooldown_sec:
                balance = await self._run(
                    self._award_points_sync,
                    uid,
                    self.per_message,
                    "chat message",
                    "chat",
                )
                self._last_award[uid] = now
                awarded = self.per_message

        return {"user_id": uid, "awarded": awarded, "balance": balance}

    async def adjust_points(
        self, user_id: int, delta: int, reason: str = "admin adjust", source: str = "admin"
    ) -> dict:
        balance = await self._run(self._award_points_sync, user_id, delta, reason, source)
        return {"user_id": user_id, "delta": delta, "balance": balance}

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

    async def link_identity(
        self,
        target_user_id: int,
        platform: str,
        platform_user_id: str,
        username: str = "",
        display_name: str = "",
    ) -> dict:
        return await self._run(
            self._link_identity_sync,
            target_user_id,
            platform,
            platform_user_id,
            username,
            display_name,
        )

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
        return await self._run(self._merge_users_sync, keep_id, absorb_id)

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
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        args.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM chat_messages {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                args,
            ).fetchall()
            return [dict(r) for r in rows]

    async def search_chat(
        self,
        user_id: Optional[int] = None,
        platform: str = "",
        q: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        return await self._run(self._search_chat_sync, user_id, platform, q, limit, offset)

    def _export_chat_csv_sync(self, user_id: Optional[int] = None) -> str:
        rows = self._search_chat_sync(user_id=user_id, limit=1_000_000, offset=0)
        buf = io.StringIO()
        w = csv.writer(buf)
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

    async def export_chat_csv(self, user_id: Optional[int] = None) -> str:
        return await self._run(self._export_chat_csv_sync, user_id)

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
