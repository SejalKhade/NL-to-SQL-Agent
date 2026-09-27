"""Top-level orchestration: NL question -> generated SQL -> guardrail
validation -> execution -> results. This is the "ask()" entry point the
Streamlit app (and tests) call."""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd

from agent import config, guardrails, sql_chain

_con: duckdb.DuckDBPyConnection | None = None


def get_connection() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        _con = duckdb.connect(config.DUCKDB_PATH, read_only=True)
    return _con


@dataclass
class AskResult:
    question: str
    generated_sql: str
    executed: bool
    blocked_reasons: list[str]
    warnings: list[str]
    dataframe: pd.DataFrame | None = None
    error: str | None = None


def ask(question: str) -> AskResult:
    con = get_connection()

    try:
        raw_sql = sql_chain.generate_sql(question)
    except Exception as e:  # noqa: BLE001
        return AskResult(
            question=question, generated_sql="", executed=False,
            blocked_reasons=[f"SQL generation failed: {e}"], warnings=[],
        )

    validation = guardrails.validate_query(raw_sql, con, max_rows=config.MAX_ROWS_RETURNED)

    if not validation.ok:
        return AskResult(
            question=question, generated_sql=validation.sql, executed=False,
            blocked_reasons=validation.blocked_reasons, warnings=validation.warnings,
        )

    try:
        df = con.execute(validation.sql).fetchdf()
    except Exception as e:  # noqa: BLE001
        return AskResult(
            question=question, generated_sql=validation.sql, executed=False,
            blocked_reasons=[f"Execution failed unexpectedly after passing validation: {e}"],
            warnings=validation.warnings,
        )

    return AskResult(
        question=question, generated_sql=validation.sql, executed=True,
        blocked_reasons=[], warnings=validation.warnings, dataframe=df,
    )
