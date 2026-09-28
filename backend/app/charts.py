import re

TIME_NAME = re.compile(r"(^|_)(date|day|week|month|year|quarter|period|time|hour)(_|$)")
TIME_VALUE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-\d{2})?)?([ T]\d{2}:\d{2}(:\d{2})?)?$|^\d{4}-(W\d{2}|Q[1-4])$")
ID_NAME = re.compile(r"(^|_)id$")
MAX_BAR_ROWS = 50
MAX_PIE_ROWS = 6


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def recommend(columns: list[str], rows: list[list]) -> dict:
    if not rows or not columns:
        return {"type": "table", "x": None, "y": []}
    numeric = [
        i
        for i, c in enumerate(columns)
        if not ID_NAME.search(c.lower())
        and all(_is_number(r[i]) or r[i] is None for r in rows)
        and any(_is_number(r[i]) for r in rows)
    ]
    labels = [i for i in range(len(columns)) if i not in numeric]

    if len(rows) == 1 and numeric and not labels and len(numeric) <= 4:
        return {"type": "metric", "x": None, "y": [columns[i] for i in numeric]}

    def is_time(i: int) -> bool:
        values = [r[i] for r in rows if r[i] is not None]
        named = TIME_NAME.search(columns[i].lower()) is not None
        if not values:
            return False
        if i in labels:
            return named or all(TIME_VALUE.match(str(v)) for v in values)
        return named and all(isinstance(v, int) and 1900 <= v <= 2100 for v in values)

    time_col = next((i for i in range(len(columns)) if is_time(i)), None)
    if time_col is not None:
        measures = [i for i in numeric if i != time_col]
        if measures and len(rows) >= 2:
            return {"type": "line", "x": columns[time_col], "y": [columns[i] for i in measures[:4]]}

    if not labels or not numeric:
        return {"type": "table", "x": None, "y": []}
    x = labels[0]
    measures = numeric[:3]
    if (
        2 <= len(rows) <= MAX_PIE_ROWS
        and len(measures) == 1
        and share_like(columns[measures[0]])
        and all((r[measures[0]] or 0) >= 0 for r in rows)
    ):
        return {"type": "pie", "x": columns[x], "y": [columns[measures[0]]]}
    if 2 <= len(rows) <= MAX_BAR_ROWS:
        return {"type": "bar", "x": columns[x], "y": [columns[i] for i in measures]}
    return {"type": "table", "x": columns[x], "y": [columns[i] for i in measures]}


def share_like(name: str) -> bool:
    return not re.search(r"(avg|average|mean|rate|pct|percent|ratio|margin|median|min|max)", name.lower())
