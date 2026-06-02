"""Qdrant vector store wrapper for knowledge chunk vectors."""

from __future__ import annotations

import threading
import uuid
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from hirocli.services.knowledge.constants import (
    COLLECTION_NAME,
    DEFAULT_EMBEDDING_MODEL,
    DENSE_VECTOR_NAME,
    KNOWLEDGE_VECTOR_BATCH_SIZE,
    SPARSE_VECTOR_NAME,
)
from hirocli.services.knowledge.converters import document_filter, hit_from_payload
from hirocli.services.knowledge.embedding_backends import EmbeddingBackend, SparseVectorData
from hirocli.services.knowledge.models import KnowledgeSearchHit


class KnowledgeVectorStore:
    """Direct qdrant-client wrapper over the workspace knowledge collection.

    Payload is flat: every retrieval/filter field lives at the top level
    (``document_id``, ``owner_kind``, ``tags``, ``text``, ``ord``, …). We
    intentionally do **not** mirror those fields under a nested ``metadata``
    key — it doubled storage and forced ``sync_payload_metadata`` to maintain
    two copies in lock-step.
    """

    def __init__(
        self,
        qdrant_path: Path,
        embedder: EmbeddingBackend,
        *,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self.qdrant_path = Path(qdrant_path)
        self.collection_name = collection_name
        self.embedder = embedder
        self._qdrant: QdrantClient | None = None
        self._qdrant_lock = threading.Lock()
        self._write_lock = threading.Lock()

    def reload_embedder(self, embedder: EmbeddingBackend) -> None:
        """Swap the active embedder and re-validate the existing collection.

        ``_ensure_collection`` previously only ran while the Qdrant client was
        being lazily created, so a swap could land against a collection whose
        vector size no longer matched the new embedder dimension. Re-running
        the check here surfaces the mismatch immediately instead of letting
        the next read silently use the stale shape.
        """
        with self._qdrant_lock:
            self.embedder = embedder
            if self._qdrant is not None:
                self._ensure_collection()

    @property
    def qdrant(self) -> QdrantClient:
        with self._qdrant_lock:
            if self._qdrant is None:
                self._qdrant = QdrantClient(
                    path=str(self.qdrant_path),
                    force_disable_check_same_thread=True,
                )
                self._ensure_collection()
        return self._qdrant

    def close(self) -> None:
        if self._qdrant is not None:
            self._qdrant.close()
            self._qdrant = None

    def upsert_document_vectors(
        self,
        document_id: str,
        path: Path,
        title: str,
        mime: str,
        chunks: list[dict[str, str | None]],
        vectors: list[list[float]],
        sparse_vectors: list[SparseVectorData],
        params: dict[str, Any],
        tags: Sequence[str],
        now: str,
    ) -> None:
        client = self.qdrant
        with self._write_lock:
            client.delete(
                collection_name=self.collection_name,
                points_selector=qm.FilterSelector(filter=document_filter(document_id)),
                wait=True,
            )
        payload_base = {
            "document_id": document_id,
            "owner_kind": params.get("owner_kind") or "system",
            "owner_id": params.get("owner_id") or "0",
            "category_id": params.get("category_id"),
            "subcategory_id": params.get("subcategory_id"),
            "tags": list(tags),
            "source_type": "file",
            "mime": mime,
            "title": title,
            "source_uri": str(path),
            "ingested_at": now,
        }
        points = []
        # Each point carries both named vectors so hybrid is a query-time toggle (no re-ingest).
        for ord_, (chunk, vector, sparse) in enumerate(
            zip(chunks, vectors, sparse_vectors), start=1
        ):
            indices, values = sparse
            payload = {
                **payload_base,
                "ord": ord_,
                "text": chunk["text"],
                "heading_path": chunk["heading_path"],
            }
            points.append(
                qm.PointStruct(
                    id=str(uuid.uuid5(uuid.UUID(document_id), str(ord_))),
                    vector={
                        DENSE_VECTOR_NAME: vector,
                        SPARSE_VECTOR_NAME: qm.SparseVector(indices=indices, values=values),
                    },
                    payload=payload,
                )
            )
        for batch_start in range(0, len(points), KNOWLEDGE_VECTOR_BATCH_SIZE):
            batch = points[batch_start : batch_start + KNOWLEDGE_VECTOR_BATCH_SIZE]
            with self._write_lock:
                client.upsert(collection_name=self.collection_name, points=batch, wait=True)

    def upsert_point(
        self,
        *,
        point_id: str,
        text: str,
        dense_vector: list[float],
        sparse_vector: SparseVectorData,
        document_id: str,
        title: str,
        tags: Sequence[str],
        now: str,
        ord: int = 1,
        source_uri: str = "",
    ) -> None:
        """Upsert ONE chunk with a caller-chosen ``point_id`` (no delete-by-document).

        Used by the episode-corpus double-write (one episode = one point, where
        ``point_id`` is the shared uuid that also keys the Graphiti episode — so a
        graph fact's ``episodes`` join straight back to this Qdrant point). Unlike
        :meth:`upsert_document_vectors` this does **not** clear the document first, so
        many episodes can share a ``document_id`` without erasing each other."""
        indices, values = sparse_vector
        payload = {
            "document_id": document_id,
            "owner_kind": "system",
            "owner_id": "0",
            "category_id": None,
            "subcategory_id": None,
            "tags": list(tags),
            "source_type": "episode",
            "mime": "text/plain",
            "title": title,
            "source_uri": source_uri,
            "ingested_at": now,
            "ord": ord,
            "text": text,
            "heading_path": None,
        }
        point = qm.PointStruct(
            id=point_id,
            vector={
                DENSE_VECTOR_NAME: dense_vector,
                SPARSE_VECTOR_NAME: qm.SparseVector(indices=list(indices), values=list(values)),
            },
            payload=payload,
        )
        with self._write_lock:
            self.qdrant.upsert(collection_name=self.collection_name, points=[point], wait=True)

    def delete_document(self, document_id: str) -> None:
        with self._write_lock:
            self.qdrant.delete(
                collection_name=self.collection_name,
                points_selector=qm.FilterSelector(filter=document_filter(document_id)),
                wait=True,
            )

    def scroll_document_chunks(
        self,
        document_id: str,
        limit: int,
        offset: Any = None,
    ) -> tuple[list[dict[str, Any]], Any]:
        records, next_offset = self.qdrant.scroll(
            collection_name=self.collection_name,
            scroll_filter=document_filter(document_id),
            limit=max(1, min(int(limit), 500)),
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        chunks: list[dict[str, Any]] = []
        for record in records:
            payload = dict(record.payload or {})
            payload["point_id"] = str(record.id)
            chunks.append(payload)
        chunks.sort(key=lambda item: int(item.get("ord") or 0))
        return chunks, next_offset

    def hit_from_point_id(self, point_id: str, score: float) -> KnowledgeSearchHit:
        records = self.qdrant.retrieve(
            collection_name=self.collection_name,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            return KnowledgeSearchHit(
                document_id="",
                point_id=point_id,
                score=score,
                ord=0,
                text="",
                heading_path=None,
                title="",
                source_uri="",
                owner_kind="",
                owner_id="",
                category_id=None,
                subcategory_id=None,
                tags=[],
            )
        return hit_from_payload(records[0].payload or {}, point_id=point_id, score=score)

    def search_hybrid(
        self,
        dense_vector: list[float],
        sparse_vector: SparseVectorData | None,
        *,
        top_k: int,
        min_score: float = 0.0,
        prefetch_limit: int = 40,
        hybrid: bool = True,
        explain: bool = False,
        qdrant_filter: qm.Filter | None = None,
    ) -> list[KnowledgeSearchHit]:
        """Dense or hybrid (dense + BM25 sparse, RRF-fused) similarity query.

        Default (``explain=False``): a single server-side ``FusionQuery`` — one round-trip,
        returning only the fused RRF score. ``min_score`` is a cosine threshold applied to the
        **dense** branch only (BM25 scores are not 0-1); the RRF output is not thresholded.

        Opt-in (``explain=True``): runs the dense and sparse branches as two separate queries and
        fuses them in-process, so each hit carries its per-branch ``dense_score`` (cosine) and
        ``sparse_score`` (BM25). Strictly opt-in — the default path stays a single query.
        """
        limit = max(1, min(int(top_k), 100))
        dense_threshold = min_score if min_score > 0 else None
        branch_limit = max(int(prefetch_limit), limit)
        use_hybrid = bool(hybrid and sparse_vector is not None and sparse_vector[0])

        if use_hybrid and explain:
            return self._search_hybrid_explained(
                dense_vector,
                sparse_vector,  # type: ignore[arg-type]
                limit=limit,
                branch_limit=branch_limit,
                dense_threshold=dense_threshold,
                qdrant_filter=qdrant_filter,
            )

        if use_hybrid:
            indices, values = sparse_vector  # type: ignore[misc]
            response = self.qdrant.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    qm.Prefetch(
                        query=list(dense_vector),
                        using=DENSE_VECTOR_NAME,
                        limit=branch_limit,
                        score_threshold=dense_threshold,
                        filter=qdrant_filter,
                    ),
                    qm.Prefetch(
                        query=qm.SparseVector(indices=list(indices), values=list(values)),
                        using=SPARSE_VECTOR_NAME,
                        limit=branch_limit,
                        filter=qdrant_filter,
                    ),
                ],
                query=qm.FusionQuery(fusion=qm.Fusion.RRF),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        else:
            response = self.qdrant.query_points(
                collection_name=self.collection_name,
                query=list(dense_vector),
                using=DENSE_VECTOR_NAME,
                limit=limit,
                query_filter=qdrant_filter,
                score_threshold=dense_threshold,
                with_payload=True,
                with_vectors=False,
            )

        hits: list[KnowledgeSearchHit] = []
        for point in response.points:
            hits.append(
                hit_from_payload(
                    dict(point.payload or {}),
                    point_id=str(point.id),
                    score=float(point.score or 0.0),
                )
            )
        return hits

    # RRF ranking constant — kept equal to Qdrant's server-side default so the explain path's
    # ordering matches the default fused query.
    _RRF_K = 2

    def _search_hybrid_explained(
        self,
        dense_vector: list[float],
        sparse_vector: SparseVectorData,
        *,
        limit: int,
        branch_limit: int,
        dense_threshold: float | None,
        qdrant_filter: qm.Filter | None,
    ) -> list[KnowledgeSearchHit]:
        """Two branch queries + in-process RRF, exposing per-branch cosine/BM25 scores.

        Only used in explain mode; the default search path remains a single fused query.
        """
        indices, values = sparse_vector
        dense_resp = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=list(dense_vector),
            using=DENSE_VECTOR_NAME,
            limit=branch_limit,
            query_filter=qdrant_filter,
            score_threshold=dense_threshold,
            with_payload=True,
            with_vectors=False,
        )
        sparse_resp = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=qm.SparseVector(indices=list(indices), values=list(values)),
            using=SPARSE_VECTOR_NAME,
            limit=branch_limit,
            query_filter=qdrant_filter,
            with_payload=True,
            with_vectors=False,
        )

        agg: dict[str, dict[str, Any]] = {}

        def _accumulate(points: list[Any], score_key: str) -> None:
            for rank, point in enumerate(points):
                pid = str(point.id)
                entry = agg.setdefault(
                    pid,
                    {"rrf": 0.0, "dense_score": None, "sparse_score": None, "payload": None},
                )
                entry["rrf"] += 1.0 / (self._RRF_K + rank)
                entry[score_key] = float(point.score or 0.0)
                if entry["payload"] is None:
                    entry["payload"] = point.payload

        _accumulate(dense_resp.points, "dense_score")
        _accumulate(sparse_resp.points, "sparse_score")

        ranked = sorted(agg.items(), key=lambda item: item[1]["rrf"], reverse=True)[:limit]
        return [
            hit_from_payload(
                dict(entry["payload"] or {}),
                point_id=pid,
                score=float(entry["rrf"]),
                dense_score=entry["dense_score"],
                sparse_score=entry["sparse_score"],
            )
            for pid, entry in ranked
        ]

    def sync_payload_metadata(
        self,
        document_id: str,
        *,
        owner_kind: str,
        owner_id: str,
        category_id: int | None,
        subcategory_id: int | None,
        tags: Sequence[str],
    ) -> None:
        records, _ = self.qdrant.scroll(
            collection_name=self.collection_name,
            scroll_filter=document_filter(document_id),
            limit=500,
            with_payload=True,
            with_vectors=False,
        )
        new_fields = {
            "owner_kind": owner_kind or "system",
            "owner_id": owner_id or "0",
            "category_id": category_id,
            "subcategory_id": subcategory_id,
            "tags": list(tags),
        }
        for record in records:
            with self._write_lock:
                # Drop legacy nested ``metadata`` snapshot from older writes;
                # set_payload otherwise merges and would leave stale copies.
                if isinstance(record.payload, dict) and "metadata" in record.payload:
                    self.qdrant.delete_payload(
                        collection_name=self.collection_name,
                        keys=["metadata"],
                        points=[record.id],
                        wait=True,
                    )
                self.qdrant.set_payload(
                    collection_name=self.collection_name,
                    payload=new_fields,
                    points=[record.id],
                    wait=True,
                )

    def touch_document_ingested_at(self, document_id: str, now: str) -> None:
        records, _ = self.qdrant.scroll(
            collection_name=self.collection_name,
            scroll_filter=document_filter(document_id),
            limit=500,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            with self._write_lock:
                self.qdrant.set_payload(
                    collection_name=self.collection_name,
                    payload={"ingested_at": now},
                    points=[record.id],
                    wait=True,
                )

    def _ensure_collection(self) -> None:
        client = self._qdrant
        if client is None:
            raise RuntimeError("Qdrant client is not initialized.")
        if client.collection_exists(self.collection_name):
            current_size = self._collection_vector_size(client, self.collection_name)
            dimension_ok = current_size is None or current_size == self.embedder.dimension
            schema_ok = self._collection_has_named_schema(client, self.collection_name)
            if dimension_ok and schema_ok:
                return
            # The dense dimension changed, or the collection predates hybrid (single unnamed
            # vector / no sparse config). No migration (no-backward-compatibility): recreate
            # when empty, otherwise require an explicit clear + re-ingest.
            point_count = client.count(self.collection_name, exact=True).count
            if point_count:
                reason = (
                    f"vector size {current_size} != embedder "
                    f"{getattr(self.embedder, 'model_name', DEFAULT_EMBEDDING_MODEL)} "
                    f"({self.embedder.dimension})"
                    if not dimension_ok
                    else "collection predates hybrid retrieval (missing named dense/sparse vectors)"
                )
                raise RuntimeError(
                    f"Knowledge collection must be rebuilt: {reason}. "
                    "Delete existing knowledge documents before changing retrieval settings."
                )
            client.delete_collection(self.collection_name)
        if not client.collection_exists(self.collection_name):
            # Named dense + BM25 sparse vectors in one collection. BM25 needs the IDF modifier
            # because FastEmbed emits raw term weights and Qdrant applies inverse doc frequency.
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    DENSE_VECTOR_NAME: qm.VectorParams(
                        size=self.embedder.dimension, distance=qm.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: qm.SparseVectorParams(modifier=qm.Modifier.IDF)
                },
            )
        for field_name, schema in {
            "owner_kind": qm.PayloadSchemaType.KEYWORD,
            "owner_id": qm.PayloadSchemaType.KEYWORD,
            "category_id": qm.PayloadSchemaType.INTEGER,
            "subcategory_id": qm.PayloadSchemaType.INTEGER,
            "tags": qm.PayloadSchemaType.KEYWORD,
            "document_id": qm.PayloadSchemaType.KEYWORD,
        }.items():
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="Payload indexes have no effect in the local Qdrant.*",
                    )
                    client.create_payload_index(self.collection_name, field_name, field_schema=schema)
            except Exception:
                pass

    @staticmethod
    def _collection_vector_size(client: QdrantClient, collection_name: str) -> int | None:
        info = client.get_collection(collection_name)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict) and vectors:
            params = vectors.get(DENSE_VECTOR_NAME) or next(iter(vectors.values()))
            return int(params.size) if hasattr(params, "size") else None
        if hasattr(vectors, "size"):  # legacy single unnamed vector
            return int(vectors.size)
        return None

    @staticmethod
    def _collection_has_named_schema(client: QdrantClient, collection_name: str) -> bool:
        """True only for the hybrid schema: named ``dense`` vector + ``bm25`` sparse vector."""
        info = client.get_collection(collection_name)
        vectors = info.config.params.vectors
        has_dense = isinstance(vectors, dict) and DENSE_VECTOR_NAME in vectors
        sparse = getattr(info.config.params, "sparse_vectors", None)
        has_sparse = isinstance(sparse, dict) and SPARSE_VECTOR_NAME in sparse
        return bool(has_dense and has_sparse)
