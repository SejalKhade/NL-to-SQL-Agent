"""Central configuration, loaded from environment / .env."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

DUCKDB_PATH = os.environ.get("DUCKDB_PATH", os.path.join(BASE_DIR, "data", "analytics.duckdb"))
CHROMA_DIR = os.environ.get("CHROMA_DIR", os.path.join(BASE_DIR, "data", "chroma_store"))

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

MAX_ROWS_RETURNED = int(os.environ.get("MAX_ROWS_RETURNED", "10000"))
RETRIEVAL_K = int(os.environ.get("RETRIEVAL_K", "4"))
