"""Helpers for the knowledge retrieval/answer graph."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from qdrant_client import models as qm


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
