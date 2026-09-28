"""Application database: dataset registry and per-client query history."""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner TEXT,
    tables TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    question TEXT NOT NULL,
    sql TEXT,
    row_count INTEGER,
    status TEXT NOT NULL,
    error TEXT,
    duration_ms REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_client ON history(client_id, dataset_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_datasets_owner ON datasets(owner);
CREATE TABLE IF NOT EXISTS pins (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    chart_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pins_client ON pins(client_id, dataset_id, created_at);
"""
HISTORY_LIMIT = 50


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params)]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def add_dataset(
        self, *, id: str, name: str, owner: str | None, tables: list[str], row_count: int, size_bytes: int
    ) -> dict:
        record = {
            "id": id,
            "name": name,
            "owner": owner,
            "tables": tables,
            "row_count": row_count,
            "size_bytes": size_bytes,
            "created_at": now(),
        }
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?,?)",
                (id, name, owner, json.dumps(tables), row_count, size_bytes, record["created_at"]),
            )
        return record

    def get_dataset(self, dataset_id: str) -> dict | None:
        rows = self._all("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        return _dataset(rows[0]) if rows else None

    def list_datasets(self, owner: str) -> list[dict]:
        rows = self._all(
            "SELECT * FROM datasets WHERE owner IS NULL OR owner = ? ORDER BY owner IS NOT NULL, created_at DESC",
            (owner,),
        )
        return [_dataset(r) for r in rows]

    def count_owned(self, owner: str) -> int:
        return self._all("SELECT COUNT(*) AS n FROM datasets WHERE owner = ?", (owner,))[0]["n"]

    def delete_dataset(self, dataset_id: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
            c.execute("DELETE FROM history WHERE dataset_id = ?", (dataset_id,))
            c.execute("DELETE FROM pins WHERE dataset_id = ?", (dataset_id,))

    def expired_datasets(self, ttl_days: int) -> list[str]:
        cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat(timespec="seconds")
        return [
            r["id"] for r in self._all("SELECT id FROM datasets WHERE owner IS NOT NULL AND created_at < ?", (cutoff,))
        ]

    def log(
        self,
        *,
        client_id: str,
        dataset_id: str,
        question: str,
        sql: str | None,
        row_count: int | None,
        status: str,
        error: str | None,
        duration_ms: float,
    ) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO history (client_id, dataset_id, question, sql, row_count, status, error, duration_ms, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (client_id, dataset_id, question, sql, row_count, status, error, duration_ms, now()),
            )
            c.execute(
                "DELETE FROM history WHERE client_id = ? AND dataset_id = ? AND id NOT IN (SELECT id FROM history "
                "WHERE client_id = ? AND dataset_id = ? ORDER BY id DESC LIMIT ?)",
                (client_id, dataset_id, client_id, dataset_id, HISTORY_LIMIT),
            )
            return cur.lastrowid

    def history(self, client_id: str, dataset_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
        return self._all(
            "SELECT id, question, sql, row_count, status, error, duration_ms, created_at FROM history "
            "WHERE client_id = ? AND dataset_id = ? ORDER BY id DESC LIMIT ?",
            (client_id, dataset_id, limit),
        )

    def clear_history(self, client_id: str, dataset_id: str) -> int:
        with self._tx() as c:
            return c.execute(
                "DELETE FROM history WHERE client_id = ? AND dataset_id = ?", (client_id, dataset_id)
            ).rowcount

    def add_pin(
        self, *, id: str, client_id: str, dataset_id: str, title: str, question: str, sql: str, chart_type: str
    ) -> dict:
        record = {
            "id": id,
            "dataset_id": dataset_id,
            "title": title,
            "question": question,
            "sql": sql,
            "chart_type": chart_type,
            "created_at": now(),
        }
        with self._tx() as c:
            c.execute(
                "INSERT INTO pins VALUES (?,?,?,?,?,?,?,?)",
                (id, client_id, dataset_id, title, question, sql, chart_type, record["created_at"]),
            )
        return record

    def pins(self, client_id: str, dataset_id: str) -> list[dict]:
        return self._all(
            "SELECT id, dataset_id, title, question, sql, chart_type, created_at FROM pins "
            "WHERE client_id = ? AND dataset_id = ? ORDER BY rowid",
            (client_id, dataset_id),
        )

    def get_pin(self, pin_id: str, client_id: str) -> dict | None:
        rows = self._all(
            "SELECT id, dataset_id, title, question, sql, chart_type, created_at FROM pins "
            "WHERE id = ? AND client_id = ?",
            (pin_id, client_id),
        )
        return rows[0] if rows else None

    def count_pins(self, client_id: str) -> int:
        return self._all("SELECT COUNT(*) AS n FROM pins WHERE client_id = ?", (client_id,))[0]["n"]

    def rename_pin(self, pin_id: str, client_id: str, title: str) -> bool:
        with self._tx() as c:
            return (
                c.execute(
                    "UPDATE pins SET title = ? WHERE id = ? AND client_id = ?", (title, pin_id, client_id)
                ).rowcount
                > 0
            )

    def delete_pin(self, pin_id: str, client_id: str) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM pins WHERE id = ? AND client_id = ?", (pin_id, client_id)).rowcount > 0

    def ping(self) -> None:
        self._all("SELECT 1")


def _dataset(row: dict) -> dict:
    return {**row, "tables": json.loads(row["tables"]), "builtin": row["owner"] is None}
