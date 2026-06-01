"""Markdown chunking helpers for knowledge ingest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.documents import Document

# NOTE: ``langchain_text_splitters/__init__.py`` (upstream) eagerly imports
# ``langchain_text_splitters.sentence_transformers`` which pulls in
# ``sentence_transformers`` → torch + transformers + sklearn (~10s cold on
# Windows). This file is loaded transitively by ``services.knowledge.service``
# on every CLI invocation, so we defer the import to actual chunk time.

from hirocli.services.knowledge.constants import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE


def title_from_markdown(text: str, path: Path) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return path.stem


def heading_path_from_metadata(metadata: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for level in range(1, 7):
        value = str(metadata.get(f"Header {level}") or "").strip()
        if value:
            parts.append(f"{'#' * level} {value}")
    return " / ".join(parts) if parts else None


def _heading_path_segments(heading_path: str | None) -> list[str]:
    """Split a stored ``heading_path`` into clean, hash-free heading words.

    ``heading_path`` is stored with markdown markers (``# Doc / ## Section``); the ``#``
    characters are noise for embedding / BM25, so strip them for the embed text.
    """
    if not heading_path:
        return []
    segments = [segment.lstrip("#").strip() for segment in heading_path.split(" / ")]
    return [segment for segment in segments if segment]


def embed_text_for_chunk(title: str | None, chunk: dict[str, str | None]) -> str:
    """Build the text actually fed to the embedders: structural breadcrumb + body.

    The dense and BM25 vectors index this prefixed form so *every* chunk — including
    heading-less continuation/overlap pieces and deep chunks whose body never repeats the
    parent headings — carries its document title and full heading path. The raw
    ``chunk["text"]`` is still what we store in the payload and show to the user / LLM; only
    the embedded representation gains the prefix.
    """
    body = chunk.get("text") or ""
    clean_title = (title or "").strip()
    segments = _heading_path_segments(chunk.get("heading_path"))
    # Lead with the document title, but avoid duplicating an H1 the heading_path already
    # starts with (the title is usually derived from that same H1).
    if clean_title and (not segments or segments[0].casefold() != clean_title.casefold()):
        segments = [clean_title, *segments]
    if not segments:
        return body
    return f"{' / '.join(segments)}\n{body}"


def markdown_chunk_error(path: Path, text: str, *, respect_headings: bool) -> str | None:
    """Return a user-facing ingest error when markdown produces no chunks."""
    if not text.strip():
        return f"No extractable text in markdown file: {path}"
    if respect_headings:
        return (
            f"No text chunks produced from {path}: content is whitespace-only or too short "
            "after heading-aware chunking."
        )
    return (
        f"No text chunks produced from {path}: content is whitespace-only or too short "
        "after chunking."
    )


def chunk_markdown(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    respect_headings: bool = True,
) -> list[dict[str, str | None]]:
    # Deferred import: see module docstring — avoids dragging in torch on every
    # CLI invocation just because something imported the chunker.
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    if respect_headings:
        header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
                ("####", "Header 4"),
                ("#####", "Header 5"),
                ("######", "Header 6"),
            ],
            strip_headers=False,
        )
        docs = header_splitter.split_text(text)
    else:
        docs = [Document(page_content=text, metadata={})] if text.strip() else []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    split_docs = splitter.split_documents(docs)
    chunks: list[dict[str, str | None]] = []
    for doc in split_docs:
        body = doc.page_content.strip()
        if not body:
            continue
        chunks.append({"text": body, "heading_path": heading_path_from_metadata(doc.metadata)})
    return chunks
