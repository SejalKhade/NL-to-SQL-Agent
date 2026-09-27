# NL-to-SQL Analytics Agent

An AI-powered analytics tool that lets non-technical users query a database in
plain English. Questions are answered by retrieving relevant schema context
(RAG), generating DuckDB SQL with an LLM, running the query through an
automated validation layer that blocks unsafe or invalid SQL before it ever
touches the database, and returning results in an interactive UI.

## Overview

Business users who can't write SQL still need answers from the data —
"what were our top products last quarter?", "which region has the most
cancelled orders?". This project closes that gap: it turns a natural-language
question into a validated, read-only SQL query and executes it directly
against a 750K+ row analytics database, with no analyst in the loop for
routine questions.

## How it works

```
 NL question
     │
     ▼
┌─────────────────────┐     retrieves top-k        ┌───────────────────────┐
│  RAG retrieval         │◄──────────────────────────┤  Chroma vector store     │
│  (agent/vectorstore)   │    schema DDL / docs /     │  (schema DDL, business   │
│                        │    similar Q→SQL pairs     │   docs, Q→SQL examples)  │
└──────────┬───────────┘                            └───────────────────────┘
           │ context
           ▼
┌─────────────────────┐
│  LangChain prompt      │
│  + Claude (Anthropic)  │   →  raw SQL text
│  (agent/sql_chain)     │
└──────────┬───────────┘
           │ generated SQL
           ▼
┌─────────────────────┐   blocks: multi-statement, DDL/DML, unknown
│  Guardrail layer        │   tables/columns, failed dry-run (EXPLAIN)
│  (agent/guardrails)    │   flags: missing LIMIT/WHERE on large tables,
│                        │   joins without ON  →  auto-caps rows, warns
└──────────┬───────────┘
           │ validated SQL (or blocked, with reasons shown to the user)
           ▼
┌─────────────────────┐
│  DuckDB (read-only)     │   500K+ row order_items fact table
│  (agent/executor)      │   + orders / customers / products
└──────────┬───────────┘
           │ pandas DataFrame
           ▼
     Streamlit UI (app.py) — SQL preview, results table, chart,
     "teach a new example" form
```

1. **Retrieve** — the question is embedded and matched against a vector store
   trained on table schemas, business definitions (e.g. "revenue excludes
   cancelled orders"), and past verified question→SQL pairs.
2. **Generate** — the retrieved context is injected into a prompt and sent to
   Claude, which returns a single DuckDB `SELECT` statement.
3. **Validate** — every generated query passes through a guardrail layer
   before execution (see below). Anything that fails is blocked and the
   reason is shown to the user instead of being silently run.
4. **Execute & display** — validated queries run against a read-only DuckDB
   connection; results are shown as a table and chart in Streamlit.

## Guardrail layer (query validation)

Generated SQL is never executed directly. It's parsed and checked before it
touches the database:

- **Blocks outright:** anything that isn't a single read-only `SELECT`
  statement — `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`, multiple stacked
  statements, references to tables or columns that don't exist in the schema,
  and queries that fail a zero-cost DuckDB `EXPLAIN` dry-run (syntax/semantic
  errors caught before real execution).
- **Flags and auto-mitigates:** queries with no `LIMIT`/`WHERE` on a large
  table (a safety cap is injected automatically), and joins without an `ON`
  condition (flagged as a likely cartesian product).

11 unit tests in `tests/test_guardrails.py` cover this layer directly against
an in-memory DuckDB fixture.

## Features

- Plain-English question box with example prompts
- Generated SQL shown before/alongside results, so it's always auditable
- Results table + auto-generated chart
- "Teach the agent" form — add a verified (question, SQL) pair to the
  knowledge base on the fly, so future similar questions retrieve it as a
  reference example
- Sidebar schema browser and live row counts

## Tech stack

Python · LangChain · Anthropic Claude · ChromaDB (vector store) ·
sentence-transformers (local embeddings) · DuckDB · sqlglot (SQL parsing/validation) ·
Streamlit · pandas

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env          # then edit .env and set ANTHROPIC_API_KEY

python data\generate_data.py            # builds data/analytics.duckdb (750K+ rows)
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
  config.py            env-driven settings
  vectorstore.py        RAG store: train on DDL / docs / Q→SQL pairs, retrieve by similarity
  sql_chain.py           LangChain prompt + Claude → raw SQL
  guardrails.py          validation / anomaly-check layer (blocks unsafe or invalid SQL)
  executor.py             orchestrates generate → validate → execute
  train_examples.py       seed DDL / documentation / example question-SQL pairs
data/
  generate_data.py        builds the synthetic 750K+ row DuckDB dataset
scripts/
  ingest_training_data.py     populates the vector store
tests/
  test_guardrails.py      unit tests for the guardrail layer
app.py                     Streamlit UI
```

## Limitations & future work

- **Guardrails check structural safety, not semantic correctness.** They
  guarantee a query is read-only, references real tables/columns, and won't
  scan a huge table unbounded — they don't guarantee the SQL answers the
  question *correctly*. High-stakes numbers should still be spot-checked.
- **Local embeddings trade some retrieval quality for zero extra API cost
  and no external vector-DB dependency** — a hosted embedding model would
  likely improve retrieval on larger, messier schemas.
- **Single-node DuckDB** is built for fast local analytics, not concurrent
  multi-user production load; a production deployment would sit this behind
  a proper OLAP warehouse (e.g. Snowflake, BigQuery) via the same guardrail
  layer.
- **Dataset is synthetic** (generated, not real business data) so the demo
  is self-contained and reproducible without needing external data access.
- **Next steps:** query result caching, per-user row-level access control,
  and a feedback loop where corrected queries are automatically added back
  into the training set.
