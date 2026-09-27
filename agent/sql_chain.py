"""LangChain pipeline that turns a natural-language question into DuckDB SQL,
grounded with context retrieved from the RAG store (schema DDL, business
documentation, and similar past question/SQL examples)."""
from __future__ import annotations

import re

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from agent import config, vectorstore

SYSTEM_PROMPT = """You are a senior data analyst that writes DuckDB SQL.

Rules:
- Output ONLY a single valid DuckDB SELECT statement. No markdown fences, no explanation, no comments.
- Use only the tables and columns shown in the provided schema context — never invent columns or tables.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, or any statement that isn't a read-only SELECT.
- Prefer explicit column names over SELECT *.
- If the question is ambiguous, make the most reasonable analytical assumption and proceed.

Schema context:
{schema_context}

Similar past examples:
{examples_context}
"""

_llm = None


def _get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model=config.CLAUDE_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0,
            max_tokens=1024,
        )
    return _llm


def _build_context(question: str) -> dict:
    ddl = vectorstore.get_related_ddl(question)
    docs = vectorstore.get_related_documentation(question)
    examples = vectorstore.get_similar_question_sql(question)

    schema_context = "\n\n".join(ddl) or "(no schema context found)"
    if docs:
        schema_context += "\n\n" + "\n".join(docs)

    examples_context = "\n\n".join(
        f"Q: {d.metadata.get('question', '')}\nSQL: {d.metadata.get('sql', '')}" for d in examples
    ) or "(no similar examples found)"

    return {"question": question, "schema_context": schema_context, "examples_context": examples_context}


def _strip_sql_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    # If the model chatted before/after the SQL, keep only from SELECT/WITH onward.
    match = re.search(r"(SELECT|WITH)\b", text, flags=re.IGNORECASE)
    if match:
        text = text[match.start():]
    return text.strip().rstrip(";")


_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{question}"),
])


def build_chain():
    return (
        RunnableLambda(_build_context)
        | _prompt
        | _get_llm()
        | StrOutputParser()
        | RunnableLambda(_strip_sql_fences)
    )


def generate_sql(question: str) -> str:
    chain = build_chain()
    return chain.invoke(question)
