import pytest

from app.sql_guard import UnsafeSQLError, check, pretty, strip_fences

TABLES = {"orders", "customers", "products"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders",
        "select id from orders;",
        "SELECT c.name, COUNT(*) AS n FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.name",
        "WITH recent AS (SELECT * FROM orders WHERE order_date > date('now','-30 days')) SELECT COUNT(*) FROM recent",
        "SELECT name FROM products UNION SELECT name FROM customers",
        "SELECT strftime('%Y-%m', order_date) AS m, SUM(total_amount) FROM orders GROUP BY m",
        "SELECT * FROM ORDERS",
        "SELECT (SELECT COUNT(*) FROM customers) AS c",
        "SELECT CASE WHEN total_amount > 100 THEN 'big' ELSE 'small' END AS size FROM orders",
        "SELECT 'drop table orders' AS text FROM orders",
    ],
)
def test_allows_read_only_queries(sql):
    assert check(sql, TABLES).sql


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("DROP TABLE orders", "SELECT"),
        ("DELETE FROM orders", "SELECT"),
        ("UPDATE orders SET status = 'x'", "SELECT"),
        ("INSERT INTO orders VALUES (1)", "SELECT"),
        ("SELECT 1; DROP TABLE orders", "single statement"),
        ("SELECT 1; SELECT 2", "single statement"),
        ("PRAGMA table_info(orders)", "SELECT"),
        ("ATTACH DATABASE '/tmp/x.db' AS x", "SELECT"),
        ("SELECT * FROM sqlite_master", "restricted table"),
        ("SELECT * FROM history", "restricted table"),
        ("SELECT * FROM main.orders", "restricted table"),
        ("SELECT load_extension('evil')", "load_extension"),
        ("SELECT readfile('/etc/passwd')", "readfile"),
        ("SELECT * FROM pragma_table_info('orders')", "Table-valued"),
        ("", "empty"),
        ("   ;  ", "empty"),
        ("SELEC * FORM orders", "SELECT"),
        ("CREATE TABLE t AS SELECT * FROM orders", "SELECT"),
        ("SELECT * FROM (", "parsed"),
        ("SELECT * FROM json_each('[1]')", "Table-valued"),
    ],
)
def test_blocks_unsafe_queries(sql, message):
    with pytest.raises(UnsafeSQLError, match=message):
        check(sql, TABLES)


def test_reports_tables_used_without_ctes():
    checked = check("WITH a AS (SELECT * FROM orders) SELECT * FROM a JOIN customers c ON 1=1", TABLES)
    assert checked.tables == {"orders", "customers"}


def test_strips_markdown_fences_and_semicolons():
    assert strip_fences("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert check("```sql\nSELECT * FROM orders;\n```", TABLES).sql == "SELECT * FROM orders"


def test_pretty_formats_and_survives_bad_sql():
    assert "\n" in pretty("SELECT id, status FROM orders WHERE total_amount > 10")
    assert pretty("not sql at all (((") == "not sql at all ((("
