"""
RAG store for schema knowledge and example question/SQL pairs.

Mirrors the "training" pattern popularized by vanna-ai/vanna (train on DDL,
free-text documentation, and question->SQL pairs; retrieve the most relevant
of each at query time) but implemented independently on top of LangChain's
Chroma vector store + a local sentence-transformers embedding model, so no
extra API key or network call is needed just to embed text.
"""
from __future__ import annotations

import hashlib
from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from agent import config

_embeddings = None
_store: Chroma | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL)
    return _embeddings


def get_store() -> Chroma:
    global _store
    if _store is None:
        _store = Chroma(
            collection_name="nl_to_sql_knowledge",
            embedding_function=_get_embeddings(),
            persist_directory=config.CHROMA_DIR,
        )
    return _store


def _stable_id(prefix: str, text: str) -> str:
    return f"{prefix}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def add_ddl(ddl: str) -> str:
    """Train on a CREATE TABLE statement / schema definition."""
    doc_id = _stable_id("ddl", ddl)
    get_store().add_documents(
        [Document(page_content=ddl, metadata={"kind": "ddl"})], ids=[doc_id]
    )
    return doc_id


def add_documentation(text: str) -> str:
    """Train on free-text business documentation (glossary, metric defs, etc.)."""
    doc_id = _stable_id("doc", text)
    get_store().add_documents(
        [Document(page_content=text, metadata={"kind": "documentation"})], ids=[doc_id]
    )
    return doc_id


def add_question_sql(question: str, sql: str) -> str:
    """Train on a known-good (question, SQL) example pair."""
    combined = f"Question: {question}\nSQL: {sql}"
    doc_id = _stable_id("qsql", combined)
    get_store().add_documents(
        [Document(page_content=combined, metadata={"kind": "question_sql", "question": question, "sql": sql})],
        ids=[doc_id],
    )
    return doc_id


def _search(query: str, kind: str, k: int) -> List[Document]:
    return get_store().similarity_search(query, k=k, filter={"kind": kind})


def get_related_ddl(question: str, k: int = config.RETRIEVAL_K) -> List[str]:
    return [d.page_content for d in _search(question, "ddl", k)]


def get_related_documentation(question: str, k: int = config.RETRIEVAL_K) -> List[str]:
    return [d.page_content for d in _search(question, "documentation", k)]


def get_similar_question_sql(question: str, k: int = config.RETRIEVAL_K) -> List[Document]:
    return _search(question, "question_sql", k)


def collection_count() -> int:
    try:
        return get_store()._collection.count()  # noqa: SLF001
    except Exception:
        return 0
