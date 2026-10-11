"""
A plugin's own SQLite database: ``data/plugins/<id>/<id>.db`` (``ctx.db``).

Plugins keep their tables here instead of in Core's ``stream_core.db``, so removing a plugin
never touches Core's data. Calls run in a worker thread (the event loop never blocks) and one
lock keeps writes in order. Rows come back as plain dicts.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


class PluginDB:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._conn = conn
        return self._conn

    def _run(self, fn, *args):
        with self._lock:
            return fn(self._connect(), *args)

    async def _call(self, fn, *args):
        return await asyncio.to_thread(self._run, fn, *args)

    # ------------------------------------------------------------------

    async def script(self, sql: str) -> None:
        """Several statements at once (CREATE TABLE IF NOT EXISTS ...)."""
        await self._call(lambda c: c.executescript(sql))

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """One write. Returns lastrowid for an INSERT, else the number of rows changed."""
        def go(c: sqlite3.Connection):
            cur = c.execute(sql, tuple(params))
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount
        return await self._call(go)

    async def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        rows = [tuple(r) for r in rows]

        def go(c: sqlite3.Connection):
            c.execute("BEGIN")
            try:
                cur = c.executemany(sql, rows)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            return cur.rowcount
        return await self._call(go)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        return await self._call(lambda c: [dict(r) for r in c.execute(sql, tuple(params)).fetchall()])

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[dict]:
        def go(c: sqlite3.Connection):
            row = c.execute(sql, tuple(params)).fetchone()
            return dict(row) if row is not None else None
        return await self._call(go)

    async def transaction(self, fn):
        """Run ``fn(conn)`` (plain sqlite3, in the worker thread) inside one transaction."""
        def go(c: sqlite3.Connection):
            c.execute("BEGIN IMMEDIATE")
            try:
                out = fn(c)
                c.execute("COMMIT")
                return out
            except Exception:
                c.execute("ROLLBACK")
                raise
        return await self._call(go)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
