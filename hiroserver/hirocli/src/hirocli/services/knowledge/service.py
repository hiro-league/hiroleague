"""Workspace-local knowledge service for markdown ingest and vector search."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import threading
import uuid
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from hiro_commons.log import Logger
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from hirocli.domain.events import DomainEvent, get_domain_event_bus

log = Logger.get("SVC.KNOWLEDGE")

KNOWLEDGE_DIR = "knowledge"
DB_FILENAME = "knowledge.db"
QDRANT_DIR = "qdrant"
COLLECTION_NAME = "hiro_knowledge"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_VECTOR_SIZE = 384
SUPPORTED_EXTENSIONS = {".md"}
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150

KNOWLEDGE_JOB_PROGRESS = "knowledge.job.progress"
KNOWLEDGE_JOB_COMPLETED = "knowledge.job.completed"
KNOWLEDGE_JOB_FAILED = "knowledge.job.failed"
KNOWLEDGE_INGESTED = "knowledge.ingested"


class EmbeddingBackend(Protocol):
    dimension: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one dense vector per text."""


class FastEmbedBackend:
    """Lazy FastEmbed wrapper so model weights download only on first real use."""

    dimension = DEFAULT_VECTOR_SIZE

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="The model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 now uses mean pooling.*",
                )
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir) if self.cache_dir is not None else None,
                    threads=min(os.cpu_count() or 1, 4),
                    lazy_load=True,
                )
        return self._model

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._ensure_model().embed(list(texts), batch_size=32)
        return [vector.astype(float).tolist() for vector in vectors]


@dataclass(frozen=True)
class KnowledgeDocumentRow:
    id: str
    source_uri: str
    source_type: str
    mime: str
    ext: str
    owner_kind: str
    owner_id: str
    category_id: int | None
    subcategory_id: int | None
    title: str
    content_hash: str
    size_bytes: int
    chunk_count: int
    status: str
    error: str | None
    ingested_at: str | None
    updated_at: str


@dataclass(frozen=True)
class ScannedFile:
    path: str
    relative_path: str
    ext: str
    size_bytes: int
    supported: bool
    already_ingested: bool
    disabled_reason: str | None = None


@dataclass(frozen=True)
class ScanFolderResult:
    root: str
    files: list[ScannedFile]


@dataclass(frozen=True)
class KnowledgeJobResult:
    job_id: str
    status: str
    totals: dict[str, int]
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeSearchHit:
    document_id: str
    point_id: str
    score: float
    ord: int
    text: str
    heading_path: str | None
    title: str
    source_uri: str
    owner_kind: str
    owner_id: str
    tags: list[str]


@dataclass(frozen=True)
class KnowledgeSearchResult:
    query: str
    hits: list[KnowledgeSearchHit]


@dataclass(frozen=True)
class KnowledgeListDocumentsResult:
    documents: list[KnowledgeDocumentRow]
    total: int


@dataclass(frozen=True)
class KnowledgeDocumentDetailResult:
    document: KnowledgeDocumentRow | None
    chunks: list[dict[str, Any]]


