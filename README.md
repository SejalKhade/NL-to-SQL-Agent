# NL-to-SQL Analytics Agent

An AI-powered analytics tool that translates plain-English business questions
into validated DuckDB SQL, so non-technical users can query the data
themselves. Inspired by the RAG-based approach popularized by
[vanna-ai/vanna](https://github.com/vanna-ai/vanna) (train on schema + example
queries, retrieve relevant context, generate SQL), but implemented
independently on **LangChain + Claude**, with an added automated
query-validation ("guardrail") layer that Vanna does not provide out of the box.

## Architecture

```
 NL question
     │
     ▼
┌─────────────────────┐     retrieves top-k        ┌───────────────────────┐
│  RAG retrieval        │◄──────────────────────────┤  Chroma vector store    │
│  (agent/vectorstore)  │    schema DDL / docs /     │  (trained on DDL,       │
│                        │    similar Q→SQL pairs    │   docs, Q→SQL examples) │
└──────────┬───────────┘                            └───────────────────────┘
           │ context
           ▼
┌─────────────────────┐
│  LangChain prompt      │
│  + ChatAnthropic       │   →  raw SQL text
│  (agent/sql_chain)     │
└──────────┬───────────┘
           │ generated SQL
           ▼
┌─────────────────────┐   blocks on: multi-statement, DDL/DML, unknown
│  Guardrail layer       │   tables/columns, failed dry-run (EXPLAIN)
│  (agent/guardrails)    │   flags on: missing LIMIT/WHERE on large tables,
│                        │   joins without ON  →  auto-caps rows, warns
└──────────┬───────────┘
           │ validated SQL (or blocked, with reasons)
           ▼
┌─────────────────────┐
│  DuckDB (read-only)    │   500K+ row order_items fact table
│  (agent/executor)      │   + orders / customers / products
└──────────┬───────────┘
           │ pandas DataFrame
           ▼
     Streamlit UI (app.py) — SQL preview, results table, chart,
     "teach a new example" form
```

## What's real vs. what's aspirational (read this before putting it on a resume)

- **RAG architecture, LangChain, LLM, DuckDB, Streamlit** — all genuinely used, see
  [`agent/vectorstore.py`](agent/vectorstore.py), [`agent/sql_chain.py`](agent/sql_chain.py),
  [`agent/guardrails.py`](agent/guardrails.py), [`app.py`](app.py).
- **"500K+ records"** — true: `order_items` alone is 500K+ rows once you run
  [`data/generate_data.py`](data/generate_data.py) (synthetic but realistic, seeded e-commerce
  dataset — customers/products/orders/order_items — so it's reproducible with no network download).
- **"automated anomaly checks blocking bad queries before execution"** — true: see the
  guardrail tests in [`tests/test_guardrails.py`](tests/test_guardrails.py). It blocks
  non-SELECT statements, stacked statements, unknown tables/columns, and queries that fail a
  DuckDB `EXPLAIN` dry-run; it flags and auto-limits queries with no LIMIT/WHERE on large tables.
- **"reducing analyst intervention to zero"** — this is the one claim the code can't prove.
  Guardrails reduce *bad* queries reaching the database, not the rate at which generated SQL is
  *correct*. Recommend rephrasing to something you can actually measure, e.g. "blocked N% of
  unsafe/invalid generated queries in testing" or "eliminated manual SQL writing for common
  reporting questions" — see the note in the top-level chat where this was flagged.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env          # then edit .env and set ANTHROPIC_API_KEY

python data\generate_data.py            # builds data/analytics.duckdb (~500K+ rows)
python scripts\ingest_training_data.py  # trains the RAG store on schema + examples

streamlit run app.py
```

## Running tests

```bash
pytest tests/ -v
```

The guardrail tests run against an in-memory DuckDB fixture and need no API key.

## Project layout

```
agent/
  config.py         env-driven settings
  vectorstore.py     RAG store: train on DDL / docs / Q→SQL pairs, retrieve by similarity
  sql_chain.py       LangChain prompt + ChatAnthropic → raw SQL
  guardrails.py       validation / anomaly-check layer (blocks unsafe or invalid SQL)
  executor.py         orchestrates generate → validate → execute
  train_examples.py   seed DDL / documentation / example question-SQL pairs
data/
  generate_data.py    builds the synthetic 500K+ row DuckDB dataset
scripts/
  ingest_training_data.py   populates the vector store
tests/
  test_guardrails.py  unit tests for the guardrail layer
app.py                 Streamlit UI
```
