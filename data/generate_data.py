"""
Generates a synthetic e-commerce analytics dataset and loads it into DuckDB.

Schema (TPC-H-style star schema):
    customers   (~50,000 rows)
    products    (~5,000 rows)
    orders      (~200,000 rows)
    order_items (~550,000+ rows)   <- main fact table, satisfies the 500K+ record target

Deterministic (seeded) so re-runs are reproducible and no network access is
required to build a realistic, sizeable dataset.
"""
from __future__ import annotations

import os
import sys
import time

import duckdb
import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
N_CUSTOMERS = 50_000
N_PRODUCTS = 5_000
N_ORDERS = 210_000
MIN_ITEMS_PER_ORDER = 1
MAX_ITEMS_PER_ORDER = 4

DB_PATH = os.environ.get("DUCKDB_PATH", os.path.join(os.path.dirname(__file__), "analytics.duckdb"))

CATEGORIES = [
    "Electronics", "Home & Kitchen", "Sports & Outdoors", "Books",
    "Clothing", "Toys & Games", "Beauty", "Grocery", "Office Supplies", "Automotive",
]
REGIONS = ["North", "South", "East", "West", "Central"]
ORDER_STATUSES = ["completed", "completed", "completed", "completed", "cancelled", "returned"]


def _log(msg: str) -> None:
    print(f"[generate_data] {msg}", flush=True)


def build_customers(rng: np.random.Generator, fake: Faker) -> pd.DataFrame:
    _log(f"Generating {N_CUSTOMERS:,} customers...")
    signup_start = pd.Timestamp("2019-01-01")
    signup_end = pd.Timestamp("2026-09-01")
    signup_days = (signup_end - signup_start).days
    return pd.DataFrame({
        "customer_id": np.arange(1, N_CUSTOMERS + 1),
        "customer_name": [fake.name() for _ in range(N_CUSTOMERS)],
        "email": [fake.unique.email() for _ in range(N_CUSTOMERS)],
        "region": rng.choice(REGIONS, N_CUSTOMERS),
        "signup_date": signup_start + pd.to_timedelta(rng.integers(0, signup_days, N_CUSTOMERS), unit="D"),
        "is_active": rng.random(N_CUSTOMERS) > 0.12,
    })


def build_products(rng: np.random.Generator) -> pd.DataFrame:
    _log(f"Generating {N_PRODUCTS:,} products...")
    category = rng.choice(CATEGORIES, N_PRODUCTS)
    unit_cost = np.round(rng.gamma(shape=2.0, scale=15.0, size=N_PRODUCTS) + 1, 2)
    margin = rng.uniform(1.15, 2.2, N_PRODUCTS)
    return pd.DataFrame({
        "product_id": np.arange(1, N_PRODUCTS + 1),
        "product_name": [f"{cat} Item #{i}" for i, cat in zip(range(1, N_PRODUCTS + 1), category)],
        "category": category,
        "unit_cost": unit_cost,
        "unit_price": np.round(unit_cost * margin, 2),
    })


def build_orders(rng: np.random.Generator, customer_ids: np.ndarray) -> pd.DataFrame:
    _log(f"Generating {N_ORDERS:,} orders...")
    order_start = pd.Timestamp("2023-01-01")
    order_end = pd.Timestamp("2026-09-27")
    order_days = (order_end - order_start).days
    return pd.DataFrame({
        "order_id": np.arange(1, N_ORDERS + 1),
        "customer_id": rng.choice(customer_ids, N_ORDERS),
        "order_date": order_start + pd.to_timedelta(rng.integers(0, order_days, N_ORDERS), unit="D"),
        "status": rng.choice(ORDER_STATUSES, N_ORDERS),
    })


def build_order_items(rng: np.random.Generator, order_ids: np.ndarray, products: pd.DataFrame) -> pd.DataFrame:
    items_per_order = rng.integers(MIN_ITEMS_PER_ORDER, MAX_ITEMS_PER_ORDER + 1, len(order_ids))
    total_items = int(items_per_order.sum())
    _log(f"Generating {total_items:,} order line items (this is the 500K+ fact table)...")

    order_id_col = np.repeat(order_ids, items_per_order)
    product_idx = rng.integers(0, len(products), total_items)
    quantity = rng.integers(1, 6, total_items)
    unit_price = products["unit_price"].to_numpy()[product_idx]
    discount_pct = np.round(rng.choice([0, 0, 0, 0.05, 0.1, 0.15, 0.2], total_items), 2)
    line_total = np.round(unit_price * quantity * (1 - discount_pct), 2)

    return pd.DataFrame({
        "order_item_id": np.arange(1, total_items + 1),
        "order_id": order_id_col,
        "product_id": products["product_id"].to_numpy()[product_idx],
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_pct": discount_pct,
        "line_total": line_total,
    })


def main() -> None:
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    fake = Faker()
    Faker.seed(SEED)

    customers = build_customers(rng, fake)
    products = build_products(rng)
    orders = build_orders(rng, customers["customer_id"].to_numpy())
    order_items = build_order_items(rng, orders["order_id"].to_numpy(), products)

    _log(f"Writing to DuckDB at {DB_PATH} ...")
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    con = duckdb.connect(DB_PATH)
    con.register("customers_df", customers)
    con.register("products_df", products)
    con.register("orders_df", orders)
    con.register("order_items_df", order_items)

    con.execute("CREATE TABLE customers AS SELECT * FROM customers_df")
    con.execute("CREATE TABLE products AS SELECT * FROM products_df")
    con.execute("CREATE TABLE orders AS SELECT * FROM orders_df")
    con.execute("CREATE TABLE order_items AS SELECT * FROM order_items_df")

    con.execute("ALTER TABLE customers ADD PRIMARY KEY (customer_id)")
    con.execute("ALTER TABLE products ADD PRIMARY KEY (product_id)")
    con.execute("ALTER TABLE orders ADD PRIMARY KEY (order_id)")
    con.execute("ALTER TABLE order_items ADD PRIMARY KEY (order_item_id)")

    counts = con.execute(
        "SELECT 'customers', count(*) FROM customers "
        "UNION ALL SELECT 'products', count(*) FROM products "
        "UNION ALL SELECT 'orders', count(*) FROM orders "
        "UNION ALL SELECT 'order_items', count(*) FROM order_items"
    ).fetchall()
    con.close()

    _log("Row counts:")
    total = 0
    for name, n in counts:
        _log(f"  {name:<14} {n:>10,}")
        total += n
    _log(f"  {'TOTAL':<14} {total:>10,}")
    _log(f"Done in {time.time() - t0:.1f}s")

    if total < 500_000:
        _log("WARNING: total row count is below 500,000 — adjust N_ORDERS / item ranges.")
        sys.exit(1)


if __name__ == "__main__":
    main()
