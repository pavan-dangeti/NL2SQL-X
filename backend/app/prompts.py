from dataclasses import dataclass

from app.schema import Schema

SYSTEM = """You are a senior analytics engineer who writes SQLite queries for business users.

Write exactly one read-only SQLite query (SELECT or WITH ... SELECT) that answers the question
using only the tables and columns in the schema below.

Rules:
- Use only columns that exist. Join through the listed foreign keys.
- Match the listed column values exactly (case and spelling) when filtering.
- Dates are ISO strings: use date('now', ...), strftime('%Y-%m', col) and comparisons on them.
  "Today" is {today}.
- Give every computed column a short snake_case alias (revenue, order_count, avg_order_value).
- Round money and averages with ROUND(x, 2). Order results in the most useful way, e.g. largest first,
  or chronologically for time series.
- Add LIMIT 100 unless the question asks for everything or the result is naturally small (aggregates).
- For "top N" questions use ORDER BY ... DESC LIMIT N.
- For monthly or daily trends return the period column first, then the measures.
- Never modify data, never use PRAGMA, ATTACH or system tables.
- If the question cannot be answered from this schema, set answerable to false, leave sql empty and
  explain what is missing in one sentence.

explanation: one or two plain-English sentences describing what the query returns and any
assumption you made (for example which statuses count as a sale).

SCHEMA
{schema}
{examples}"""

ECOMMERCE_NOTES = """
Business definitions for this dataset:
- Revenue counts orders whose status is 'Delivered' or 'Shipped' and uses orders.total_amount.
- Units sold come from order_items.quantity. Line revenue = quantity * unit_price * (1 - discount).
- Profit per line = quantity * (unit_price * (1 - discount) - products.cost).

Examples:
Q: Revenue by month for the last 6 months
SQL: SELECT strftime('%Y-%m', order_date) AS month, ROUND(SUM(total_amount), 2) AS revenue FROM orders WHERE status IN ('Delivered', 'Shipped') AND order_date >= date('now', 'start of month', '-5 months') GROUP BY month ORDER BY month
Q: Top 5 products by units sold in the last 30 days
SQL: SELECT p.name AS product, SUM(oi.quantity) AS units_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id WHERE o.order_date >= date('now', '-30 days') AND o.status NOT IN ('Cancelled', 'Returned') GROUP BY p.id ORDER BY units_sold DESC LIMIT 5
"""


@dataclass
class Turn:
    question: str
    sql: str


def system_prompt(schema: Schema, today: str, dataset_id: str) -> str:
    examples = ECOMMERCE_NOTES if dataset_id == "ecommerce" else ""
    return SYSTEM.format(schema=schema.to_prompt(), today=today, examples=examples)


def user_prompt(
    question: str, previous: Turn | None = None, failed_sql: str | None = None, error: str | None = None
) -> str:
    parts = []
    if previous:
        parts.append(
            "Previous question (the new one may be a follow-up that refines it):\n"
            f"{previous.question}\nPrevious SQL:\n{previous.sql}\n"
        )
    parts.append(f"Question:\n{question}")
    if failed_sql:
        parts.append(f"\nYour previous attempt failed.\nSQL:\n{failed_sql}\nError:\n{error}\nReturn a corrected query.")
    return "\n".join(parts)
