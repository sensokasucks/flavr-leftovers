"""
Paid list: every paid message and tip from every platform, with a tick box.

Super Chats, Super Stickers and Jewels gifts (YouTube), bits and bits power-ups (Twitch),
KICKs (Kick), plus subs / resubs / gifted subs and YouTube memberships. Each one is a row
in ``paid_events`` (same SQLite file as the chat log), so the list survives restarts.
The streamer ticks a row once it is read out or thanked; the dashboard's Paid tab
filters by what is still unticked (Admin → Paid, ``/api/admin/paid``).

Alert tests and the overlay showcase never land here. Red-flagged chatters' paid messages
do (with ``flagged``), so no money is missed; they stay hidden on the overlays.
"""

from __future__ import annotations

import io
import logging
import re
import sqlite3
import time
from typing import Any, Optional

from core.csv_safe import SafeWriter

log = logging.getLogger("core.paid")

# Table + indexes, created on first use (``PaidLog.store``). amount is in the row's own unit
# (money, bits or KICKs); amount_text keeps what the platform showed. The unique message index
# stops a platform message from being listed twice after a reconnect. done = ticked.
SCHEMA = """
CREATE TABLE IF NOT EXISTS paid_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL,
    kind             TEXT NOT NULL,
    grp              TEXT NOT NULL DEFAULT 'money',
    platform_user_id TEXT NOT NULL DEFAULT '',
    username         TEXT NOT NULL DEFAULT '',
    display_name     TEXT NOT NULL DEFAULT '',
    message          TEXT NOT NULL DEFAULT '',
    amount           REAL,
    currency         TEXT NOT NULL DEFAULT '',
    amount_text      TEXT NOT NULL DEFAULT '',
    qty              INTEGER,
    months           INTEGER,
    item             TEXT NOT NULL DEFAULT '',
    image_url        TEXT NOT NULL DEFAULT '',
    avatar_url       TEXT NOT NULL DEFAULT '',
    message_id       TEXT,
    flagged          INTEGER NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL,
    done             INTEGER NOT NULL DEFAULT 0,
    done_at          REAL
);
CREATE INDEX IF NOT EXISTS idx_paid_time ON paid_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paid_done ON paid_events(done, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_paid_msg ON paid_events(platform, message_id)
    WHERE message_id IS NOT NULL AND message_id != '';
"""

# kind -> label, group ("money" = paid messages and tips, "subs" = subs and memberships)
KINDS: dict[str, dict[str, str]] = {
    "superchat": {"label": "Super Chat", "group": "money", "platform": "youtube"},
    "supersticker": {"label": "Super Sticker", "group": "money", "platform": "youtube"},
    "jewels": {"label": "Jewels gift", "group": "money", "platform": "youtube"},
    "bits": {"label": "Bits cheer", "group": "money", "platform": "twitch"},
    "powerup": {"label": "Bits power-up", "group": "money", "platform": "twitch"},
    "celebration": {"label": "On-screen celebration", "group": "money", "platform": "twitch"},
    "charity": {"label": "Charity donation", "group": "money", "platform": "twitch"},
    "hypetrain": {"label": "Hype Train", "group": "money", "platform": "twitch"},
    "kicks": {"label": "KICKs", "group": "money", "platform": "kick"},
    "donation": {"label": "Tip", "group": "money", "platform": ""},
    "subscribe": {"label": "Sub / new member", "group": "subs", "platform": ""},
    "resub": {"label": "Resub / member milestone", "group": "subs", "platform": ""},
    "gift": {"label": "Gifted subs / memberships", "group": "subs", "platform": ""},
    "member": {"label": "New member", "group": "subs", "platform": "youtube"},
    "member_milestone": {"label": "Member milestone", "group": "subs", "platform": "youtube"},
    "member_gift": {"label": "Gifted memberships", "group": "subs", "platform": "youtube"},
}

