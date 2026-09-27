"""Populates the Chroma vector store with schema DDL, documentation, and
example question/SQL pairs. Run once after generate_data.py, and again any
time train_examples.py changes.

    python scripts/ingest_training_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import train_examples, vectorstore  # noqa: E402


def main() -> None:
    print("[ingest] Adding schema DDL...")
    for ddl in train_examples.DDL_STATEMENTS:
        vectorstore.add_ddl(ddl)

    print("[ingest] Adding documentation...")
    for doc in train_examples.DOCUMENTATION:
        vectorstore.add_documentation(doc)

    print("[ingest] Adding example question/SQL pairs...")
    for question, sql in train_examples.EXAMPLES:
        vectorstore.add_question_sql(question, sql)

    print(f"[ingest] Done. Vector store now has {vectorstore.collection_count()} documents.")


if __name__ == "__main__":
    main()
