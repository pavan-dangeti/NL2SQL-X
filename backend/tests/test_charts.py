import pytest

from app.charts import recommend


@pytest.mark.parametrize(
    ("columns", "rows", "expected"),
    [
        (["month", "revenue"], [["2026-01", 10.0], ["2026-02", 12.5], ["2026-03", 9.0]], "line"),
        (["order_date", "orders"], [["2026-01-01", 3], ["2026-01-02", 5]], "line"),
        (["year", "revenue"], [[2024, 10], [2025, 20]], "line"),
        (["region", "revenue"], [["EU", 10], ["US", 20], ["APAC", 5]], "pie"),
        (["region", "avg_order_value"], [["EU", 10], ["US", 20]], "bar"),
        (["product", "units"], [[f"p{i}", i] for i in range(12)], "bar"),
        (["product", "units"], [[f"p{i}", i] for i in range(80)], "table"),
        (["revenue"], [[1234.5]], "metric"),
        (["orders", "revenue"], [[10, 2000.0]], "metric"),
        (["name", "email"], [["a", "a@x"], ["b", "b@x"]], "table"),
        (["customer", "orders"], [["Ann", 3]], "table"),
        (["id", "total"], [[1, 5], [2, 7]], "pie"),
        (["region", "delta"], [["EU", -5], ["US", 3]], "bar"),
        ([], [], "table"),
        (["x"], [], "table"),
    ],
)
def test_chart_type(columns, rows, expected):
    assert recommend(columns, rows)["type"] == expected


def test_line_chart_uses_time_axis_and_all_measures():
    chart = recommend(["month", "revenue", "orders"], [["2026-01", 1, 2], ["2026-02", 3, 4]])
    assert chart == {"type": "line", "x": "month", "y": ["revenue", "orders"]}


def test_numeric_values_that_look_like_years_are_not_time():
    chart = recommend(["region", "orders"], [["EU", 2024], ["US", 2031], ["IN", 1999]])
    assert chart["type"] == "pie"
    assert chart["x"] == "region"


def test_nulls_do_not_break_detection():
    chart = recommend(["category", "revenue"], [["A", None], ["B", 5.0], [None, 2.0]])
    assert chart["type"] == "pie"
