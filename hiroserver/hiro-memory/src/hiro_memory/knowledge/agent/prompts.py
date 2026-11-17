"""Pure prompt / fallback helpers for the knowledge answering step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from hiro_memory.knowledge.settings import DEFAULT_KNOWLEDGE_ANSWERING_PROMPT, KnowledgeAnsweringSettings

from .helpers import NormalizedQuery

if TYPE_CHECKING:
    from hiro_memory.knowledge.models import KnowledgeSource


def fallback_answer(
    *,
    answering: KnowledgeAnsweringSettings,
    normalized: NormalizedQuery | None,
    sources: Sequence["KnowledgeSource"],
    query: str,
) -> str:
    text = normalized.text if normalized is not None else query
    lead = f"Found {len(sources)} relevant source(s) for: {text.strip()}"
    lines = [lead]
    for source in sources[:5]:
        snippet = " ".join(source.text.split())
        if len(snippet) > 280:
            snippet = snippet[:277].rstrip() + "..."
        citation = f" [{source.ref}]" if answering.cite_sources else ""
        lines.append(f"- {snippet}{citation}")
    return "\n".join(lines)


def system_prompt(*, answering: KnowledgeAnsweringSettings, normalized: NormalizedQuery) -> str:
    # Base instruction comes from the owner's answering prompt (blank → relaxed default that
    # allows partial answers); the citation + language clauses below are appended at runtime.
    base = (answering.prompt or "").strip() or DEFAULT_KNOWLEDGE_ANSWERING_PROMPT
    parts = [base]
    if answering.cite_sources:
        parts.append("Cite evidence inline with footnote references like [1].")
    else:
        parts.append("Do not include footnote references or inline source markers.")
    policy = answering.language_policy
    if policy == "prefer_english":
        parts.append("Answer in English.")
    elif policy == "prefer_arabic":
        parts.append("Answer in Arabic.")
    elif normalized.language == "ar":
        parts.append("Answer in the same language as the question, Arabic.")
    elif normalized.language and normalized.language != "unknown":
        parts.append(f"Answer in the same language as the question ({normalized.language}).")
    else:
        parts.append("Answer in the same language as the question when it is clear.")
    return " ".join(parts)
