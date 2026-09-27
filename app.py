"""Streamlit UI for the NL-to-SQL analytics agent."""
from __future__ import annotations

import duckdb
import streamlit as st

from agent import config, executor, train_examples, vectorstore

st.set_page_config(page_title="NL-to-SQL Analytics Agent", page_icon="📊", layout="wide")


@st.cache_data(show_spinner=False)
def _schema_overview() -> dict[str, list[str]]:
    con = executor.get_connection()
    rows = con.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
    ).fetchall()
    schema: dict[str, list[str]] = {}
    for table, col in rows:
        schema.setdefault(table, []).append(col)
    return schema


@st.cache_data(show_spinner=False)
def _row_counts() -> dict[str, int]:
    con = executor.get_connection()
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for (t,) in tables}


st.title("📊 NL-to-SQL Analytics Agent")
st.caption(
    "Ask a plain-English question about the sales dataset. The agent retrieves relevant "
    "schema context (RAG), asks Claude to write DuckDB SQL, then runs it through an "
    "automated guardrail layer that blocks unsafe/invalid queries before execution."
)

with st.sidebar:
    st.header("Dataset")
    try:
        counts = _row_counts()
        total = sum(counts.values())
        st.metric("Total records", f"{total:,}")
        for t, n in counts.items():
            st.write(f"**{t}**: {n:,} rows")
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not read database at {config.DUCKDB_PATH}: {e}\n\nRun `python data/generate_data.py` first.")

    st.header("Schema")
    try:
        for table, cols in _schema_overview().items():
            with st.expander(table):
                st.code("\n".join(cols), language=None)
    except Exception:
        pass

    st.header("Knowledge base")
    st.write(f"{vectorstore.collection_count()} trained documents (DDL / docs / examples).")

    st.header("Try an example")
    example_qs = [q for q, _ in train_examples.EXAMPLES]
    picked = st.selectbox("Example questions", ["-- choose --"] + example_qs)

question = st.text_input(
    "Ask a question about the data",
    value="" if picked == "-- choose --" else picked,
    placeholder="e.g. What are the top 10 best-selling products by revenue?",
)

col_run, col_train = st.columns([1, 1])
run_clicked = col_run.button("Run", type="primary")

if run_clicked and question.strip():
    with st.spinner("Retrieving context, generating SQL, and validating..."):
        result = executor.ask(question.strip())

    st.subheader("Generated SQL")
    st.code(result.generated_sql or "(no SQL generated)", language="sql")

    if result.warnings:
        for w in result.warnings:
            st.warning(f"⚠️ Anomaly check: {w}")

    if not result.executed:
        st.error("🚫 Query blocked before execution:")
        for reason in result.blocked_reasons:
            st.write(f"- {reason}")
    else:
        st.success(f"✅ Query passed all guardrails and returned {len(result.dataframe):,} row(s).")
        st.dataframe(result.dataframe, use_container_width=True)

        numeric_cols = result.dataframe.select_dtypes("number").columns
        if len(result.dataframe) > 1 and len(numeric_cols) >= 1 and len(result.dataframe.columns) >= 2:
            label_col = result.dataframe.columns[0]
            try:
                st.bar_chart(result.dataframe.set_index(label_col)[numeric_cols])
            except Exception:
                pass

with st.expander("➕ Teach the agent a new question/SQL example"):
    st.caption("Adds a verified (question, SQL) pair to the RAG store so future similar questions retrieve it as context.")
    new_q = st.text_input("Question", key="train_q")
    new_sql = st.text_area("Correct SQL", key="train_sql")
    if st.button("Add to knowledge base"):
        if new_q.strip() and new_sql.strip():
            vectorstore.add_question_sql(new_q.strip(), new_sql.strip())
            st.success("Added. Future similar questions will use this as a reference example.")
        else:
            st.error("Both question and SQL are required.")
