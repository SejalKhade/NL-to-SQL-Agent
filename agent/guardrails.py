"""
Validation / guardrail layer that sits between "LLM generated some SQL" and
"we actually run it against the database".

A query is blocked (never executed) if it fails any check:
  1. parses as valid SQL at all
  2. is a single statement (no stacked / chained statements)
  3. is read-only (SELECT / WITH only — no DDL or DML)
  4. only references tables/columns that exist in the known schema
  5. passes a zero-cost dry run (DuckDB EXPLAIN) to catch semantic errors
     before touching real data

A query that passes all of the above but looks risky (e.g. no LIMIT on a
large table, an unconditioned cross join) is flagged as an "anomaly" and
has a safety LIMIT injected rather than being blocked outright.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import sqlglot
from sqlglot import exp

FORBIDDEN_STATEMENT_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
    exp.TruncateTable, exp.Attach, exp.Grant, exp.Copy, exp.Command,
)

LARGE_TABLE_ROW_THRESHOLD = 50_000  # tables above this size require a LIMIT or WHERE


@dataclass
class ValidationResult:
    ok: bool
    sql: str
    blocked_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _known_schema(con: duckdb.DuckDBPyConnection) -> dict[str, set[str]]:
    rows = con.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'main'"
    ).fetchall()
    schema: dict[str, set[str]] = {}
    for table, column in rows:
        schema.setdefault(table.lower(), set()).add(column.lower())
    return schema


def _table_row_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    counts = {}
    for (table,) in tables:
        n = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        counts[table.lower()] = n
    return counts


def _split_statements(sql: str) -> list[str]:
    return [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]


def _check_single_readonly_statement(sql: str, reasons: list[str]) -> list[exp.Expression] | None:
    try:
        statements = _split_statements(sql)
    except Exception as e:  # noqa: BLE001
        reasons.append(f"Could not parse SQL: {e}")
        return None

    if len(statements) == 0:
        reasons.append("No SQL statement found.")
        return None
    if len(statements) > 1:
        reasons.append("Multiple / stacked SQL statements are not allowed — only one SELECT is permitted.")
        return None

    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union, exp.With)):
        reasons.append(f"Only read-only SELECT queries are allowed, got: {type(stmt).__name__}.")
        return None

    for forbidden in FORBIDDEN_STATEMENT_TYPES:
        if isinstance(stmt, forbidden) or stmt.find(forbidden):
            reasons.append(f"Query contains a forbidden operation: {forbidden.__name__}.")
            return None

    return statements


def _collect_known_aliases(stmt: exp.Expression) -> set[str]:
    """Column-shaped names that are safe even though they're not real schema
    columns: SELECT-list aliases (e.g. `sum(x) AS revenue`, later used in
    ORDER BY/GROUP BY or by an outer query over a derived table) and CTE
    names. Scoping isn't tracked precisely — this is a guardrail against
    hallucinated tables/columns, not a full SQL binder — so aliases are
    collected query-wide rather than per-scope."""
    aliases: set[str] = set()
    for select_expr in stmt.find_all(exp.Select):
        for e in select_expr.expressions:
            if isinstance(e, exp.Alias) and e.alias:
                aliases.add(e.alias.lower())
    for cte in stmt.find_all(exp.CTE):
        if cte.alias:
            aliases.add(cte.alias.lower())
    return aliases


def _check_schema_references(stmt: exp.Expression, schema: dict[str, set[str]], reasons: list[str]) -> None:
    # Table aliases (e.g. "orders o") map an alias like "o" to the real table
    # "orders" — column references qualified by an alias need to resolve
    # through this, not be looked up as if "o" were a table name.
    alias_to_table = {
        t.alias.lower(): t.name.lower()
        for t in stmt.find_all(exp.Table) if t.alias and t.name
    }
    referenced_tables = {t.name.lower() for t in stmt.find_all(exp.Table) if t.name}
    unknown_tables = referenced_tables - set(schema.keys())
    if unknown_tables:
        reasons.append(f"References unknown table(s): {', '.join(sorted(unknown_tables))}.")
        return

    known_aliases = _collect_known_aliases(stmt)
    all_known_columns = set().union(*schema.values()) if schema else set()
    for col in stmt.find_all(exp.Column):
        col_name = col.name.lower() if col.name else ""
        if not col_name or col_name == "*" or col_name in known_aliases:
            continue
        table_hint = col.table.lower() if col.table else None
        resolved_table = alias_to_table.get(table_hint, table_hint) if table_hint else None
        if resolved_table and resolved_table in schema:
            if col_name not in schema[resolved_table]:
                reasons.append(f"Unknown column '{col.table}.{col.name}' — not found in schema.")
        elif not table_hint and col_name not in all_known_columns:
            reasons.append(f"Unknown column '{col.name}' — not found in any referenced table.")


def _dry_run(con: duckdb.DuckDBPyConnection, sql: str, reasons: list[str]) -> bool:
    """Cheap semantic check: ask DuckDB to plan the query without executing it."""
    try:
        con.execute(f"EXPLAIN {sql}")
        return True
    except Exception as e:  # noqa: BLE001
        reasons.append(f"Query failed dry-run validation (DuckDB EXPLAIN): {e}")
        return False


def _anomaly_scan(stmt: exp.Expression, table_row_counts: dict[str, int], warnings: list[str]) -> exp.Expression:
    """Flag (and where possible auto-mitigate) risky-but-technically-valid queries."""
    referenced_tables = {t.name.lower() for t in stmt.find_all(exp.Table) if t.name}
    touches_large_table = any(table_row_counts.get(t, 0) >= LARGE_TABLE_ROW_THRESHOLD for t in referenced_tables)

    has_limit = stmt.find(exp.Limit) is not None
    has_where = stmt.find(exp.Where) is not None
    has_aggregate = any(stmt.find(fn) for fn in (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max))

    if touches_large_table and not has_limit and not has_aggregate:
        warnings.append(
            "No LIMIT clause on a large table and no aggregation — "
            "auto-capping result set to prevent a runaway scan."
        )
        stmt = stmt.limit(10_000)

    if touches_large_table and not has_where and not has_aggregate:
        warnings.append("Query has no WHERE filter on a large table — this may scan the full table.")

    joins = list(stmt.find_all(exp.Join))
    for j in joins:
        if j.args.get("on") is None and j.kind not in ("CROSS",):
            warnings.append("Join without an ON condition detected — possible unintended cartesian product.")

    return stmt


def validate_query(sql: str, con: duckdb.DuckDBPyConnection, max_rows: int = 10_000) -> ValidationResult:
    reasons: list[str] = []
    warnings: list[str] = []

    statements = _check_single_readonly_statement(sql, reasons)
    if statements is None:
        return ValidationResult(ok=False, sql=sql, blocked_reasons=reasons)
    stmt = statements[0]

    schema = _known_schema(con)
    _check_schema_references(stmt, schema, reasons)
    if reasons:
        return ValidationResult(ok=False, sql=sql, blocked_reasons=reasons)

    row_counts = _table_row_counts(con)
    stmt = _anomaly_scan(stmt, row_counts, warnings)

    # Hard safety net regardless of anomaly scan outcome.
    if stmt.find(exp.Limit) is None and not any(stmt.find(fn) for fn in (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)):
        stmt = stmt.limit(max_rows)

    final_sql = stmt.sql(dialect="duckdb")

    if not _dry_run(con, final_sql, reasons):
        return ValidationResult(ok=False, sql=final_sql, blocked_reasons=reasons)

    return ValidationResult(ok=True, sql=final_sql, warnings=warnings)
