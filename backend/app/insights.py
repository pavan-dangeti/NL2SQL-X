"""Deterministic, verifiable highlights computed from the result set itself."""

from datetime import date

from app.charts import recommend, share_like


def _fmt(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 10_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _label(name: str) -> str:
    return name.replace("_", " ")


def summarize(columns: list[str], rows: list[list], chart: dict | None = None) -> list[str]:
    chart = chart or recommend(columns, rows)
    if chart["type"] not in {"line", "bar", "pie"} or not chart["y"]:
        return []
    x, y = columns.index(chart["x"]), columns.index(chart["y"][0])
    points = [(str(r[x]), float(r[y])) for r in rows if isinstance(r[y], (int, float)) and r[x] is not None]
    if len(points) < 2:
        return []
    measure = _label(columns[y])
    out = []

    if chart["type"] == "line":
        (first_label, first), (last_label, last) = points[0], points[-1]
        if first:
            change = (last - first) / abs(first) * 100
            direction = "up" if change >= 0 else "down"
            out.append(f"{measure.capitalize()} is {direction} {abs(change):.1f}% from {first_label} to {last_label}.")
        peak = max(points, key=lambda p: p[1])
        low = min(points, key=lambda p: p[1])
        out.append(f"Peak {measure} was {_fmt(peak[1])} in {peak[0]}; the lowest was {_fmt(low[1])} in {low[0]}.")
        if len(points) >= 3 and points[-2][1]:
            change = (last - points[-2][1]) / abs(points[-2][1]) * 100
            partial = " (month to date)" if last_label == date.today().strftime("%Y-%m") else ""
            out.append(f"{last_label}{partial} changed {change:+.1f}% versus {points[-2][0]}.")
        return out

    ranked = sorted(points, key=lambda p: p[1], reverse=True)
    total = sum(p[1] for p in points)
    top = ranked[0]
    if total > 0 and all(p[1] >= 0 for p in points) and share_like(columns[y]):
        out.append(f"{top[0]} leads with {_fmt(top[1])} ({top[1] / total * 100:.1f}% of the total {measure}).")
        if len(ranked) >= 5:
            share = sum(p[1] for p in ranked[:3]) / total * 100
            out.append(f"The top 3 account for {share:.1f}% of {measure}.")
    else:
        out.append(f"{top[0]} has the highest {measure} at {_fmt(top[1])}.")
    bottom = ranked[-1]
    if bottom[0] != top[0]:
        out.append(f"{bottom[0]} is lowest at {_fmt(bottom[1])}.")
    return out
