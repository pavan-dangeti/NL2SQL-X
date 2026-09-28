"""Concurrent load test against a running server.

    python scripts/load_test.py --base http://localhost:8000 --users 50 --seconds 30

Each simulated user loops through streamed questions, edited SQL, table
previews and history reads. Reports latency percentiles per endpoint and
fails on any unexpected status code.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid

import httpx

QUESTIONS = [
    "Revenue by month for the last 12 months",
    "Top 10 products by revenue",
    "Revenue share by region",
    "Average order value by channel",
    "Profit margin by category",
    "Return rate by category",
    "Top 10 customers by lifetime value",
    "Total revenue this year",
]


def sql_variant(rng: random.Random) -> str:
    days = rng.randint(7, 400)
    return (
        "SELECT c.segment, COUNT(*) AS orders, ROUND(SUM(o.total_amount), 2) AS revenue FROM orders o "
        f"JOIN customers c ON c.id = o.customer_id WHERE o.order_date >= date('now', '-{days} days') "
        "GROUP BY c.segment ORDER BY revenue DESC"
    )


async def user(base: str, deadline: float, stats: dict, errors: list, seed: int) -> None:
    rng = random.Random(seed)
    headers = {"X-Client-Id": f"load-{uuid.uuid4().hex[:12]}"}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30) as client:
        while time.perf_counter() < deadline:
            kind = rng.choices(["ask", "sql", "preview", "history"], weights=[4, 3, 2, 1])[0]
            started = time.perf_counter()
            if kind == "ask":
                r = await client.post("/api/v1/query", json={"question": rng.choice(QUESTIONS)},
                                      headers={"Accept": "text/event-stream"})
                ok = r.status_code == 200 and "event: result" in r.text
            elif kind == "sql":
                r = await client.post("/api/v1/sql", json={"sql": sql_variant(rng)})
                ok = r.status_code == 200 and r.json()["row_count"] == 3
            elif kind == "preview":
                table = rng.choice(["orders", "customers", "products"])
                r = await client.get(f"/api/v1/datasets/ecommerce/tables/{table}/preview")
                ok = r.status_code == 200
            else:
                r = await client.get("/api/v1/history")
                ok = r.status_code == 200
            stats.setdefault(kind, []).append((time.perf_counter() - started) * 1000)
            if not ok:
                errors.append(f"{kind}: {r.status_code} {r.text[:120]}")


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(p * len(ordered)))], 1)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--seconds", type=int, default=30)
    args = ap.parse_args()
    stats: dict[str, list[float]] = {}
    errors: list[str] = []
    started = time.perf_counter()
    deadline = started + args.seconds
    await asyncio.gather(*(user(args.base, deadline, stats, errors, i) for i in range(args.users)))
    elapsed = time.perf_counter() - started
    total = sum(len(v) for v in stats.values())
    report = {
        "users": args.users,
        "seconds": round(elapsed, 1),
        "requests": total,
        "throughput_rps": round(total / elapsed, 1),
        "errors": len(errors),
        "latency_ms": {
            k: {"count": len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95), "p99": pct(v, 0.99),
                "mean": round(statistics.mean(v), 1)}
            for k, v in sorted(stats.items())
        },
        "sample_errors": errors[:5],
    }
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
