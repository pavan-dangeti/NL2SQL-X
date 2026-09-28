import sqlite3

import pytest

from app.ingest import IngestError, build_dataset, identifier, infer, read_csv


def rows_of(path, table):
    conn = sqlite3.connect(path)
    try:
        cols = [r[1] + ":" + r[2] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        return cols, conn.execute(f'SELECT * FROM "{table}"').fetchall()
    finally:
        conn.close()


def test_builds_typed_tables_from_csv(tmp_path):
    csv = (
        b"Order ID,Customer Name,Amount ($),Order Date,Is Gift\n"
        b'1,Ann,"$1,200.50",2026-01-05,yes\n'
        b"2,Bob,99,2026-01-06,no\n"
        b"3,Cy,,2026-01-07,\n"
    )
    tables = build_dataset(tmp_path / "d.db", [("Q1 Sales.csv", csv)], 1000, 50)
    assert tables[0].name == "q1_sales"
    cols, rows = rows_of(tmp_path / "d.db", "q1_sales")
    assert cols == ["order_id:INTEGER", "customer_name:TEXT", "amount:REAL", "order_date:DATE", "is_gift:TEXT"]
    assert rows[0] == (1, "Ann", 1200.5, "2026-01-05", "yes")
    assert rows[2][2] is None


def test_detects_semicolon_and_tab_delimiters(tmp_path):
    files = [("a.csv", b"x;y\n1;2\n3;4\n"), ("b.tsv", b"p\tq\nfoo\t1\nbar\t2\n")]
    tables = build_dataset(tmp_path / "d.db", files, 100, 10)
    assert [t.columns for t in tables] == [["x", "y"], ["p", "q"]]


def test_normalises_common_date_formats(tmp_path):
    build_dataset(tmp_path / "d.db", [("t.csv", b"day\n05/01/2026\n28/02/2026\n")], 100, 10)
    assert rows_of(tmp_path / "d.db", "t")[1] == [("2026-01-05",), ("2026-02-28",)]


def test_keeps_leading_zero_codes_as_text():
    assert infer(["00123", "04567"]) == "TEXT"
    assert infer(["123", "4567"]) == "INTEGER"
    assert infer(["1.5", "2"]) == "REAL"
    assert infer(["", "NULL"]) == "TEXT"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Order Date", "order_date"),
        ("2024 Revenue", "c_2024_revenue"),
        ("select", "select_"),
        ("", "col"),
        ("sqlite_seq", "sqlite_seq_"),
        ("Näme  (EUR)", "n_me_eur"),
    ],
)
def test_identifier_cleanup(raw, expected):
    assert identifier(raw, "col") == expected


def test_duplicate_headers_and_filenames_are_disambiguated(tmp_path):
    tables = build_dataset(tmp_path / "d.db", [("s.csv", b"a,a,A\n1,2,3\n"), ("s.csv", b"z\n1\n")], 10, 10)
    assert tables[0].columns == ["a", "a_2", "a_3"]
    assert [t.name for t in tables] == ["s", "s_2"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"a,b\n", "no data rows"),
        (b",,\n1,2,3\n", "column names"),
        (b"a,b,c\n" + b"1,2,3\n" * 20, "Too many rows"),
        (b"\x00\x01\x02binary", "CSV text"),
    ],
)
def test_rejects_bad_files(data, message):
    with pytest.raises(IngestError, match=message):
        read_csv(data, max_rows=10, max_columns=2 if message == "Too many columns" else 10)


def test_rejects_too_many_columns():
    with pytest.raises(IngestError, match="Too many columns"):
        read_csv(b"a,b,c\n1,2,3\n", max_rows=10, max_columns=2)


def test_failed_build_leaves_no_partial_file(tmp_path):
    with pytest.raises(IngestError):
        build_dataset(tmp_path / "d.db", [("ok.csv", b"a\n1\n"), ("bad.csv", b"")], 10, 10)
    assert not (tmp_path / "d.db").exists()
    assert not (tmp_path / "d.building").exists()


def test_short_rows_are_padded(tmp_path):
    build_dataset(tmp_path / "d.db", [("t.csv", b"a,b,c\n1\n2,x,y\n")], 10, 10)
    assert rows_of(tmp_path / "d.db", "t")[1] == [(1, None, None), (2, "x", "y")]
