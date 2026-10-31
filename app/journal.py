"""Trading journal stored in a local SQLite file (journal.db)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount_usdt REAL, sell_pct REAL, price REAL,
    take_profit REAL, stop_loss REAL,
    reason TEXT NOT NULL,
    confidence INTEGER, feeling TEXT,
    order_ref TEXT, status TEXT,
    warnings TEXT,
    review TEXT
);
"""


class Journal:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, **fields) -> int:
        fields.setdefault("created_ms", int(time.time() * 1000))
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with self._conn() as c:
            cur = c.execute(f"INSERT INTO entries ({cols}) VALUES ({marks})", list(fields.values()))
            return int(cur.lastrowid)

    def set_review(self, entry_id: int, review: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE entries SET review = ? WHERE id = ?", (review, entry_id))

    def list(self, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM entries ORDER BY created_ms DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
