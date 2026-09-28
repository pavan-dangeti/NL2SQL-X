"""Schema introspection plus lightweight column profiles (distinct values, ranges)
that make the model's SQL far more accurate on filters like status = 'Delivered'."""

import re
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

HIDDEN = re.compile(r"^(sqlite_|_meta$)")
DATE_VALUE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")
MAX_SAMPLE_VALUES = 12


@dataclass
class Column:
    name: str
    type: str
    primary_key: bool
    nullable: bool
    values: list[str] | None = None
    min: str | float | None = None
    max: str | float | None = None


@dataclass
class ForeignKey:
    column: str
    references_table: str
    references_column: str


@dataclass
class Table:
    name: str
    row_count: int
    columns: list[Column] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)


@dataclass
class Schema:
    tables: list[Table]

    @property
    def table_names(self) -> set[str]:
        return {t.name for t in self.tables}

    def to_dict(self) -> dict:
        return {"tables": [asdict(t) for t in self.tables]}

    def to_prompt(self) -> str:
        lines = []
        for t in self.tables:
            lines.append(f"TABLE {_q(t.name)} ({t.row_count} rows)")
            for c in t.columns:
                notes = []
                if c.primary_key:
                    notes.append("primary key")
                fk = next((f for f in t.foreign_keys if f.column == c.name), None)
                if fk:
                    notes.append(f"references {_q(fk.references_table)}.{_q(fk.references_column)}")
                if c.values is not None:
                    notes.append("values: " + ", ".join(repr(v) for v in c.values))
                elif c.min is not None:
                    notes.append(f"range {c.min} .. {c.max}")
                suffix = f"  -- {'; '.join(notes)}" if notes else ""
                lines.append(f"  {_q(c.name)} {c.type or 'ANY'}{suffix}")
            lines.append("")
        return "\n".join(lines).strip()


def _q(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) else '"' + name.replace('"', '""') + '"'


def introspect(db_path: Path) -> Schema:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        names = [
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
        ]
        tables = []
        for name in names:
            if HIDDEN.match(name):
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            table = Table(name=name, row_count=count)
            for col in conn.execute("SELECT * FROM pragma_table_info(?)", (name,)):
                column = Column(col["name"], col["type"].upper(), bool(col["pk"]), not col["notnull"] and not col["pk"])
                if not column.primary_key and count:
                    _profile(conn, quoted, column)
                table.columns.append(column)
            table.foreign_keys = [
                ForeignKey(fk["from"], fk["table"], fk["to"] or "id")
                for fk in conn.execute("SELECT * FROM pragma_foreign_key_list(?)", (name,))
            ]
            tables.append(table)
        return Schema(tables)
    finally:
        conn.close()


def _profile(conn: sqlite3.Connection, table: str, column: Column) -> None:
    col = '"' + column.name.replace('"', '""') + '"'
    if column.name.lower() in {"email", "name"} or column.name.lower().endswith(("_email", "_name", "_id")):
        return
    if column.type in {"INTEGER", "REAL", "NUMERIC", "FLOAT", "DOUBLE"}:
        lo, hi = conn.execute(f"SELECT MIN({col}), MAX({col}) FROM {table}").fetchone()
        column.min, column.max = lo, hi
        return
    distinct = conn.execute(
        f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL GROUP BY {col} ORDER BY COUNT(*) DESC LIMIT ?",
        (MAX_SAMPLE_VALUES + 1,),
    ).fetchall()
    values = [str(r[0]) for r in distinct]
    if values and all(DATE_VALUE.match(v) for v in values):
        column.min, column.max = conn.execute(f"SELECT MIN({col}), MAX({col}) FROM {table}").fetchone()
    elif 0 < len(values) <= MAX_SAMPLE_VALUES and all(len(v) <= 40 for v in values):
        column.values = sorted(values)


class SchemaCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[Path, tuple[float, Schema]] = {}

    def get(self, db_path: Path) -> Schema:
        mtime = db_path.stat().st_mtime
        with self._lock:
            hit = self._items.get(db_path)
            if hit and hit[0] == mtime:
                return hit[1]
        schema = introspect(db_path)
        with self._lock:
            self._items[db_path] = (mtime, schema)
        return schema

    def forget(self, db_path: Path) -> None:
        with self._lock:
            self._items.pop(db_path, None)
