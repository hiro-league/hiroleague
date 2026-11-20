"""A knowledge collection on disk with its embedders: ingest a file into it, remove a document, read one back, and the
retrieval the answer graph drives (``agent.config.KnowledgeRetriever``).

The core's ``KnowledgeService`` is one (the family's knowledge base, with its jobs, events and preferences on top);
EvalHiro's knowledge eval holds one per corpus. The owner builds the parts (where the catalog and the Qdrant folder
are, which embedders) and hands them in; ``KnowledgeIndex`` never reads preferences and publishes nothing: a file it
ingests is reported through ``on_ingested``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qdrant_client import models as qm

from hiro_memory.knowledge.catalog_store import CatalogStore
from hiro_memory.knowledge.chunker import embed_text_for_chunk
from hiro_memory.knowledge.converters import document_from_row, utc_now_iso
from hiro_memory.knowledge.embedding_backends import EmbeddingBackend, SparseEmbeddingBackend, SparseVectorData
from hiro_memory.knowledge.loaders import DEFAULT_LOADER_REGISTRY, LoaderRegistry
from hiro_memory.knowledge.models import KnowledgeDocumentDetailResult, KnowledgeSearchHit
from hiro_memory.knowledge.settings import KnowledgeChunkingSettings
from hiro_memory.knowledge.vector_store import KnowledgeVectorStore

# Called after a file is (re)ingested: (document_id, source_uri).
OnIngested = Callable[[str, str], None]


class KnowledgeIndex:
    """The catalog (SQLite), the Qdrant collection, the dense and BM25 embedders, and the loaders, as one."""

    def __init__(
        self,
        *,
        catalog: CatalogStore,
        vector_store: KnowledgeVectorStore,
        embedder: EmbeddingBackend,
        sparse_embedder: SparseEmbeddingBackend,
        loader_registry: LoaderRegistry | None = None,
    ) -> None:
        self.catalog = catalog
        self.vector_store = vector_store
        self.embedder = embedder
        self.sparse_embedder = sparse_embedder
        self.loader_registry = loader_registry or DEFAULT_LOADER_REGISTRY
        # One ingest at a time per source file (a file asked twice in one job, or by two jobs).
        self._uri_locks: dict[str, asyncio.Lock] = {}

    # --- retrieval (KnowledgeRetriever) ---

    async def embed_query(self, query: str) -> list[float]:
        vectors = await asyncio.to_thread(self.embedder.embed_texts, [query])
        return list(vectors[0]) if vectors else []

    async def embed_query_sparse(self, query: str) -> SparseVectorData:
        """BM25 sparse vector for the query (query-side weighting differs from documents)."""
        return await asyncio.to_thread(self.sparse_embedder.embed_query, query)

    async def vector_search_by_vector(
        self,
        vector: list[float],
        sparse_vector: SparseVectorData | None = None,
        *,
        top_k: int,
        min_score: float,
        prefetch_limit: int = 40,
        hybrid: bool = True,
        explain: bool = False,
        qdrant_filter: qm.Filter | None = None,
    ) -> list[KnowledgeSearchHit]:
        return await asyncio.to_thread(
            self.vector_store.search_hybrid,
            vector,
            sparse_vector,
            top_k=top_k,
            min_score=min_score,
            prefetch_limit=prefetch_limit,
            hybrid=hybrid,
            explain=explain,
            qdrant_filter=qdrant_filter,
        )

    async def fetch_hits_by_point_ids(self, point_ids: list[str]) -> list[KnowledgeSearchHit]:
        """Fetch chunk hits for explicit Qdrant point_ids, in caller order.

        Used by the graph retrieval leg: the graph picks the fact-supporting
        chunk_ids and we retrieve those verbatim passages by id (no query hybrid /
        no min_score drop). Points with empty text (a chunk_id not in Qdrant) are
        skipped. Scores descend with rank so build_context's ordinal normalization
        preserves the graph's ranking."""
        if not point_ids:
            return []

        def _fetch() -> list[KnowledgeSearchHit]:
            out: list[KnowledgeSearchHit] = []
            count = len(point_ids)
            for rank, pid in enumerate(point_ids):
                hit = self.vector_store.hit_from_point_id(pid, score=float(count - rank))
                if (hit.text or "").strip():
                    out.append(hit)
            return out

        return await asyncio.to_thread(_fetch)

    # --- documents ---

    async def get_document(
        self,
        document_id: str,
        *,
        chunk_limit: int = 100,
        chunk_offset: str | None = None,
    ) -> KnowledgeDocumentDetailResult:
        row = await asyncio.to_thread(self.catalog.document_row_by_id, document_id)
        if row is None:
            return KnowledgeDocumentDetailResult(document=None, chunks=[])
        tags = await asyncio.to_thread(self.catalog.tags_for_document, document_id)
        document = document_from_row(row, tags=tags)
        offset = json.loads(chunk_offset) if chunk_offset else None
        chunks, next_offset = await asyncio.to_thread(
            self.vector_store.scroll_document_chunks,
            document_id,
            chunk_limit,
            offset,
        )
        return KnowledgeDocumentDetailResult(
            document=document,
            chunks=chunks,
            chunk_next_offset=json.dumps(next_offset) if next_offset is not None else None,
        )

    def remove_document(self, document_id: str) -> bool:
        """Remove a document's catalog row and its chunks (blocking). False when the catalog has no such document."""
        if not self.catalog.delete_document_row(document_id):
            return False
        self.vector_store.delete_document(document_id)
        return True

    # --- ingest ---

    async def ingest_file(
        self,
        raw_path: str,
        params: dict[str, Any],
        *,
        chunking: KnowledgeChunkingSettings,
        max_file_size_bytes: int,
        on_ingested: OnIngested | None = None,
    ) -> int | None:
        """Load, chunk, embed (dense and BM25) and upsert one file; its catalog row follows each step.

        Returns the chunk count; None when the file is unchanged since its last ingest (same content hash, ready);
        0 when ``params["force_reingest"]`` re-stamps an unchanged file. Raises on an unsupported extension, a file
        over ``max_file_size_bytes``, or a failed load or embed (the catalog row is marked failed first).
        ``params`` carries the document's metadata (owner_kind, owner_id, category_id, subcategory_id, tags)."""
        path = await asyncio.to_thread(lambda: Path(raw_path).expanduser().resolve())
        loader = self.loader_registry.resolve(path.suffix.lower())
        if loader is None:
            raise ValueError(f"Unsupported file extension: {path.suffix}")
        lock = self._uri_locks.setdefault(str(path), asyncio.Lock())
        async with lock:
            size_bytes = await asyncio.to_thread(lambda: path.stat().st_size)
            if size_bytes > max_file_size_bytes:
                raise ValueError(
                    f"File exceeds maximum knowledge ingest size "
                    f"({size_bytes} bytes > {max_file_size_bytes} bytes): {path}"
                )
            data = await asyncio.to_thread(path.read_bytes)
            content_hash = hashlib.sha256(data).hexdigest()
            existing = await asyncio.to_thread(self.catalog.document_row_by_source, str(path))
            if existing and existing["content_hash"] == content_hash and existing["status"] == "ready":
                if params.get("force_reingest"):
                    document_id = str(existing["id"])
                    now = utc_now_iso()
                    await asyncio.to_thread(self.catalog.touch_document_ingested, document_id, now)
                    await asyncio.to_thread(
                        self.vector_store.touch_document_ingested_at,
                        document_id,
                        now,
                    )
                    if on_ingested is not None:
                        on_ingested(document_id, str(path))
                    return 0
                return None
            document_id = existing["id"] if existing else str(uuid.uuid4())
            await asyncio.to_thread(
                self.catalog.mark_document_progress, document_id, path, "parsing", size_bytes, params
            )
            try:
                loaded = loader.load(
                    path,
                    data,
                    chunk_size=chunking.chunk_size,
                    chunk_overlap=chunking.chunk_overlap,
                    respect_headings=chunking.markdown.respect_headings,
                )
                chunks = loaded.chunks
                if not chunks:
                    raise ValueError(f"No text chunks produced from {path}.")
                await asyncio.to_thread(self.catalog.update_document_status, document_id, "embedding", None)
                # Embed the structural breadcrumb (title / heading path) + body when enabled, so
                # every chunk — including heading-less continuation pieces — carries its document
                # and section context in what actually gets indexed. The stored payload text stays
                # the raw chunk body (the UI and LLM context add title/heading separately).
                if chunking.embed_structural_context:
                    embed_texts = [embed_text_for_chunk(loaded.title, chunk) for chunk in chunks]
                else:
                    embed_texts = [chunk["text"] for chunk in chunks]
                vectors = await asyncio.to_thread(self.embedder.embed_texts, embed_texts)
                if len(vectors) != len(chunks):
                    raise RuntimeError("Embedding backend returned the wrong number of vectors.")
                # Always store BM25 sparse alongside dense so hybrid is a query-time toggle.
                sparse_vectors = await asyncio.to_thread(
                    self.sparse_embedder.embed_documents, embed_texts
                )
                if len(sparse_vectors) != len(chunks):
                    raise RuntimeError("Sparse embedding backend returned the wrong number of vectors.")
                now = utc_now_iso()
                await asyncio.to_thread(
                    self.upsert_document_and_vectors,
                    document_id,
                    path,
                    loaded.title,
                    loaded.mime,
                    content_hash,
                    size_bytes,
                    chunks,
                    vectors,
                    sparse_vectors,
                    params,
                    now,
                )
            except Exception as exc:
                await asyncio.to_thread(self.catalog.update_document_status, document_id, "failed", str(exc))
                raise
            if on_ingested is not None:
                on_ingested(document_id, str(path))
            return len(chunks)

    def upsert_document_and_vectors(
        self,
        document_id: str,
        path: Path,
        title: str,
        mime: str,
        content_hash: str,
        size_bytes: int,
        chunks: list[dict[str, str | None]],
        vectors: list[list[float]],
        sparse_vectors: list[SparseVectorData],
        params: dict[str, Any],
        now: str,
    ) -> None:
        """Write a document's chunks (both vectors) and its catalog row (blocking)."""
        self.catalog.validate_category_assignment(params.get("category_id"), params.get("subcategory_id"))
        tags = self.catalog.ensure_tags(params.get("tags") or [])
        self.vector_store.upsert_document_vectors(
            document_id,
            path,
            title,
            mime,
            chunks,
            vectors,
            sparse_vectors,
            params,
            tags,
            now,
        )
        self.catalog.upsert_document_row(
            document_id,
            path,
            title,
            mime,
            content_hash,
            size_bytes,
            len(chunks),
            params,
            now,
            tags,
        )


__all__ = ["KnowledgeIndex", "OnIngested"]