# Alert kinds (core/alerts.py) that go on the list when a platform sends them. Paid chat
# (Super Chats, bits ...) is listed from the chat message itself, not from its alert.
ALERT_KINDS = ("subscribe", "resub", "gift", "kicks", "donation", "jewels",
               "member", "member_milestone", "member_gift",
               # Twitch EventSub: power-ups with their bits, celebrations, charity, Hype Trains
               "powerup", "celebration", "charity", "hypetrain")

# Platform alerts whose amount goes on the list (subs are counted, not priced)
PRICED_ALERT_KINDS = ("kicks", "donation", "powerup", "celebration", "charity")

GROUPS = ("money", "subs")
SORTS = {
    "oldest": "created_at ASC, id ASC",
    "newest": "created_at DESC, id DESC",
    "biggest": "COALESCE(amount, 0) DESC, created_at ASC",
}
LIMIT_MAX = 2000

# ----------------------------------------------------------------------
# Money text ("$5.00", "CA$10.00", "€2,00", "1.000 ₫") -> (amount, ISO currency)
# ----------------------------------------------------------------------

# Longest first so "CA$" wins over "$".
_SYMBOLS: list[tuple[str, str]] = sorted([
    ("$", "USD"), ("US$", "USD"), ("CA$", "CAD"), ("C$", "CAD"), ("A$", "AUD"), ("AU$", "AUD"),
    ("NZ$", "NZD"), ("MX$", "MXN"), ("R$", "BRL"), ("HK$", "HKD"), ("NT$", "TWD"), ("S$", "SGD"),
    ("€", "EUR"), ("£", "GBP"), ("¥", "JPY"), ("JP¥", "JPY"), ("CN¥", "CNY"), ("₹", "INR"),
    ("₩", "KRW"), ("₱", "PHP"), ("₫", "VND"), ("₪", "ILS"), ("₺", "TRY"), ("₽", "RUB"),
    ("฿", "THB"), ("₴", "UAH"), ("zł", "PLN"), ("kr", "SEK"), ("Kč", "CZK"), ("Ft", "HUF"),
    ("CHF", "CHF"), ("R", "ZAR"), ("RM", "MYR"), ("Rp", "IDR"),
], key=lambda p: -len(p[0]))

_NUM_RE = re.compile(r"\d[\d.,\s  ']*")
_CODE_RE = re.compile(r"\b([A-Z]{3})\b")


def _parse_number(raw: str) -> Optional[float]:
    """"1,000.50" / "1.000,50" / "10,00" -> float, guessing which mark is the decimal one; None if junk."""
    s = re.sub(r"[\s\u00a0\u202f']", "", raw).strip(".,")
    if not s:
        return None
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        # "1,000.50" / "1.000,50": the later mark is the decimal one
        dec, thou = (".", ",") if last_dot > last_comma else (",", ".")
        s = s.replace(thou, "").replace(dec, ".")
    elif last_comma >= 0:
        # "10,00" / "2,5" = decimal comma; "1,000" / "12,345,678" = thousands
        tail = s[last_comma + 1:]
        s = s.replace(",", ".") if s.count(",") == 1 and len(tail) != 3 else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")          # "1.000.000"
    try:
        return float(s)
    except ValueError:
        return None


def parse_money(text: str) -> tuple[Optional[float], str]:
    """``"$5.00"`` -> ``(5.0, "USD")``. Unknown currency -> ``(amount, "")``; no number -> ``(None, "")``."""
    t = (text or "").strip()
    if not t:
        return None, ""
    m = _NUM_RE.search(t)
    if not m:
        return None, ""
    amount = _parse_number(m.group(0))
    rest = (t[: m.start()] + " " + t[m.end():]).strip()
    currency = ""
    code = _CODE_RE.search(rest)
    if code:
        currency = code.group(1)
    else:
        for sym, iso in _SYMBOLS:
            if sym in rest:
                currency = iso
                break
    return amount, currency


_PREFIX_RE = re.compile(r"^\[([^\]]{1,24})\]\s*")


