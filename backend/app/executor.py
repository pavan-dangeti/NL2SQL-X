"""Runs validated SELECTs on a read-only connection with an authorizer, a time
budget and a row cap. Work happens in worker threads behind a semaphore so a slow
query never blocks the event loop."""

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from app.sql_guard import BLOCKED_FUNCTIONS

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", 33)
SYSTEM_TABLES = {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema", "sqlite_sequence"}


class QueryTimeoutError(Exception):
    pass


class QueryExecutionError(Exception):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool
    duration_ms: float


def _authorizer(allowed_tables: set[str], real_tables: set[str]):
    allowed = {t.lower() for t in allowed_tables}
    protected = {t.lower() for t in real_tables} | SYSTEM_TABLES

    def check(action, arg1, arg2, _db, _trigger):
        if action == sqlite3.SQLITE_READ:
            name = (arg1 or "").lower()
            return sqlite3.SQLITE_DENY if name in protected and name not in allowed else sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_DENY if (arg2 or "").lower() in BLOCKED_FUNCTIONS else sqlite3.SQLITE_OK
        if action in _ALLOWED_ACTIONS or action == _RECURSIVE:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return check


def _cell(value):
    return f"<{len(value)} bytes>" if isinstance(value, bytes) else value


def run_sync(db_path: Path, sql: str, allowed_tables: set[str], max_rows: int, timeout_ms: int) -> QueryResult:
    started = time.perf_counter()
    deadline = started + timeout_ms / 1000
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    try:
        conn.execute("PRAGMA query_only = ON")
        real = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        conn.set_authorizer(_authorizer(allowed_tables, real))
        conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 2000)
        try:
            cursor = conn.execute(sql)
            fetched = cursor.fetchmany(max_rows + 1)
        except sqlite3.OperationalError as exc:
            if str(exc) == "interrupted":
                raise QueryTimeoutError(f"Query exceeded the {timeout_ms} ms time limit.") from exc
            raise QueryExecutionError(_clean(exc)) from exc
        except (sqlite3.DatabaseError, sqlite3.Warning, sqlite3.ProgrammingError) as exc:
            raise QueryExecutionError(_clean(exc)) from exc
        columns = _unique([d[0] for d in cursor.description or []])
        truncated = len(fetched) > max_rows
        rows = [[_cell(v) for v in row] for row in fetched[:max_rows]]
    finally:
        conn.close()
    return QueryResult(columns, rows, truncated, round((time.perf_counter() - started) * 1000, 2))


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        key = name or "column"
        if key in seen:
            seen[key] += 1
            key = f"{key}_{seen[key]}"
        else:
            seen[key] = 1
        out.append(key)
    return out


def _clean(exc: Exception) -> str:
    msg = str(exc)
    if "not authorized" in msg or "prohibited" in msg:
        return "The query touches a table or operation that is not allowed."
    return msg[:300]


class Executor:
    def __init__(self, max_concurrent: int, max_rows: int, timeout_ms: int) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms

    async def run(self, db_path: Path, sql: str, allowed_tables: set[str]) -> QueryResult:
        async with self._sem:
            return await asyncio.to_thread(run_sync, db_path, sql, allowed_tables, self.max_rows, self.timeout_ms)
