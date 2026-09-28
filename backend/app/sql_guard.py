"""Static validation of generated SQL. The executor adds a second, runtime layer
(read-only connection + SQLite authorizer), so this module never has to be perfect
on its own."""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

BLOCKED_FUNCTIONS = {
    "load_extension",
    "readfile",
    "writefile",
    "edit",
    "fts3_tokenizer",
    "sqlite_offset",
    "zeroblob",
    "randomblob",
    "sqlite_compileoption_get",
    "sqlite_compileoption_used",
    "sqlite_source_id",
    "sqlite_version",
}
WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Merge,
    exp.Command,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)


class UnsafeSQLError(ValueError):
    pass


@dataclass(frozen=True)
class CheckedSQL:
    sql: str
    tables: frozenset[str]


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip().rstrip(";").strip()


def check(sql: str, allowed_tables: set[str]) -> CheckedSQL:
    sql = strip_fences(sql)
    if not sql:
        raise UnsafeSQLError("The generated query is empty.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except ParseError as exc:
        raise UnsafeSQLError(f"The generated SQL could not be parsed: {_first_line(exc)}") from exc
    if len(statements) != 1:
        raise UnsafeSQLError("Only a single statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise UnsafeSQLError("Only read-only SELECT queries are allowed.")
    if any(isinstance(node, WRITE_NODES) for node in tree.walk()):
        raise UnsafeSQLError("Only read-only SELECT queries are allowed.")

    for fn in tree.find_all(exp.Anonymous, exp.Func):
        name = (fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()).lower()
        if name in BLOCKED_FUNCTIONS:
            raise UnsafeSQLError(f"The function {name}() is not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    lookup = {t.lower(): t for t in allowed_tables}
    tables = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise UnsafeSQLError("Table-valued functions are not allowed.")
        name = table.name.lower()
        if not name or name in cte_names:
            continue
        if table.args.get("db") or name not in lookup:
            raise UnsafeSQLError(f"Unknown or restricted table: {table.sql(dialect='sqlite')}")
        tables.add(lookup[name])
    return CheckedSQL(sql=sql, tables=frozenset(tables))


def pretty(sql: str) -> str:
    try:
        return sqlglot.transpile(sql, read="sqlite", write="sqlite", pretty=True)[0]
    except ParseError:
        return sql


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0][:200]
