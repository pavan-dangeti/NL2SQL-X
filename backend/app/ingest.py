"""CSV to SQLite ingestion with header cleanup and type inference."""

import csv
import io
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d %b %Y", "%b %d, %Y")
DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%SZ")
RESERVED = {
    "select",
    "from",
    "where",
    "group",
    "order",
    "by",
    "table",
    "index",
    "join",
    "limit",
    "union",
    "case",
    "when",
    "then",
    "else",
    "end",
    "and",
    "or",
    "not",
    "null",
    "values",
    "default",
    "primary",
    "key",
}
NULLS = {"", "null", "none", "n/a", "na", "nan", "-"}
SAMPLE = 2000


class IngestError(ValueError):
    pass


@dataclass
class TableInfo:
    name: str
    rows: int
    columns: list[str]


def identifier(raw: str, fallback: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", raw.strip()).strip("_").lower()
    if not name:
        name = fallback
    if name[0].isdigit():
        name = f"c_{name}"
    if name in RESERVED or name.startswith("sqlite_"):
        name = f"{name}_"
    return name[:60]


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        seen.setdefault(n, 1)
        out.append(n)
    return out


def _number(v: str) -> str:
    v = v.strip().replace(",", "")
    for sym in ("$", "€", "£", "₹", "%"):
        v = v.replace(sym, "")
    return v.strip()


def _is_code(v: str) -> bool:
    return bool(re.match(r"^0\d", v.strip()))


def _is_int(v: str) -> bool:
    return bool(re.fullmatch(r"[-+]?\d{1,18}", _number(v))) and not _is_code(v)


def _is_real(v: str) -> bool:
    if _is_code(v):
        return False
    try:
        float(_number(v))
        return v.strip().lower() not in {"inf", "-inf", "nan", "infinity"}
    except ValueError:
        return False


def _parse_date(v: str, formats: tuple[str, ...]) -> str | None:
    v = v.strip()
    for fmt in formats:
        try:
            parsed = datetime.strptime(v, fmt)
        except ValueError:
            continue
        return parsed.strftime("%Y-%m-%d %H:%M:%S" if formats is DATETIME_FORMATS else "%Y-%m-%d")
    return None


def infer(values: list[str]) -> str:
    present = [v for v in values if v.strip().lower() not in NULLS]
    if not present:
        return "TEXT"
    if all(_is_int(v) for v in present):
        return "INTEGER"
    if all(_is_real(v) for v in present):
        return "REAL"
    if all(_parse_date(v, DATE_FORMATS) for v in present):
        return "DATE"
    if all(_parse_date(v, DATETIME_FORMATS) or _parse_date(v, DATE_FORMATS) for v in present):
        return "DATETIME"
    return "TEXT"


def convert(value: str, kind: str):
    if value.strip().lower() in NULLS:
        return None
    try:
        if kind == "INTEGER":
            return int(_number(value))
        if kind == "REAL":
            return float(_number(value))
    except ValueError:
        return value
    if kind == "DATE":
        return _parse_date(value, DATE_FORMATS) or value
    if kind == "DATETIME":
        day = _parse_date(value, DATE_FORMATS)
        return _parse_date(value, DATETIME_FORMATS) or (f"{day} 00:00:00" if day else value)
    return value.strip()


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise IngestError("File encoding not recognised.")


def read_csv(data: bytes, max_rows: int, max_columns: int) -> tuple[list[str], list[list[str]]]:
    text = decode(data)
    if "\x00" in text[:4096]:
        raise IngestError("This does not look like a CSV text file.")
    try:
        dialect = csv.Sniffer().sniff(text[:16384], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise IngestError("The file is empty.") from exc
    except csv.Error as exc:
        raise IngestError(f"Could not read CSV: {exc}") from exc
    if not any(h.strip() for h in header):
        raise IngestError("The first row must contain column names.")
    if len(header) > max_columns:
        raise IngestError(f"Too many columns ({len(header)}); the limit is {max_columns}.")
    rows = []
    try:
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            if len(rows) >= max_rows:
                raise IngestError(f"Too many rows; the limit is {max_rows:,}.")
            rows.append((row + [""] * len(header))[: len(header)])
    except csv.Error as exc:
        raise IngestError(f"Could not read CSV near row {len(rows) + 2}: {exc}") from exc
    if not rows:
        raise IngestError("The file has a header but no data rows.")
    return header, rows


def load_table(conn: sqlite3.Connection, table: str, header: list[str], rows: list[list[str]]) -> TableInfo:
    columns = _unique([identifier(h, f"column_{i + 1}") for i, h in enumerate(header)])
    kinds = [infer([r[i] for r in rows[:SAMPLE]]) for i in range(len(columns))]
    cols_sql = ", ".join(f'"{c}" {k}' for c, k in zip(columns, kinds, strict=True))
    conn.execute(f'CREATE TABLE "{table}" ({cols_sql})')
    placeholders = ",".join("?" * len(columns))
    conn.executemany(
        f'INSERT INTO "{table}" VALUES ({placeholders})',
        ([convert(v, k) for v, k in zip(row, kinds, strict=True)] for row in rows),
    )
    return TableInfo(table, len(rows), columns)


def build_dataset(path: Path, files: list[tuple[str, bytes]], max_rows: int, max_columns: int) -> list[TableInfo]:
    tmp = path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    tables: list[TableInfo] = []
    try:
        used: set[str] = set()
        for filename, data in files:
            name = identifier(Path(filename).stem, "data")
            base, n = name, 1
            while name in used:
                n += 1
                name = f"{base}_{n}"
            used.add(name)
            header, rows = read_csv(data, max_rows, max_columns)
            tables.append(load_table(conn, name, header, rows))
        conn.commit()
    except Exception:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()
    tmp.replace(path)
    return tables
