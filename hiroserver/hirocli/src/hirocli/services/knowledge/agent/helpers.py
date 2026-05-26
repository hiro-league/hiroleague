"""Helpers for the knowledge retrieval/answer graph."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from qdrant_client import models as qm

_WORD_RE = re.compile(r"\w+", re.UNICODE)
# Tiny English + Arabic stoplist so matched-term chips show content words, not glue words.
_MATCH_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
        "was", "were", "what", "which", "who", "how", "why", "when", "where", "do",
        "does", "did", "with", "that", "this", "it", "as", "by", "at", "be",
        "من", "في", "على", "عن", "الى", "ما", "ماذا", "هل", "كيف", "لماذا", "متى",
        "اين", "و", "او", "هذا", "هذه", "ذلك", "التي", "الذي",
    }
)


class ContextSource(Protocol):
    ref: int
    title: str
    heading_path: str | None
    text: str


@dataclass(frozen=True)
class NormalizedQuery:
    raw: str
    text: str
    language: str


_ARABIC_ALEF_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
    }
)


def normalize_query(text: str) -> NormalizedQuery:
    raw = str(text or "")
    normalized = unicodedata.normalize("NFC", raw).strip()
    normalized = normalized.translate(_ARABIC_ALEF_MAP)
    return NormalizedQuery(raw=raw, text=normalized, language=_detect_language(normalized))


def _detect_language(text: str) -> str:
    if not text:
        return "unknown"
    try:
        from langdetect import LangDetectException, detect

        try:
            return detect(text)
        except LangDetectException:
            return "unknown"
    except Exception:
        if any("\u0600" <= ch <= "\u06ff" for ch in text):
            return "ar"
        return "unknown"


def _match_tokens(text: str) -> list[str]:
    """Normalized word tokens (NFC + Arabic alef fold + lowercase) for overlap matching."""
    normalized = unicodedata.normalize("NFC", str(text or "")).translate(_ARABIC_ALEF_MAP).lower()
    return _WORD_RE.findall(normalized)


def matched_query_terms(query: str, text: str, *, limit: int = 12) -> list[str]:
    """Query words that also appear in the chunk text (normalized, Arabic-aware).

    A lightweight keyword-overlap hint for human evaluation in explain mode — deliberately
    *not* BM25's stemmed match (no stemming), so it shows the literal shared words. Returns
    query terms in query order, deduped, content words only.
    """
    chunk_tokens = set(_match_tokens(text))
    if not chunk_tokens:
        return []
    matched: list[str] = []
    seen: set[str] = set()
    for token in _match_tokens(query):
        if len(token) < 2 or token in _MATCH_STOPWORDS or token in seen:
            continue
        seen.add(token)
        if token in chunk_tokens:
            matched.append(token)
        if len(matched) >= limit:
            break
    return matched


def build_qdrant_filter(filters: dict[str, Any]) -> qm.Filter | None:
    must: list[Any] = []
    for key in ("owner_kind", "owner_id", "document_id"):
        value = filters.get(key)
        if value not in (None, ""):
            must.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=str(value))))
    for key in ("category_id", "subcategory_id"):
        value = filters.get(key)
        if value not in (None, ""):
            must.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=int(value))))
    # Tags use OR semantics: a chunk matches if it carries ANY of the selected tags.
    # Wrapping the should-clause in a nested Filter inside must makes the OR
    # mandatory (without it, should alone wouldn't be required to match).
    tag_should = [
        qm.FieldCondition(key="tags", match=qm.MatchValue(value=str(tag).strip()))
        for tag in (filters.get("tags") or [])
        if str(tag).strip()
    ]
    if tag_should:
        must.append(qm.Filter(should=tag_should))
    return qm.Filter(must=must) if must else None


def build_context(sources: Sequence[ContextSource]) -> str:
    blocks: list[str] = []
    for source in sources:
        heading = f" §{source.heading_path}" if source.heading_path else ""
        blocks.append(f"[{source.ref}] {source.title}{heading}\n{source.text}")
    return "\n\n".join(blocks)
