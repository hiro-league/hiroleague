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
    KNOWLEDGE_VECTOR_BATCH_SIZE,
)
from hirocli.services.knowledge.converters import document_filter, hit_from_payload
from hirocli.services.knowledge.embedding_backends import EmbeddingBackend
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
        for ord_, (chunk, vector) in enumerate(zip(chunks, vectors), start=1):
            payload = {
                **payload_base,
                "ord": ord_,
                "text": chunk["text"],
                "heading_path": chunk["heading_path"],
            }
            points.append(
                qm.PointStruct(
                    id=str(uuid.uuid5(uuid.UUID(document_id), str(ord_))),
                    vector=vector,
                    payload=payload,
                )
            )
        for batch_start in range(0, len(points), KNOWLEDGE_VECTOR_BATCH_SIZE):
            batch = points[batch_start : batch_start + KNOWLEDGE_VECTOR_BATCH_SIZE]
            with self._write_lock:
                client.upsert(collection_name=self.collection_name, points=batch, wait=True)

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

    def search_by_vector(
        self,
        vector: list[float],
        *,
        top_k: int,
        min_score: float = 0.0,
        qdrant_filter: qm.Filter | None = None,
    ) -> list[KnowledgeSearchHit]:
        """Run a similarity query directly via the qdrant client.

        Replaces the previous ``langchain-qdrant`` wrapper path: that wrapper
        required mirroring every flat payload field under a nested ``metadata``
        key (its ``metadata_payload_key``) which doubled per-point storage.
        Querying directly lets the payload stay flat.
        """
        response = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=list(vector),
            limit=max(1, min(int(top_k), 100)),
            query_filter=qdrant_filter,
            score_threshold=min_score if min_score > 0 else None,
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
            if current_size is not None and current_size != self.embedder.dimension:
                point_count = client.count(self.collection_name, exact=True).count
                if point_count:
                    raise RuntimeError(
                        f"Knowledge collection vector size is {current_size}, "
                        f"but embedder {getattr(self.embedder, 'model_name', DEFAULT_EMBEDDING_MODEL)} "
                        f"uses {self.embedder.dimension}. "
                        "Delete existing knowledge documents before changing embedding models."
                    )
                client.delete_collection(self.collection_name)
            else:
                return
        if not client.collection_exists(self.collection_name):
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config=qm.VectorParams(size=self.embedder.dimension, distance=qm.Distance.COSINE),
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
        if hasattr(vectors, "size"):
            return int(vectors.size)
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            if hasattr(first, "size"):
                return int(first.size)
        return None
