"""Deterministic e-commerce sample dataset. Dates are anchored to the build day so
questions like "last 30 days" always have data; the file is rebuilt when stale."""

import bisect
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DEMO_ID = "ecommerce"
DEMO_NAME = "E-commerce (sample)"
SEED = 20260927
VERSION = "2"

SCHEMA = """
CREATE TABLE regions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    country TEXT NOT NULL
);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    region_id INTEGER NOT NULL REFERENCES regions(id),
    segment TEXT NOT NULL,
    signup_date DATE NOT NULL
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL,
    cost REAL NOT NULL,
    stock INTEGER NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date DATE NOT NULL,
    status TEXT NOT NULL,
    channel TEXT NOT NULL,
    total_amount REAL NOT NULL
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    discount REAL NOT NULL DEFAULT 0
);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

REGIONS = [
    ("North America", "United States"),
    ("Europe", "Germany"),
    ("Asia Pacific", "Japan"),
    ("Latin America", "Brazil"),
    ("India", "India"),
    ("Middle East", "United Arab Emirates"),
]
FIRST = [
    "Ava",
    "Liam",
    "Noah",
    "Mia",
    "Aarav",
    "Sofia",
    "Kenji",
    "Lucas",
    "Priya",
    "Omar",
    "Emma",
    "Diego",
    "Hana",
    "Ethan",
    "Zara",
    "Mateo",
    "Isla",
    "Arjun",
    "Chloe",
    "Yusuf",
    "Lena",
    "Ravi",
    "Nora",
    "Felix",
]
LAST = [
    "Patel",
    "Garcia",
    "Tanaka",
    "Müller",
    "Silva",
    "Khan",
    "Smith",
    "Rossi",
    "Kim",
    "Nguyen",
    "Brown",
    "Haddad",
    "Iyer",
    "Costa",
    "Schmidt",
    "Wong",
    "Lopez",
    "Sato",
    "Reddy",
    "Evans",
]
SEGMENTS = [("Consumer", 0.6), ("Small Business", 0.3), ("Enterprise", 0.1)]
PRODUCTS = {
    "Electronics": [
        ("Quantum Laptop Pro", 1299),
        ("Apex Smartphone", 799),
        ("Sonic ANC Headphones", 199),
        ("Pixel Tablet 11", 449),
        ("Aero Smartwatch", 249),
        ("Nova 4K Monitor", 379),
        ("Echo Mini Speaker", 59),
        ("Volt Power Bank", 39),
    ],
    "Apparel": [
        ("Classic Denim Jacket", 89),
        ("Slim Fit Jeans", 49),
        ("Merino Wool Tee", 29),
        ("Trail Rain Shell", 139),
        ("Everyday Hoodie", 59),
        ("Linen Shirt", 45),
    ],
    "Home": [
        ("Smart Drip Coffee Maker", 119),
        ("LED Desk Lamp", 39),
        ("RoboVac 3000", 249),
        ("Air Purifier Max", 179),
        ("Chef Knife Set", 99),
        ("Cast Iron Skillet", 49),
    ],
    "Sports": [
        ("Eco Grip Yoga Mat", 25),
        ("Hex Dumbbell Set", 69),
        ("Trail Running Shoes", 99),
        ("Carbon Road Helmet", 149),
        ("Hydro Bottle 1L", 19),
    ],
    "Beauty": [
        ("Vitamin C Serum", 34),
        ("Hydrating Face Cream", 28),
        ("Travel Grooming Kit", 42),
        ("Silk Hair Dryer", 159),
    ],
}
STATUSES = [("Delivered", 0.72), ("Shipped", 0.1), ("Processing", 0.06), ("Cancelled", 0.07), ("Returned", 0.05)]
REGION_WEIGHTS = [34, 26, 16, 9, 10, 5]
CHANNELS = [("Web", 0.55), ("Mobile App", 0.35), ("Marketplace", 0.1)]
DAYS = 540
SEASON = {1: 0.85, 2: 0.9, 7: 1.1, 11: 1.3, 12: 1.45}


def _pick(rng: random.Random, weighted: list[tuple[str, float]]) -> str:
    return rng.choices([v for v, _ in weighted], weights=[w for _, w in weighted])[0]


def build(path: Path, today: date | None = None) -> None:
    today = today or date.today()
    rng = random.Random(SEED)
    tmp = path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO regions VALUES (?,?,?)", [(i + 1, *r) for i, r in enumerate(REGIONS)])

        customers = []
        for cid in range(1, 241):
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            email = f"{name.lower().replace(' ', '.').replace('ü', 'u')}.{cid}@example.com"
            signup = today - timedelta(days=rng.randint(60, DAYS + 240))
            customers.append(
                (
                    cid,
                    name,
                    email,
                    rng.choices(range(1, len(REGIONS) + 1), weights=REGION_WEIGHTS)[0],
                    _pick(rng, SEGMENTS),
                    signup.isoformat(),
                )
            )
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)

        products, pid = [], 0
        for category, items in PRODUCTS.items():
            for name, price in items:
                pid += 1
                cost = round(price * rng.uniform(0.45, 0.7), 2)
                products.append((pid, name, category, float(price), cost, rng.randint(0, 400)))
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", products)

        popularity = [rng.uniform(0.3, 3.0) for _ in products]
        by_signup = sorted(customers, key=lambda c: c[5])
        signups = [c[5] for c in by_signup]
        days = [today - timedelta(days=d) for d in range(DAYS, 0, -1)]
        day_weights = [(1 + 0.9 * i / len(days)) * SEASON.get(d.month, 1.0) for i, d in enumerate(days)]
        orders, items, item_id = [], [], 0
        for oid in range(1, 4201):
            order_day = rng.choices(days, weights=day_weights)[0]
            eligible = max(1, bisect.bisect_right(signups, order_day.isoformat()))
            cust = by_signup[rng.randrange(eligible)]
            status = _pick(rng, STATUSES)
            if (today - order_day).days < 4:
                status = rng.choice(["Processing", "Shipped"])
            total = 0.0
            for _ in range(rng.choices([1, 2, 3, 4], weights=[55, 28, 12, 5])[0]):
                item_id += 1
                prod = rng.choices(products, weights=popularity)[0]
                qty = rng.choices([1, 2, 3], weights=[75, 18, 7])[0]
                discount = rng.choice([0, 0, 0, 0.05, 0.1, 0.15])
                items.append((item_id, oid, prod[0], qty, prod[3], discount))
                total += qty * prod[3] * (1 - discount)
            orders.append((oid, cust[0], order_day.isoformat(), status, _pick(rng, CHANNELS), round(total, 2)))
        orders.sort(key=lambda o: o[2])
        remap = {o[0]: i + 1 for i, o in enumerate(orders)}
        conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", [(remap[o[0]], *o[1:]) for o in orders])
        conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", [(i[0], remap[i[1]], *i[2:]) for i in items])
        conn.executemany("INSERT INTO _meta VALUES (?, ?)", [("built_on", today.isoformat()), ("version", VERSION)])
        conn.commit()
    finally:
        conn.close()
    tmp.replace(path)


def built_on(path: Path) -> date | None:
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = dict(conn.execute("SELECT key, value FROM _meta").fetchall())
        finally:
            conn.close()
        return date.fromisoformat(meta["built_on"]) if meta.get("version") == VERSION else None
    except sqlite3.Error:
        return None


def ensure(path: Path, today: date | None = None) -> bool:
    """Builds or refreshes the sample database; returns True when it was (re)built."""
    today = today or datetime.now().date()
    if built_on(path) == today:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    build(path, today)
    return True