def split_amount_prefix(message: str) -> tuple[str, str]:
    """YouTube paid chat starts "[$5.00] ..." -> ("...", "$5.00")."""
    m = _PREFIX_RE.match(message or "")
    if not m:
        return message or "", ""
    return (message or "")[m.end():], m.group(1)


# ----------------------------------------------------------------------
# The list
# ----------------------------------------------------------------------


def group_of(kind: str) -> str:
    """"money" or "subs" for a kind (unknown kinds count as money)."""
    return (KINDS.get(kind) or {}).get("group", "money")


class PaidLog:
    """Rows in ``paid_events`` (the Store's database file)."""

    def __init__(self, store, on_change=None):
        """``store`` is the Store or a function returning it; ``on_change`` gets the new unticked count."""
        # the Store, or a function returning it (Core swaps its Store in tests)
        self._store = store
        self._ready: set[int] = set()
        self.on_change = on_change          # async callable(count_unticked) after a change

    @property
    def store(self):
        """The Store, making sure the paid_events table exists in its database first (once per Store)."""
        st = self._store() if callable(self._store) else self._store
        if id(st) not in self._ready:
            with st._connect() as conn:
                conn.executescript(SCHEMA)
            self._ready.add(id(st))
        return st

    # ---- adding ------------------------------------------------------

    def _add_sync(self, row: dict) -> Optional[int]:
        """Insert one row (worker thread). Returns its id, or None for a duplicate platform message."""
        cols = ("platform", "kind", "grp", "platform_user_id", "username", "display_name", "message",
                "amount", "currency", "amount_text", "qty", "months", "item", "image_url", "avatar_url",
                "message_id", "flagged", "created_at")
        vals = [row.get(c) for c in cols]
        with self.store._connect() as conn:
            try:
                cur = conn.execute(
                    f"INSERT INTO paid_events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
            except sqlite3.IntegrityError:
                return None          # same platform message seen twice (a reconnect)
            conn.commit()
            return int(cur.lastrowid)

    async def add(
        self,
        *,
        platform: str,
        kind: str,
        user_id: str = "",
        username: str = "",
        display_name: str = "",
        message: str = "",
        amount: Optional[float] = None,
        currency: str = "",
        amount_text: str = "",
        qty: Optional[int] = None,
        months: Optional[int] = None,
        item: str = "",
        image_url: str = "",
        avatar_url: str = "",
        message_id: str = "",
        flagged: bool = False,
        when: Optional[float] = None,
    ) -> Optional[int]:
        """List one paid message, tip or sub (main.py: paid chat and platform alerts). Returns the row id.

        Never raises: a database error is logged and gives None.
        """
        kind = (kind or "donation").strip().lower()
        row = {
            "platform": (platform or "").lower(), "kind": kind, "grp": group_of(kind),
            "platform_user_id": str(user_id or ""), "username": str(username or ""),
            "display_name": str(display_name or username or ""), "message": str(message or "")[:2000],
            "amount": float(amount) if amount is not None else None, "currency": str(currency or ""),
            "amount_text": str(amount_text or ""), "qty": qty, "months": months, "item": str(item or ""),
            "image_url": str(image_url or ""), "avatar_url": str(avatar_url or ""),
            "message_id": str(message_id) if message_id else None, "flagged": 1 if flagged else 0,
            "created_at": float(when or time.time()),
        }
        try:
            rid = await self.store._run(self._add_sync, row)
        except Exception:
            log.exception("paid list: could not save %s from %s", kind, username)
            return None
        if rid is not None:
            log.info("[paid] %s %s %s %s", row["platform"], kind, row["display_name"],
                     row["amount_text"] or (f"{amount:g} {currency}" if amount is not None else row["item"]))
            await self._changed()
        return rid

    async def _changed(self) -> None:
        """Tell the dashboard (``on_change``) the new unticked count after a change."""
        if self.on_change is None:
            return
        try:
            await self.on_change(await self.unticked())
        except Exception:
            log.exception("paid list change hook failed")

    # ---- reading -----------------------------------------------------

    @staticmethod
    def _where(f: dict) -> tuple[str, list]:
        """Filters from the dashboard / API → SQL WHERE and its values."""
        sql: list[str] = []
        args: list = []
        status = str(f.get("status") or "open")
        if status == "open":
            sql.append("done=0")
        elif status == "done":
            sql.append("done=1")
        since, until = f.get("since"), f.get("until")
        if since not in (None, ""):
            sql.append("created_at>=?")
            args.append(float(since))
        if until not in (None, ""):
            sql.append("created_at<?")
            args.append(float(until))
        plats = [p for p in _list(f.get("platforms")) if p in ("kick", "twitch", "youtube")]
        if plats:
            sql.append(f"platform IN ({','.join('?' * len(plats))})")
            args += plats
        group = str(f.get("group") or "")
        if group in GROUPS:
            sql.append("grp=?")
            args.append(group)
        kinds = [k for k in _list(f.get("kinds")) if k in KINDS]
        if kinds:
            sql.append(f"kind IN ({','.join('?' * len(kinds))})")
            args += kinds
        try:
            least = float(f.get("min")) if f.get("min") not in (None, "") else None
        except (TypeError, ValueError):
            least = None
        if least is not None and least > 0:
            # one number, read in each row's own unit: 5 = 5.00 of any money, 5 bits, 5 KICKs
            sql.append("amount IS NOT NULL AND amount>=?")
            args.append(least)
        has_msg = str(f.get("has_message") or "")
        if has_msg in ("1", "yes", "true"):
            sql.append("TRIM(message)!=''")
        elif has_msg in ("0", "no", "false"):
            sql.append("TRIM(message)=''")
        q = str(f.get("q") or "").strip().lower()
        if q:
            sql.append("(lower(display_name) LIKE ? OR lower(username) LIKE ? OR lower(message) LIKE ? OR lower(item) LIKE ?)")
            like = f"%{q}%"
            args += [like, like, like, like]
        return (" WHERE " + " AND ".join(sql)) if sql else "", args

    def _list_sync(self, f: dict, limit: int) -> dict:
        """Rows matching the filters, plus the total count, sums per currency (or counts per kind for
        unpriced rows) and the unticked count.
        """
        where, args = self._where(f)
        order = SORTS.get(str(f.get("sort") or "oldest"), SORTS["oldest"])
        with self.store._connect() as conn:
            rows = [dict(r) for r in conn.execute(
                f"SELECT * FROM paid_events{where} ORDER BY {order} LIMIT ?", args + [limit])]
            total = conn.execute(f"SELECT COUNT(*) FROM paid_events{where}", args).fetchone()[0]
            sums = conn.execute(
                f"SELECT currency, SUM(amount) AS amount, COUNT(*) AS n, kind FROM paid_events{where} "
                f"GROUP BY CASE WHEN amount IS NULL THEN kind ELSE currency END", args).fetchall()
            unticked = conn.execute("SELECT COUNT(*) FROM paid_events WHERE done=0 AND grp='money'").fetchone()[0]
        totals = []
        for s in sums:
            if s["amount"] is None:
                totals.append({"kind": s["kind"], "label": KINDS.get(s["kind"], {}).get("label", s["kind"]),
                               "count": s["n"]})
            else:
                totals.append({"currency": s["currency"], "amount": round(s["amount"], 2), "count": s["n"]})
        for r in rows:
            r["label"] = KINDS.get(r["kind"], {}).get("label", r["kind"])
            r["done"] = bool(r["done"])
            r["flagged"] = bool(r["flagged"])
        return {"rows": rows, "total": total, "totals": totals, "unticked": unticked}

    async def list(self, filters: Optional[dict] = None, limit: int = 500) -> dict:
        """``_list_sync`` off the event loop; ``limit`` is clamped to 1..LIMIT_MAX."""
        return await self.store._run(self._list_sync, dict(filters or {}), max(1, min(LIMIT_MAX, int(limit))))

    def _unticked_sync(self) -> int:
        """Count unticked money rows (worker thread)."""
        with self.store._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM paid_events WHERE done=0 AND grp='money'").fetchone()[0])

    async def unticked(self) -> int:
        """Paid messages and tips not ticked yet (subs don't count; the tab badge)."""
        return await self.store._run(self._unticked_sync)

    # ---- ticking / tidying -------------------------------------------

    def _tick_sync(self, ids: list[int], done: bool) -> int:
        """Tick / untick rows by id (worker thread). Returns how many rows changed."""
        if not ids:
            return 0
        with self.store._connect() as conn:
            cur = conn.execute(
                f"UPDATE paid_events SET done=?, done_at=? WHERE id IN ({','.join('?' * len(ids))})",
                [1 if done else 0, time.time() if done else None] + ids)
            conn.commit()
            return cur.rowcount

    async def tick(self, ids: list, done: bool = True) -> int:
        """Tick (or untick with ``done=False``) rows by id. Junk ids are ignored."""
        clean = [int(i) for i in ids if str(i).lstrip("-").isdigit()][:LIMIT_MAX]
        n = await self.store._run(self._tick_sync, clean, bool(done))
        if n:
            await self._changed()
        return n

    def _tick_matching_sync(self, f: dict, done: bool) -> int:
        """Tick / untick every row the filters match (worker thread)."""
        where, args = self._where(f)
        with self.store._connect() as conn:
            cur = conn.execute(f"UPDATE paid_events SET done=?, done_at=?{where}",
                               [1 if done else 0, time.time() if done else None] + args)
            conn.commit()
            return cur.rowcount

    async def tick_matching(self, filters: dict, done: bool = True) -> int:
        """"Tick all shown": every row the filters match (not only the page on screen)."""
        n = await self.store._run(self._tick_matching_sync, dict(filters or {}), bool(done))
        if n:
            await self._changed()
        return n

    def _delete_ticked_sync(self, older_than: float) -> int:
        """Delete ticked rows created before ``older_than`` (epoch seconds)."""
        with self.store._connect() as conn:
            cur = conn.execute("DELETE FROM paid_events WHERE done=1 AND created_at<?", (older_than,))
            conn.commit()
            return cur.rowcount

    async def delete_ticked(self, older_than_days: float) -> int:
        """Ticked rows older than this many days. Nothing is ever deleted on its own."""
        days = max(0.0, float(older_than_days))
        return await self.store._run(self._delete_ticked_sync, time.time() - days * 86400)

    async def export_csv(self, filters: Optional[dict] = None) -> str:
        """Every matching row (no page limit) as formula-safe CSV text."""
        data = await self.store._run(self._list_sync, dict(filters or {}), 1_000_000)
        buf = io.StringIO()
        w = SafeWriter(buf)
        w.writerow(["time", "platform", "type", "name", "amount", "currency", "amount_as_shown", "count",
                    "months", "item", "message", "ticked", "red_flagged"])
        for r in data["rows"]:
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"])), r["platform"],
                        r["label"], r["display_name"] or r["username"],
                        "" if r["amount"] is None else r["amount"], r["currency"], r["amount_text"],
                        "" if r["qty"] is None else r["qty"], "" if r["months"] is None else r["months"],
                        r["item"], r["message"], "yes" if r["done"] else "no", "yes" if r["flagged"] else "no"])
        return buf.getvalue()


def _list(raw: Any) -> list[str]:
    """A filter value ("a,b" or a list) as clean lower-case entries."""
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(x).strip().lower() for x in raw if str(x).strip()]


def kind_catalog() -> list[dict[str, str]]:
    """[{kind, label, group, platform}] for the dashboard's filters."""
    return [{"kind": k, **v} for k, v in KINDS.items()]
