import asyncio
import sqlite3

import pytest

from app.executor import Executor, QueryExecutionError, QueryTimeoutError, run_sync

TABLES = {"items"}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL, data BLOB);
        CREATE TABLE secrets (token TEXT);
        INSERT INTO secrets VALUES ('s3cr3t');
    """)
    conn.executemany(
        "INSERT INTO items (name, price, data) VALUES (?, ?, ?)",
        [(f"item {i}", i * 1.5, b"\x00\x01") for i in range(50)],
    )
    conn.commit()
    conn.close()
    return path


def run(db, sql, max_rows=1000, timeout_ms=2000):
    return run_sync(db, sql, TABLES, max_rows, timeout_ms)


def test_returns_columns_rows_and_timing(db):
    result = run(db, "SELECT id, name, price FROM items ORDER BY id LIMIT 2")
    assert result.columns == ["id", "name", "price"]
    assert result.rows == [[1, "item 0", 0.0], [2, "item 1", 1.5]]
    assert not result.truncated
    assert result.duration_ms >= 0


def test_caps_rows_and_flags_truncation(db):
    result = run(db, "SELECT * FROM items", max_rows=10)
    assert len(result.rows) == 10
    assert result.truncated


def test_blobs_are_summarised(db):
    assert run(db, "SELECT data FROM items LIMIT 1").rows == [["<2 bytes>"]]


def test_duplicate_column_names_are_made_unique(db):
    assert run(db, "SELECT name, name FROM items LIMIT 1").columns == ["name", "name_2"]


def test_authorizer_blocks_tables_outside_the_allow_list(db):
    with pytest.raises(QueryExecutionError, match="not allowed"):
        run(db, "SELECT token FROM secrets")


def test_authorizer_blocks_blocked_functions(db):
    with pytest.raises(QueryExecutionError):
        run(db, "SELECT randomblob(10) FROM items")


def test_connection_is_read_only(db):
    with pytest.raises(QueryExecutionError):
        run(db, "DELETE FROM items")
    assert run(db, "SELECT COUNT(*) FROM items").rows == [[50]]


def test_runaway_query_is_interrupted(db):
    sql = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT COUNT(*) FROM n"
    with pytest.raises(QueryTimeoutError, match="time limit"):
        run(db, sql, timeout_ms=150)


def test_sql_errors_are_reported(db):
    with pytest.raises(QueryExecutionError, match="no such column"):
        run(db, "SELECT nope FROM items")


async def test_executor_limits_concurrency(db):
    executor = Executor(max_concurrent=2, max_rows=100, timeout_ms=2000)
    results = await asyncio.gather(*(executor.run(db, "SELECT COUNT(*) FROM items", TABLES) for _ in range(20)))
    assert all(r.rows == [[50]] for r in results)
