"""Unit tests for the guardrail / anomaly-check layer. These run against a
tiny in-memory DuckDB fixture — no API key or trained vector store needed."""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import guardrails  # noqa: E402


@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE customers (customer_id BIGINT, customer_name VARCHAR, region VARCHAR)")
    c.execute("INSERT INTO customers VALUES (1, 'Alice', 'North'), (2, 'Bob', 'South')")
    c.execute("CREATE TABLE orders (order_id BIGINT, customer_id BIGINT, status VARCHAR)")
    c.execute("INSERT INTO orders VALUES (1, 1, 'completed'), (2, 2, 'cancelled')")
    yield c
    c.close()


def test_valid_select_passes(con):
    result = guardrails.validate_query("SELECT customer_id, customer_name FROM customers", con)
    assert result.ok
    assert "customer_name" in result.sql


def test_blocks_drop_table(con):
    result = guardrails.validate_query("DROP TABLE customers", con)
    assert not result.ok
    assert any("forbidden" in r.lower() or "select" in r.lower() for r in result.blocked_reasons)


def test_blocks_delete(con):
    result = guardrails.validate_query("DELETE FROM customers WHERE customer_id = 1", con)
    assert not result.ok


def test_blocks_update(con):
    result = guardrails.validate_query("UPDATE customers SET region = 'East' WHERE customer_id = 1", con)
    assert not result.ok


def test_blocks_stacked_statements(con):
    result = guardrails.validate_query(
        "SELECT * FROM customers; DROP TABLE customers;", con
    )
    assert not result.ok
    assert any("multiple" in r.lower() or "stacked" in r.lower() for r in result.blocked_reasons)


def test_blocks_unknown_table(con):
    result = guardrails.validate_query("SELECT * FROM nonexistent_table", con)
    assert not result.ok
    assert any("unknown table" in r.lower() for r in result.blocked_reasons)


def test_blocks_unknown_column(con):
    result = guardrails.validate_query("SELECT not_a_real_column FROM customers", con)
    assert not result.ok
    assert any("unknown column" in r.lower() for r in result.blocked_reasons)


def test_blocks_syntactically_invalid_sql(con):
    result = guardrails.validate_query("SELEKT * FROM customers", con)
    assert not result.ok


def test_join_without_on_raises_warning(con):
    result = guardrails.validate_query(
        "SELECT customers.customer_name, orders.status FROM customers JOIN orders", con
    )
    # Not blocked outright, but flagged as a potential cartesian join.
    assert result.ok
    assert any("cartesian" in w.lower() or "join" in w.lower() for w in result.warnings)


def test_auto_adds_limit_when_missing(con):
    result = guardrails.validate_query("SELECT * FROM customers", con, max_rows=1)
    assert result.ok
    assert "LIMIT" in result.sql.upper()


def test_aggregate_query_not_forced_to_limit(con):
    result = guardrails.validate_query("SELECT count(*) FROM customers", con)
    assert result.ok