class KnowledgeService:
    """Phase 1 knowledge service: scan, ingest markdown, search, browse chunks."""

    def __init__(
        self,
        workspace_path: Path,
        *,
        embedder: EmbeddingBackend | None = None,
    ) -> None:
        self.workspace_path = Path(workspace_path)
        self.knowledge_path = self.workspace_path / KNOWLEDGE_DIR
        self.db_path = self.knowledge_path / DB_FILENAME
        self.qdrant_path = self.knowledge_path / QDRANT_DIR
        self.embedder = embedder or FastEmbedBackend(
            cache_dir=self.workspace_path / KNOWLEDGE_DIR / "fastembed_cache",
        )
        self._qdrant: QdrantClient | None = None
        self._qdrant_lock = threading.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._uri_locks: dict[str, asyncio.Lock] = {}
        self.knowledge_path.mkdir(parents=True, exist_ok=True)
        self.qdrant_path.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

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

    async def close(self) -> None:
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        if self._qdrant is not None:
            self._qdrant.close()
            self._qdrant = None

    async def scan_folder(self, folder: str, *, recursive: bool = True) -> ScanFolderResult:
        root = Path(folder).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Folder not found: {root}")
        return await asyncio.to_thread(self._scan_folder_sync, root, recursive)

    async def start_ingest(
        self,
        paths: Sequence[str],
        *,
        owner_kind: str = "system",
        owner_id: str = "0",
        category_id: int | None = None,
        subcategory_id: int | None = None,
        tags: Sequence[str] | None = None,
    ) -> KnowledgeJobResult:
        job_id = str(uuid.uuid4())
        clean_paths = [str(Path(p).expanduser().resolve()) for p in paths if str(p).strip()]
        params = {
            "paths": clean_paths,
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            "category_id": category_id,
            "subcategory_id": subcategory_id,
            "tags": list(tags or []),
        }
        totals = {"requested": len(clean_paths), "skipped": 0, "ingested": 0, "failed": 0, "chunks": 0}
        await asyncio.to_thread(self._insert_job, job_id, "running", totals, {}, params)
        task = asyncio.create_task(
            self._run_ingest_job(job_id, clean_paths, params),
            name=f"knowledge-ingest-{job_id}",
        )
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
        return KnowledgeJobResult(job_id=job_id, status="running", totals=totals)

    async def ingest_and_wait(
        self,
        paths: Sequence[str],
        *,
        owner_kind: str = "system",
        owner_id: str = "0",
        category_id: int | None = None,
        subcategory_id: int | None = None,
        tags: Sequence[str] | None = None,
    ) -> KnowledgeJobResult:
        started = await self.start_ingest(
            paths,
            owner_kind=owner_kind,
            owner_id=owner_id,
            category_id=category_id,
            subcategory_id=subcategory_id,
            tags=tags,
        )
        task = self._tasks.get(started.job_id)
        if task is not None:
            await task
        return await self.job_status(started.job_id)

    async def job_status(self, job_id: str) -> KnowledgeJobResult:
        row = await asyncio.to_thread(self._job_row, job_id)
        if row is None:
            raise KeyError(f"Unknown knowledge job: {job_id}")
        return KnowledgeJobResult(
            job_id=row["id"],
            status=row["status"],
            totals=json.loads(row["totals_json"] or "{}"),
            errors=json.loads(row["errors_json"] or "{}"),
        )

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> KnowledgeSearchResult:
        text = query.strip()
        if not text:
            return KnowledgeSearchResult(query=query, hits=[])
        vector = await asyncio.to_thread(self.embedder.embed_texts, [text])
        query_filter = self._build_filter(filters or {})
        response = await asyncio.to_thread(
            self.qdrant.query_points,
            collection_name=COLLECTION_NAME,
            query=vector[0],
            query_filter=query_filter,
            limit=max(1, min(int(top_k), 100)),
            score_threshold=min_score if min_score > 0 else None,
            with_payload=True,
            with_vectors=False,
        )
        hits: list[KnowledgeSearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                KnowledgeSearchHit(
                    document_id=str(payload.get("document_id", "")),
                    point_id=str(point.id),
                    score=float(point.score or 0.0),
                    ord=int(payload.get("ord") or 0),
                    text=str(payload.get("text") or ""),
                    heading_path=payload.get("heading_path"),
                    title=str(payload.get("title") or ""),
                    source_uri=str(payload.get("source_uri") or ""),
                    owner_kind=str(payload.get("owner_kind") or ""),
                    owner_id=str(payload.get("owner_id") or ""),
                    tags=list(payload.get("tags") or []),
                )
            )
        log.info("knowledge.search", hits=len(hits), top_k=top_k)
        return KnowledgeSearchResult(query=query, hits=hits)

    async def list_documents(
        self,
        *,
        status: str | None = None,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        title: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> KnowledgeListDocumentsResult:
        return await asyncio.to_thread(
            self._list_documents_sync,
            status,
            owner_kind,
            owner_id,
            title,
            limit,
            offset,
        )

    async def get_document(self, document_id: str, *, chunk_limit: int = 100) -> KnowledgeDocumentDetailResult:
        row = await asyncio.to_thread(self._document_row_by_id, document_id)
        document = _document_from_row(row) if row else None
        if document is None:
            return KnowledgeDocumentDetailResult(document=None, chunks=[])
        chunks = await asyncio.to_thread(self._chunks_for_document, document_id, chunk_limit)
        return KnowledgeDocumentDetailResult(document=document, chunks=chunks)

    async def list_tags(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_table, "knowledge_tags")

    async def list_categories(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_table, "knowledge_categories")

    def _scan_folder_sync(self, root: Path, recursive: bool) -> ScanFolderResult:
        pattern = "**/*" if recursive else "*"
        known = self._known_source_uris()
        files: list[ScannedFile] = []
        for path in sorted(p for p in root.glob(pattern) if p.is_file()):
            ext = path.suffix.lower()
            supported = ext in SUPPORTED_EXTENSIONS
            files.append(
                ScannedFile(
                    path=str(path),
                    relative_path=str(path.relative_to(root)),
                    ext=ext,
                    size_bytes=path.stat().st_size,
                    supported=supported,
                    already_ingested=str(path.resolve()) in known,
                    disabled_reason=None if supported else f"Unsupported extension: {ext or '(none)'}",
                )
            )
        return ScanFolderResult(root=str(root), files=files)

    async def _run_ingest_job(self, job_id: str, paths: list[str], params: dict[str, Any]) -> None:
        totals = {"requested": len(paths), "skipped": 0, "ingested": 0, "failed": 0, "chunks": 0}
        errors: dict[str, str] = {}
        try:
            for raw_path in paths:
                try:
                    chunks = await self._ingest_one(raw_path, params)
                    if chunks is None:
                        totals["skipped"] += 1
                    else:
                        totals["ingested"] += 1
                        totals["chunks"] += chunks
                except Exception as exc:
                    totals["failed"] += 1
                    errors[raw_path] = str(exc)
                    log.error("knowledge ingest file failed", path=raw_path, error=str(exc), exc_info=True)
                await asyncio.to_thread(self._update_job, job_id, "running", totals, errors)
                self._publish(KNOWLEDGE_JOB_PROGRESS, {"job_id": job_id, "totals": totals, "errors": errors})
            status = "failed" if totals["failed"] and not totals["ingested"] else "completed"
            await asyncio.to_thread(self._finish_job, job_id, status, totals, errors)
            self._publish(KNOWLEDGE_JOB_COMPLETED if status == "completed" else KNOWLEDGE_JOB_FAILED, {
                "job_id": job_id,
                "totals": totals,
                "errors": errors,
            })
            log.info("knowledge ingest job", status=status, files=totals["ingested"], chunks=totals["chunks"])
        except Exception as exc:
            errors["job"] = str(exc)
            await asyncio.to_thread(self._finish_job, job_id, "failed", totals, errors)
            self._publish(KNOWLEDGE_JOB_FAILED, {"job_id": job_id, "totals": totals, "errors": errors})
            raise

    async def _ingest_one(self, raw_path: str, params: dict[str, Any]) -> int | None:
        path = Path(raw_path).expanduser().resolve()
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {path.suffix}")
        lock = self._uri_locks.setdefault(str(path), asyncio.Lock())
        async with lock:
            data = await asyncio.to_thread(path.read_bytes)
            content_hash = hashlib.sha256(data).hexdigest()
            existing = await asyncio.to_thread(self._document_row_by_source, str(path))
            if existing and existing["content_hash"] == content_hash and existing["status"] == "ready":
                return None
            text = data.decode("utf-8-sig")
            title = _title_from_markdown(text, path)
            chunks = _chunk_markdown(text)
            if not chunks:
                raise ValueError("No text chunks produced.")
            vectors = await asyncio.to_thread(self.embedder.embed_texts, [c["text"] for c in chunks])
            if len(vectors) != len(chunks):
                raise RuntimeError("Embedding backend returned the wrong number of vectors.")
            now = _now()
            document_id = existing["id"] if existing else str(uuid.uuid4())
            await asyncio.to_thread(
                self._upsert_document_and_vectors,
                document_id,
                path,
                title,
                content_hash,
                len(data),
                chunks,
                vectors,
                params,
                now,
            )
            self._publish(KNOWLEDGE_INGESTED, {"document_id": document_id, "source_uri": str(path)})
            return len(chunks)

    def _upsert_document_and_vectors(
        self,
        document_id: str,
        path: Path,
        title: str,
        content_hash: str,
        size_bytes: int,
        chunks: list[dict[str, str | None]],
        vectors: list[list[float]],
        params: dict[str, Any],
        now: str,
    ) -> None:
        client = self.qdrant
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qm.FilterSelector(filter=_document_filter(document_id)),
            wait=True,
        )
        tags = self._ensure_tags(params.get("tags") or [])
        payload_base = {
            "document_id": document_id,
            "owner_kind": params.get("owner_kind") or "system",
            "owner_id": params.get("owner_id") or "0",
            "category_id": params.get("category_id"),
            "subcategory_id": params.get("subcategory_id"),
            "tags": tags,
            "source_type": "file",
            "mime": "text/markdown",
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
        client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
        self._upsert_document_row(
            document_id,
            path,
            title,
            content_hash,
            size_bytes,
            len(chunks),
            params,
            now,
        )

    def _ensure_db(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                  id TEXT PRIMARY KEY,
                  source_uri TEXT NOT NULL UNIQUE,
                  source_type TEXT NOT NULL,
                  mime TEXT NOT NULL,
                  ext TEXT NOT NULL,
                  owner_kind TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  category_id INTEGER NULL,
                  subcategory_id INTEGER NULL,
                  title TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL,
                  chunk_count INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  error TEXT NULL,
                  ingested_at TEXT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_categories (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  parent_id INTEGER NULL REFERENCES knowledge_categories(id) ON DELETE CASCADE,
                  UNIQUE(parent_id, name)
                );
                CREATE TABLE IF NOT EXISTS knowledge_tags (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS knowledge_document_tags (
                  document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                  tag_id INTEGER NOT NULL REFERENCES knowledge_tags(id) ON DELETE CASCADE,
                  PRIMARY KEY (document_id, tag_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_ingestion_jobs (
                  id TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL,
                  finished_at TEXT NULL,
                  status TEXT NOT NULL,
                  totals_json TEXT NOT NULL,
                  errors_json TEXT NOT NULL,
                  params_json TEXT NOT NULL
                );
                """
            )

    def _ensure_collection(self) -> None:
        client = self._qdrant
        if client is None:
            raise RuntimeError("Qdrant client is not initialized.")
        if client.collection_exists(COLLECTION_NAME):
            current_size = self._collection_vector_size(client)
            if current_size is not None and current_size != self.embedder.dimension:
                point_count = client.count(COLLECTION_NAME, exact=True).count
                if point_count:
                    raise RuntimeError(
                        f"Knowledge collection vector size is {current_size}, "
                        f"but embedder {DEFAULT_EMBEDDING_MODEL} uses {self.embedder.dimension}. "
                        "Delete existing knowledge documents before changing embedding models."
                    )
                client.delete_collection(COLLECTION_NAME)
            else:
                return
        if not client.collection_exists(COLLECTION_NAME):
            client.create_collection(
                collection_name=COLLECTION_NAME,
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
                    client.create_payload_index(COLLECTION_NAME, field_name, field_schema=schema)
            except Exception:
                pass

    def _collection_vector_size(self, client: QdrantClient) -> int | None:
        info = client.get_collection(COLLECTION_NAME)
        vectors = info.config.params.vectors
        if hasattr(vectors, "size"):
            return int(vectors.size)
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            if hasattr(first, "size"):
                return int(first.size)
        return None

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _known_source_uris(self) -> set[str]:
        with self._connect() as con:
            rows = con.execute("SELECT source_uri FROM knowledge_documents WHERE status = 'ready'").fetchall()
            return {str(row["source_uri"]) for row in rows}

    def _insert_job(
        self,
        job_id: str,
        status: str,
        totals: dict[str, int],
        errors: dict[str, str],
        params: dict[str, Any],
    ) -> None:
        now = _now()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO knowledge_ingestion_jobs
                (id, created_at, finished_at, status, totals_json, errors_json, params_json)
                VALUES (?, ?, NULL, ?, ?, ?, ?)
                """,
                (job_id, now, status, json.dumps(totals), json.dumps(errors), json.dumps(params)),
            )

    def _update_job(self, job_id: str, status: str, totals: dict[str, int], errors: dict[str, str]) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE knowledge_ingestion_jobs SET status = ?, totals_json = ?, errors_json = ? WHERE id = ?",
                (status, json.dumps(totals), json.dumps(errors), job_id),
            )

    def _finish_job(self, job_id: str, status: str, totals: dict[str, int], errors: dict[str, str]) -> None:
        with self._connect() as con:
            con.execute(
                """
                UPDATE knowledge_ingestion_jobs
                SET status = ?, totals_json = ?, errors_json = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, json.dumps(totals), json.dumps(errors), _now(), job_id),
            )

    def _job_row(self, job_id: str) -> sqlite3.Row | None:
        with self._connect() as con:
            return con.execute("SELECT * FROM knowledge_ingestion_jobs WHERE id = ?", (job_id,)).fetchone()

    def _document_row_by_source(self, source_uri: str) -> sqlite3.Row | None:
        with self._connect() as con:
            return con.execute("SELECT * FROM knowledge_documents WHERE source_uri = ?", (source_uri,)).fetchone()

    def _document_row_by_id(self, document_id: str) -> sqlite3.Row | None:
        with self._connect() as con:
            return con.execute("SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)).fetchone()

    def _upsert_document_row(
        self,
        document_id: str,
        path: Path,
        title: str,
        content_hash: str,
        size_bytes: int,
        chunk_count: int,
        params: dict[str, Any],
        now: str,
    ) -> None:
        tags = self._ensure_tags(params.get("tags") or [])
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO knowledge_documents (
                  id, source_uri, source_type, mime, ext, owner_kind, owner_id,
                  category_id, subcategory_id, title, content_hash, size_bytes,
                  chunk_count, status, error, ingested_at, updated_at
                )
                VALUES (?, ?, 'file', 'text/markdown', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', NULL, ?, ?)
                ON CONFLICT(source_uri) DO UPDATE SET
                  id = excluded.id,
                  ext = excluded.ext,
                  owner_kind = excluded.owner_kind,
                  owner_id = excluded.owner_id,
                  category_id = excluded.category_id,
                  subcategory_id = excluded.subcategory_id,
                  title = excluded.title,
                  content_hash = excluded.content_hash,
                  size_bytes = excluded.size_bytes,
                  chunk_count = excluded.chunk_count,
                  status = 'ready',
                  error = NULL,
                  ingested_at = excluded.ingested_at,
                  updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    str(path),
                    path.suffix.lower(),
                    params.get("owner_kind") or "system",
                    params.get("owner_id") or "0",
                    params.get("category_id"),
                    params.get("subcategory_id"),
                    title,
                    content_hash,
                    size_bytes,
                    chunk_count,
                    now,
                    now,
                ),
            )
            con.execute("DELETE FROM knowledge_document_tags WHERE document_id = ?", (document_id,))
            for tag in tags:
                tag_id = con.execute("SELECT id FROM knowledge_tags WHERE name = ?", (tag,)).fetchone()["id"]
                con.execute(
                    "INSERT OR IGNORE INTO knowledge_document_tags (document_id, tag_id) VALUES (?, ?)",
                    (document_id, tag_id),
                )

    def _ensure_tags(self, tags: Sequence[str]) -> list[str]:
        clean = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
        if not clean:
            return []
        with self._connect() as con:
            for tag in clean:
                con.execute("INSERT OR IGNORE INTO knowledge_tags (name) VALUES (?)", (tag,))
        return clean

    def _list_documents_sync(
        self,
        status: str | None,
        owner_kind: str | None,
        owner_id: str | None,
        title: str | None,
        limit: int,
        offset: int,
    ) -> KnowledgeListDocumentsResult:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if owner_kind:
            clauses.append("owner_kind = ?")
            params.append(owner_kind)
        if owner_id:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        if title:
            clauses.append("title LIKE ?")
            params.append(f"%{title}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as con:
            total = con.execute(f"SELECT COUNT(*) AS n FROM knowledge_documents {where}", params).fetchone()["n"]
            rows = con.execute(
                f"""
                SELECT * FROM knowledge_documents
                {where}
                ORDER BY COALESCE(ingested_at, updated_at) DESC
                LIMIT ? OFFSET ?
                """,
                [*params, max(1, min(int(limit), 200)), max(0, int(offset))],
            ).fetchall()
        return KnowledgeListDocumentsResult(
            documents=[_document_from_row(row) for row in rows],
            total=int(total),
        )

    def _chunks_for_document(self, document_id: str, limit: int) -> list[dict[str, Any]]:
        records, _ = self.qdrant.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=_document_filter(document_id),
            limit=max(1, min(int(limit), 500)),
            with_payload=True,
            with_vectors=False,
        )
        chunks: list[dict[str, Any]] = []
        for record in records:
            payload = dict(record.payload or {})
            payload["point_id"] = str(record.id)
            chunks.append(payload)
        chunks.sort(key=lambda item: int(item.get("ord") or 0))
        return chunks

    def _list_table(self, table: str) -> list[dict[str, Any]]:
        if table not in {"knowledge_tags", "knowledge_categories"}:
            raise ValueError("Unsupported table.")
        with self._connect() as con:
            rows = con.execute(f"SELECT * FROM {table} ORDER BY name").fetchall()
            return [dict(row) for row in rows]

    def _build_filter(self, filters: dict[str, Any]) -> qm.Filter | None:
        conditions: list[qm.FieldCondition] = []
        for key in ("owner_kind", "owner_id", "document_id"):
            value = filters.get(key)
            if value not in (None, ""):
                conditions.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=str(value))))
        for key in ("category_id", "subcategory_id"):
            value = filters.get(key)
            if value not in (None, ""):
                conditions.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=int(value))))
        for tag in filters.get("tags") or []:
            if str(tag).strip():
                conditions.append(qm.FieldCondition(key="tags", match=qm.MatchValue(value=str(tag).strip())))
        return qm.Filter(must=conditions) if conditions else None

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        get_domain_event_bus().publish(
            DomainEvent(type=event_type, workspace_path=self.workspace_path, payload=payload)
        )


def _document_from_row(row: sqlite3.Row) -> KnowledgeDocumentRow:
    return KnowledgeDocumentRow(
        id=row["id"],
        source_uri=row["source_uri"],
        source_type=row["source_type"],
        mime=row["mime"],
        ext=row["ext"],
        owner_kind=row["owner_kind"],
        owner_id=row["owner_id"],
        category_id=row["category_id"],
        subcategory_id=row["subcategory_id"],
        title=row["title"],
        content_hash=row["content_hash"],
        size_bytes=row["size_bytes"],
        chunk_count=row["chunk_count"],
        status=row["status"],
        error=row["error"],
        ingested_at=row["ingested_at"],
        updated_at=row["updated_at"],
    )


def _document_filter(document_id: str) -> qm.Filter:
    return qm.Filter(
        must=[
            qm.FieldCondition(
                key="document_id",
                match=qm.MatchValue(value=str(document_id)),
            )
        ]
    )


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _title_from_markdown(text: str, path: Path) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return path.stem


def _chunk_markdown(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, str | None]]:
    sections: list[dict[str, str | None]] = []
    heading_stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    current_heading: str | None = None

    def flush() -> None:
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            sections.append({"text": body, "heading_path": current_heading})
        buffer = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= hashes <= 6 and stripped[hashes:hashes + 1] == " ":
                flush()
                heading = stripped[hashes:].strip()
                heading_stack = [(lvl, val) for lvl, val in heading_stack if lvl < hashes]
                heading_stack.append((hashes, heading))
                current_heading = " / ".join(f"{'#' * lvl} {val}" for lvl, val in heading_stack)
        buffer.append(line)
    flush()

    if not sections and text.strip():
        sections.append({"text": text.strip(), "heading_path": None})

    chunks: list[dict[str, str | None]] = []
    for section in sections:
        body = str(section["text"] or "")
        heading_path = section["heading_path"]
        if len(body) <= chunk_size:
            chunks.append({"text": body, "heading_path": heading_path})
            continue
        start = 0
        step = max(1, chunk_size - chunk_overlap)
        while start < len(body):
            end = min(len(body), start + chunk_size)
            if end < len(body):
                newline = body.rfind("\n", start, end)
                if newline > start + math.floor(chunk_size * 0.5):
                    end = newline
            chunk = body[start:end].strip()
            if chunk:
                chunks.append({"text": chunk, "heading_path": heading_path})
            if end >= len(body):
                break
            start = max(end - chunk_overlap, start + step)
    return chunks
