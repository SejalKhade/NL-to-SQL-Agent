"""Seeds the RAG store with schema DDL, business documentation, and
known-good (question, SQL) pairs — the "training" step, in Vanna's
terminology. Run via scripts/ingest_training_data.py."""
from __future__ import annotations

DDL_STATEMENTS = [
    """CREATE TABLE customers (
        customer_id BIGINT PRIMARY KEY,
        customer_name VARCHAR,
        email VARCHAR,
        region VARCHAR,          -- one of: North, South, East, West, Central
        signup_date DATE,
        is_active BOOLEAN
    );""",
    """CREATE TABLE products (
        product_id BIGINT PRIMARY KEY,
        product_name VARCHAR,
        category VARCHAR,        -- e.g. Electronics, Books, Grocery, ...
        unit_cost DOUBLE,
        unit_price DOUBLE
    );""",
    """CREATE TABLE orders (
        order_id BIGINT PRIMARY KEY,
        customer_id BIGINT REFERENCES customers(customer_id),
        order_date DATE,
        status VARCHAR           -- one of: completed, cancelled, returned
    );""",
    """CREATE TABLE order_items (
        order_item_id BIGINT PRIMARY KEY,
        order_id BIGINT REFERENCES orders(order_id),
        product_id BIGINT REFERENCES products(product_id),
        quantity INTEGER,
        unit_price DOUBLE,
        discount_pct DOUBLE,
        line_total DOUBLE        -- = unit_price * quantity * (1 - discount_pct)
    );""",
]

DOCUMENTATION = [
    "Revenue for a period is the sum of order_items.line_total, joined through "
    "orders on order_id, restricted to orders.status = 'completed'. Cancelled "
    "and returned orders should be excluded from revenue calculations.",
    "'Active customers' means customers.is_active = TRUE. A customer's region "
    "is stored directly on the customers table.",
    "Profit for a line item is (unit_price - product.unit_cost) * quantity * (1 - discount_pct); "
    "requires joining order_items to products on product_id.",
    "order_items is the primary fact table (500K+ rows) — one row per product per order.",
]

EXAMPLES = [
    ("How many customers do we have?",
     "SELECT count(*) AS customer_count FROM customers"),
    ("How many active customers are there per region?",
     "SELECT region, count(*) AS active_customers FROM customers "
     "WHERE is_active = TRUE GROUP BY region ORDER BY active_customers DESC"),
    ("What is our total revenue from completed orders?",
     "SELECT round(sum(oi.line_total), 2) AS total_revenue FROM order_items oi "
     "JOIN orders o ON oi.order_id = o.order_id WHERE o.status = 'completed'"),
    ("What are the top 10 best-selling products by revenue?",
     "SELECT p.product_name, round(sum(oi.line_total), 2) AS revenue "
     "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
     "JOIN orders o ON oi.order_id = o.order_id WHERE o.status = 'completed' "
     "GROUP BY p.product_name ORDER BY revenue DESC LIMIT 10"),
    ("Show monthly revenue for 2025.",
     "SELECT date_trunc('month', o.order_date) AS month, round(sum(oi.line_total), 2) AS revenue "
     "FROM order_items oi JOIN orders o ON oi.order_id = o.order_id "
     "WHERE o.status = 'completed' AND o.order_date >= DATE '2025-01-01' "
     "AND o.order_date < DATE '2026-01-01' "
     "GROUP BY month ORDER BY month"),
    ("Which product category generates the most profit?",
     "SELECT p.category, round(sum((oi.unit_price - p.unit_cost) * oi.quantity * (1 - oi.discount_pct)), 2) AS profit "
     "FROM order_items oi JOIN products p ON oi.product_id = p.product_id "
     "JOIN orders o ON oi.order_id = o.order_id WHERE o.status = 'completed' "
     "GROUP BY p.category ORDER BY profit DESC"),
    ("What percentage of orders are cancelled or returned?",
     "SELECT round(100.0 * sum(CASE WHEN status IN ('cancelled', 'returned') THEN 1 ELSE 0 END) / count(*), 2) "
     "AS pct_cancelled_or_returned FROM orders"),
    ("Who are our top 5 customers by total spend?",
     "SELECT c.customer_name, round(sum(oi.line_total), 2) AS total_spend "
     "FROM order_items oi JOIN orders o ON oi.order_id = o.order_id "
     "JOIN customers c ON o.customer_id = c.customer_id "
     "WHERE o.status = 'completed' GROUP BY c.customer_name ORDER BY total_spend DESC LIMIT 5"),
    ("How many orders were placed in each region last year?",
     "SELECT c.region, count(*) AS order_count FROM orders o "
     "JOIN customers c ON o.customer_id = c.customer_id "
     "WHERE o.order_date >= DATE '2025-01-01' AND o.order_date < DATE '2026-01-01' "
     "GROUP BY c.region ORDER BY order_count DESC"),
    ("What is the average order value?",
     "SELECT round(avg(order_total), 2) AS avg_order_value FROM ("
     "SELECT o.order_id, sum(oi.line_total) AS order_total FROM order_items oi "
     "JOIN orders o ON oi.order_id = o.order_id WHERE o.status = 'completed' "
     "GROUP BY o.order_id)"),
]
