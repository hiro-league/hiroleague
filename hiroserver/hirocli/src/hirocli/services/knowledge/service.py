"""Workspace-local knowledge service for markdown ingest and vector search."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hiro_commons.constants.storage import DB_DIR
from hiro_commons.log import Logger
from hiro_memory.knowledge.agent import KnowledgeAgentGraph, build_qdrant_filter
from hiro_memory.knowledge.answer import answer_result, answer_state, run_answer
from hiro_memory.knowledge.catalog_store import CatalogStore
from hiro_memory.knowledge.converters import (
    bounded_file_concurrency,
    default_file_concurrency_for_embedder,
    document_from_row,
    job_from_row,
)
from hiro_memory.knowledge.embedding_backends import (
    EmbeddingBackend,
    SparseEmbeddingBackend,
)
from hiro_memory.knowledge.index import KnowledgeIndex
from hiro_memory.knowledge.loaders import DEFAULT_LOADER_REGISTRY, LoaderRegistry
from hiro_memory.knowledge.models import (
    KnowledgeAnswerResult,
    KnowledgeDocumentRow,
    KnowledgeJobResult,
    KnowledgeListDocumentsResult,
    KnowledgeListJobsResult,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    ScanFolderResult,
)
from hiro_memory.knowledge.runtime_owner import current_owner_token
from hiro_memory.knowledge.scanner import SourceScanner
from hiro_memory.knowledge.settings import KnowledgeChunkingSettings
from hiro_memory.knowledge.vector_store import KnowledgeVectorStore
from hiro_memory.ledger.node_group import LedgerSinkRef

from hirocli.domain.events import DomainEvent, get_domain_event_bus
from hirocli.domain.preferences import load_preferences
from hirocli.runtime.agent_graph.workspace_ledger import workspace_ledger_sink
from hirocli.services.knowledge.audit_log import (
    build_answer_audit,
    build_ingest_audit,
    build_search_audit,
    log_knowledge_answer,
    log_knowledge_ingest,
    log_knowledge_search,
)
from hirocli.services.knowledge.constants import (
    DB_FILENAME,
    KNOWLEDGE_DELETED,
    KNOWLEDGE_DIR,
    KNOWLEDGE_INGESTED,
    KNOWLEDGE_JOB_COMPLETED,
    KNOWLEDGE_JOB_FAILED,
    KNOWLEDGE_JOB_PROGRESS,
    KNOWLEDGE_JOB_STARTED,
    MAX_FILE_SIZE_BYTES,
    QDRANT_DIR,
)
from hirocli.services.knowledge.graph_wiring import knowledge_graph_config
from hirocli.services.knowledge.live_registry import register_live_service, unregister_live_service
from hirocli.services.knowledge.preview import FilePreviewResult, read_file_preview

if TYPE_CHECKING:
    from hiro_memory.knowledge.models import KnowledgeAnswerComparison

    from hirocli.domain.preferences import WorkspacePreferences

log = Logger.get("SVC.KNOWLEDGE")


def _resolved_paths(paths: Sequence[str]) -> list[str]:
    """The ingest's paths, absolute (resolving touches the disk, so it runs off the event loop)."""
    return [str(Path(p).expanduser().resolve()) for p in paths if str(p).strip()]


@dataclass
class _DownloadJob:
    """A running local-model download (a killable subprocess + progress baseline).

    Shared by the reranker and embedder download lanes (same subprocess mechanism)."""

    process: subprocess.Popen  # the download subprocess
    baseline_bytes: int  # cache size at start; progress = (current - baseline) / expected
    expected_bytes: int  # approximate total from the model's size label
    cancelled: bool = False


class KnowledgeService(KnowledgeIndex):
    """The workspace's knowledge base: the memory library's ``KnowledgeIndex`` (ingest a file, retrieve, read a
    document) with the core's own on top: its files' places, preferences, ingest jobs, events, local model
    downloads, and the graph's upkeep."""

    def __init__(
        self,
        workspace_path: Path,
        *,
        embedder: EmbeddingBackend | None = None,
        sparse_embedder: SparseEmbeddingBackend | None = None,
        loader_registry: LoaderRegistry | None = None,
        prefs_provider: Callable[[], WorkspacePreferences] | None = None,
    ) -> None:
        self.workspace_path = Path(workspace_path)
        self._prefs_provider = prefs_provider
        # knowledge/ still hosts regenerable caches (fastembed); the databases themselves
        # (knowledge.db + qdrant/) live in the consolidated db/ folder.
        self.knowledge_path = self.workspace_path / KNOWLEDGE_DIR
        db_root = self.workspace_path / DB_DIR
        self.db_path = db_root / DB_FILENAME
        self.qdrant_path = db_root / QDRANT_DIR
        dense = embedder or self._default_embedder_for_workspace()
        super().__init__(
            catalog=CatalogStore(self.db_path),
            vector_store=KnowledgeVectorStore(self.qdrant_path, dense),
            embedder=dense,
            # BM25 sparse backend for hybrid retrieval — local and independent of the dense model.
            sparse_embedder=sparse_embedder or self._default_sparse_embedder_for_workspace(),
            loader_registry=loader_registry or DEFAULT_LOADER_REGISTRY,
        )
        self.scanner = SourceScanner(self.loader_registry, self.catalog)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Cached reranker compressor (model load is expensive — keyed by model/top_n/device).
        self._reranker_key: tuple[str, int, str] | None = None
        self._reranker_compressor: Any | None = None
        self._reranker_calibrated: bool = True
        # In-flight local-reranker downloads (killable spawn processes), keyed by model_id, and
        # terminal error messages for the last failed download. The downloaded marker is the
        # source of truth for "ready". Surfaced via reranker_options() for the admin poll.
        self._reranker_jobs: dict[str, _DownloadJob] = {}
        self._reranker_errors: dict[str, str] = {}
        # In-flight local-embedder downloads + last terminal errors (same mechanism as rerankers).
        self._embedder_jobs: dict[str, _DownloadJob] = {}
        self._embedder_errors: dict[str, str] = {}
        self.owner_token = current_owner_token()
        self.knowledge_path.mkdir(parents=True, exist_ok=True)
        self.qdrant_path.mkdir(parents=True, exist_ok=True)
        self.catalog.ensure_schema()
        register_live_service(self)

    def workspace_prefs(self) -> WorkspacePreferences:
        """Return current workspace preferences without redundant disk reads when wired."""
        if self._prefs_provider is not None:
            return self._prefs_provider()
        return load_preferences(self.workspace_path)

    def _default_embedder_for_workspace(self) -> EmbeddingBackend:
        from hirocli.domain.preferences import resolve_knowledge_embedder_model
        from hirocli.services.knowledge.embedder import resolve_knowledge_embedder

        prefs = self.workspace_prefs()
        return resolve_knowledge_embedder(
            self.workspace_path,
            resolve_knowledge_embedder_model(prefs),
        )

    def _default_sparse_embedder_for_workspace(self) -> SparseEmbeddingBackend:
        from hirocli.services.knowledge.embedder import resolve_knowledge_sparse_embedder

        # Sparse model is a fixed constant (no longer a preference) — resolver uses its default.
        return resolve_knowledge_sparse_embedder(self.workspace_path)

    def reload_embedder(self, embedder: EmbeddingBackend) -> None:
        """Swap the active embedder after a preference change (empty collection only)."""
        previous = getattr(self.embedder, "model_name", None)
        self.embedder = embedder
        self.vector_store.reload_embedder(embedder)
        log.info(
            "✅ Knowledge embedder swapped — HiroServer",
            previous=previous,
            current=getattr(embedder, "model_name", None),
            dimension=embedder.dimension,
        )

    @property
    def qdrant(self):
        """Backward-compatible Qdrant client access for tests and live registry."""
        return self.vector_store.qdrant

    async def close(self) -> None:
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        # Terminate any in-flight download processes so they don't outlive the service.
        for model_id in list(self._reranker_jobs):
            self.cancel_reranker_download(model_id)
        for model_id in list(self._embedder_jobs):
            self.cancel_embedder_download(model_id)
        self.vector_store.close()
        unregister_live_service(self)

    async def scan_folder(self, folder: str, *, recursive: bool = True) -> ScanFolderResult:
        root = await asyncio.to_thread(lambda: Path(folder).expanduser().resolve())
        if not await asyncio.to_thread(root.is_dir):
            raise FileNotFoundError(f"Folder not found: {root}")
        return await asyncio.to_thread(self.scanner.scan, root, recursive=recursive)

    async def preview_file(self, path: str) -> FilePreviewResult:
        return await asyncio.to_thread(read_file_preview, Path(path), loader_registry=self.loader_registry)

    def _resolve_file_concurrency(self, file_concurrency: int | None) -> int:
        fallback = default_file_concurrency_for_embedder(self.embedder)
        if file_concurrency is None:
            return fallback
        return bounded_file_concurrency(file_concurrency, fallback=fallback)

    async def start_ingest(
        self,
        paths: Sequence[str],
        *,
        owner_kind: str = "system",
        owner_id: str = "0",
        category_id: int | None = None,
        subcategory_id: int | None = None,
        tags: Sequence[str] | None = None,
        file_concurrency: int | None = None,
        force_reingest: bool = False,
    ) -> KnowledgeJobResult:
        await asyncio.to_thread(self.catalog.validate_category_assignment, category_id, subcategory_id)
        job_id = str(uuid.uuid4())
        clean_paths = await asyncio.to_thread(_resolved_paths, paths)
        resolved_file_concurrency = self._resolve_file_concurrency(file_concurrency)
        params = {
            "paths": clean_paths,
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            "category_id": category_id,
            "subcategory_id": subcategory_id,
            "tags": list(tags or []),
            "file_concurrency": resolved_file_concurrency,
            "force_reingest": force_reingest,
        }
        totals = {"requested": len(clean_paths), "skipped": 0, "ingested": 0, "failed": 0, "chunks": 0}
        await asyncio.to_thread(self._insert_job, job_id, "running", totals, {}, params)
        self._publish(
            KNOWLEDGE_JOB_STARTED,
            {
                "job_id": job_id,
                "totals": dict(totals),
                "errors": {},
                "in_flight": [],
            },
        )
        task = asyncio.create_task(
            self._run_ingest_job_story(job_id, clean_paths, params),
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
        file_concurrency: int | None = None,
    ) -> KnowledgeJobResult:
        started = await self.start_ingest(
            paths,
            owner_kind=owner_kind,
            owner_id=owner_id,
            category_id=category_id,
            subcategory_id=subcategory_id,
            tags=tags,
            file_concurrency=file_concurrency,
        )
        task = self._tasks.get(started.job_id)
        if task is not None:
            await task
        return await self.job_status(started.job_id)

    async def job_status(self, job_id: str) -> KnowledgeJobResult:
        row = await asyncio.to_thread(self.catalog.job_row, job_id)
        if row is None:
            raise KeyError(f"Unknown knowledge job: {job_id}")
        return KnowledgeJobResult(
            job_id=row["id"],
            status=row["status"],
            totals=json.loads(row["totals_json"] or "{}"),
            errors=json.loads(row["errors_json"] or "{}"),
        )

    async def list_jobs(self, *, limit: int = 20) -> KnowledgeListJobsResult:
        rows = await asyncio.to_thread(self.catalog.list_jobs, limit)
        return KnowledgeListJobsResult(jobs=[job_from_row(row) for row in rows])

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
        explain: bool = False,
    ) -> KnowledgeSearchResult:
        text = query.strip()
        if not text:
            return KnowledgeSearchResult(query=query, hits=[])
        t0 = time.perf_counter()
        retrieval = self.workspace_prefs().knowledge.retrieval
        vector = await self.embed_query(text)
        # Skip the BM25 query embed entirely when hybrid is off — pure dense path.
        sparse_vector = await self.embed_query_sparse(text) if retrieval.hybrid else None
        # L3 — ``filters`` may carry a ``chunk_ids`` key (set by callers wanting
        # graph-focused search); build_qdrant_filter folds it in as a HasIdCondition.
        hits = await self.vector_search_by_vector(
            vector,
            sparse_vector,
            top_k=top_k,
            min_score=min_score,
            prefetch_limit=retrieval.prefetch_limit,
            hybrid=retrieval.hybrid,
            explain=explain,
            qdrant_filter=build_qdrant_filter(filters or {}),
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log_knowledge_search(
            log,
            build_search_audit(
                query=query,
                top_k=top_k,
                min_score=min_score,
                filters=filters or {},
                hits=hits,
                elapsed_ms=elapsed_ms,
            ),
        )
        return KnowledgeSearchResult(query=query, hits=hits)

    async def rerank_hits(
        self,
        query: str,
        hits: list[KnowledgeSearchHit],
        *,
        model_id: str,
        top_n: int,
        device: str | None = None,
        workspace_id: str | None = None,
    ) -> list[KnowledgeSearchHit]:
        """Rerank retrieved hits with the active reranker (cloud or local).

        Builds + caches the compressor on first use, then reorders/trims off the event loop.
        Raises on resolution/inference failure — the graph node catches and falls back to the
        retrieval order, so reranking never blocks an answer.
        """
        if not hits:
            return []
        from hiro_memory.knowledge.rerank import rerank_hits as _rerank_hits

        from hirocli.services.knowledge.reranker import resolve_reranker

        key = (model_id, int(top_n), device or "")
        if self._reranker_key != key or self._reranker_compressor is None:
            compressor, calibrated = await asyncio.to_thread(
                resolve_reranker,
                model_id,
                workspace_path=self.workspace_path,
                workspace_id=workspace_id,
                top_n=int(top_n),
                device=device,
            )
            self._reranker_compressor = compressor
            self._reranker_calibrated = calibrated
            self._reranker_key = key
        return await asyncio.to_thread(
            _rerank_hits,
            self._reranker_compressor,
            query,
            list(hits),
            scores_calibrated=self._reranker_calibrated,
            top_n=int(top_n),
        )

    async def download_reranker(self, model_id: str) -> dict[str, Any]:
        """Download a local reranker's weights synchronously (no model is fetched silently).

        Blocking — used for short-lived (owned) services. Live services use the non-blocking
        ``start_reranker_download`` so a multi-GB fetch never holds the HTTP request open.
        """
        from hirocli.services.knowledge.reranker_registry import (
            download,
            get_local_reranker,
            reranker_cache_dir,
        )

        spec = get_local_reranker(model_id)
        if spec is None:
            raise KeyError(f"Unknown local reranker: {model_id}")
        await asyncio.to_thread(download, spec, reranker_cache_dir(self.workspace_path))
        return {"model_id": model_id, "status": "ready"}

    def start_reranker_download(self, model_id: str) -> dict[str, Any]:
        """Start a download in a killable spawn process and return immediately.

        The admin UI polls ``reranker_options`` for live ``downloading`` (with byte progress) →
        ``ready`` / ``error``, and may ``cancel_reranker_download`` to terminate the process.
        """
        from hirocli.services.knowledge.download_markers import (
            dir_size_bytes,
            parse_size_label,
        )
        from hirocli.services.knowledge.reranker_registry import (
            get_local_reranker,
            is_downloaded,
            reranker_cache_dir,
        )

        spec = get_local_reranker(model_id)
        if spec is None:
            raise KeyError(f"Unknown local reranker: {model_id}")
        cache = reranker_cache_dir(self.workspace_path)
        if is_downloaded(spec, cache):
            return {"model_id": model_id, "status": "ready"}
        existing = self._reranker_jobs.get(model_id)
        if existing is not None and existing.process.poll() is None:
            return {"model_id": model_id, "status": "downloading"}
        self._reranker_errors.pop(model_id, None)
        # Run in an isolated subprocess so the download can be truly terminated (an
        # asyncio.to_thread cannot be killed). A subprocess (vs. multiprocessing) avoids
        # re-importing the server's __main__ on Windows spawn.
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "hirocli.services.knowledge.download_entry",
                "reranker",
                model_id,
                str(cache),
            ],
        )
        self._reranker_jobs[model_id] = _DownloadJob(
            process=proc,
            baseline_bytes=dir_size_bytes(cache),
            expected_bytes=parse_size_label(spec.size_label),
        )
        log.info("⬇️ Reranker download started — %s", model_id, size=spec.size_label)
        return {"model_id": model_id, "status": "downloading"}

    def cancel_reranker_download(self, model_id: str) -> dict[str, Any]:
        """Terminate an in-flight local-reranker download (best-effort kill of the subprocess)."""
        job = self._reranker_jobs.pop(model_id, None)
        if job is None:
            return {"model_id": model_id, "status": "available"}
        job.cancelled = True
        try:
            if job.process.poll() is None:
                job.process.terminate()
                try:
                    job.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    job.process.kill()
        except Exception:
            log.warning("⚠️ Reranker download cancel failed — %s", model_id, exc_info=True)
        self._reranker_errors.pop(model_id, None)
        log.info("🛑 Reranker download cancelled — %s", model_id)
        return {"model_id": model_id, "status": "cancelled"}

    def _poll_reranker_jobs(self) -> None:
        """Reap finished download subprocesses: success → marker (ready); non-zero exit → error."""
        from hirocli.services.knowledge.reranker_registry import (
            get_local_reranker,
            is_downloaded,
            reranker_cache_dir,
        )

        cache = reranker_cache_dir(self.workspace_path)
        for model_id, job in list(self._reranker_jobs.items()):
            if job.process.poll() is None:
                continue
            self._reranker_jobs.pop(model_id, None)
            if job.cancelled:
                continue
            spec = get_local_reranker(model_id)
            if spec is not None and is_downloaded(spec, cache):
                continue  # success — marker present
            self._reranker_errors[model_id] = f"download failed (exit {job.process.returncode})"
            log.error("❌ Reranker download failed — %s · exit %s", model_id, job.process.returncode)

    def reranker_options(self) -> list[dict[str, Any]]:
        """Local reranker registry rows with per-model download status + byte progress."""
        from hirocli.services.knowledge.download_markers import dir_size_bytes
        from hirocli.services.knowledge.reranker_registry import (
            is_downloaded,
            list_local_rerankers,
            reranker_cache_dir,
        )

        self._poll_reranker_jobs()
        cache = reranker_cache_dir(self.workspace_path)
        current_bytes: int | None = None  # computed once, only if a download is active
        rows: list[dict[str, Any]] = []
        for spec in list_local_rerankers():
            downloaded = is_downloaded(spec, cache)
            job = self._reranker_jobs.get(spec.id)
            error = self._reranker_errors.get(spec.id)
            percent: int | None = None
            downloaded_bytes: int | None = None
            total_bytes: int | None = None
            if downloaded:
                status = "ready"
            elif job is not None and job.process.poll() is None:
                status = "downloading"
                if current_bytes is None:
                    current_bytes = dir_size_bytes(cache)
                downloaded_bytes = max(0, current_bytes - job.baseline_bytes)
                total_bytes = job.expected_bytes or None
                if job.expected_bytes > 0:
                    percent = min(99, int(downloaded_bytes / job.expected_bytes * 100))
            elif error:
                status = "error"
            else:
                status = "available"
            rows.append(
                {
                    "id": spec.id,
                    "display_name": spec.display_name,
                    "backend": spec.backend,
                    "size_label": spec.size_label,
                    "languages": spec.languages,
                    "multilingual": spec.multilingual,
                    "description": spec.description,
                    "downloaded": downloaded,
                    "status": status,
                    "error": error if status == "error" else None,
                    "percent": percent,
                    "downloaded_bytes": downloaded_bytes,
                    "total_bytes": total_bytes,
                }
            )
        return rows

    # --- Local embedder downloads (same killable-subprocess mechanism as rerankers) -----------

    async def download_embedder(self, model_id: str) -> dict[str, Any]:
        """Download a local embedder's weights synchronously (blocking; for owned services)."""
        from hirocli.services.knowledge.embedder_registry import (
            download,
            embedder_cache_dir,
            get_local_embedder,
        )

        spec = get_local_embedder(model_id)
        if spec is None:
            raise KeyError(f"Unknown local embedder: {model_id}")
        await asyncio.to_thread(download, spec, embedder_cache_dir(self.workspace_path))
        return {"model_id": model_id, "status": "ready"}

    def start_embedder_download(self, model_id: str) -> dict[str, Any]:
        """Start a local-embedder download in a killable spawn process and return immediately."""
        from hirocli.services.knowledge.download_markers import (
            dir_size_bytes,
            parse_size_label,
        )
        from hirocli.services.knowledge.embedder_registry import (
            embedder_cache_dir,
            get_local_embedder,
            is_downloaded,
        )

        spec = get_local_embedder(model_id)
        if spec is None:
            raise KeyError(f"Unknown local embedder: {model_id}")
        cache = embedder_cache_dir(self.workspace_path)
        if is_downloaded(spec, cache):
            return {"model_id": model_id, "status": "ready"}
        existing = self._embedder_jobs.get(model_id)
        if existing is not None and existing.process.poll() is None:
            return {"model_id": model_id, "status": "downloading"}
        self._embedder_errors.pop(model_id, None)
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "hirocli.services.knowledge.download_entry",
                "embedder",
                model_id,
                str(cache),
            ],
        )
        self._embedder_jobs[model_id] = _DownloadJob(
            process=proc,
            baseline_bytes=dir_size_bytes(cache),
            expected_bytes=parse_size_label(spec.size_label),
        )
        log.info("⬇️ Embedder download started — %s", model_id, size=spec.size_label)
        return {"model_id": model_id, "status": "downloading"}

    def cancel_embedder_download(self, model_id: str) -> dict[str, Any]:
        """Terminate an in-flight local-embedder download (best-effort kill of the subprocess)."""
        job = self._embedder_jobs.pop(model_id, None)
        if job is None:
            return {"model_id": model_id, "status": "available"}
        job.cancelled = True
        try:
            if job.process.poll() is None:
                job.process.terminate()
                try:
                    job.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    job.process.kill()
        except Exception:
            log.warning("⚠️ Embedder download cancel failed — %s", model_id, exc_info=True)
        self._embedder_errors.pop(model_id, None)
        log.info("🛑 Embedder download cancelled — %s", model_id)
        return {"model_id": model_id, "status": "cancelled"}

    def _poll_embedder_jobs(self) -> None:
        """Reap finished embedder download subprocesses: success → marker (ready); else error."""
        from hirocli.services.knowledge.embedder_registry import (
            embedder_cache_dir,
            get_local_embedder,
            is_downloaded,
        )

        cache = embedder_cache_dir(self.workspace_path)
        for model_id, job in list(self._embedder_jobs.items()):
            if job.process.poll() is None:
                continue
            self._embedder_jobs.pop(model_id, None)
            if job.cancelled:
                continue
            spec = get_local_embedder(model_id)
            if spec is not None and is_downloaded(spec, cache):
                continue  # success — marker present
            self._embedder_errors[model_id] = f"download failed (exit {job.process.returncode})"
            log.error("❌ Embedder download failed — %s · exit %s", model_id, job.process.returncode)

    def embedder_options(self) -> list[dict[str, Any]]:
        """Local embedder registry rows with per-model download status + byte progress."""
        from hirocli.services.knowledge.download_markers import dir_size_bytes
        from hirocli.services.knowledge.embedder_registry import (
            embedder_cache_dir,
            is_downloaded,
            list_local_embedders,
        )

        self._poll_embedder_jobs()
        cache = embedder_cache_dir(self.workspace_path)
        current_bytes: int | None = None  # computed once, only if a download is active
        rows: list[dict[str, Any]] = []
        for spec in list_local_embedders():
            downloaded = is_downloaded(spec, cache)
            job = self._embedder_jobs.get(spec.id)
            error = self._embedder_errors.get(spec.id)
            percent: int | None = None
            downloaded_bytes: int | None = None
            total_bytes: int | None = None
            if downloaded:
                status = "ready"
            elif job is not None and job.process.poll() is None:
                status = "downloading"
                if current_bytes is None:
                    current_bytes = dir_size_bytes(cache)
                downloaded_bytes = max(0, current_bytes - job.baseline_bytes)
                total_bytes = job.expected_bytes or None
                if job.expected_bytes > 0:
                    percent = min(99, int(downloaded_bytes / job.expected_bytes * 100))
            elif error:
                status = "error"
            else:
                status = "available"
            rows.append(
                {
                    "id": spec.id,
                    "display_name": spec.display_name,
                    "size_label": spec.size_label,
                    "dimension": spec.dimension,
                    "languages": spec.languages,
                    "multilingual": spec.multilingual,
                    "description": spec.description,
                    "downloaded": downloaded,
                    "status": status,
                    "error": error if status == "error" else None,
                    "percent": percent,
                    "downloaded_bytes": downloaded_bytes,
                    "total_bytes": total_bytes,
                }
            )
        return rows

    async def answer(
        self,
        query: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        filters: dict[str, Any] | None = None,
        workspace_id: str | None = None,
        explain: bool = False,
        rewrite: bool = False,
        graph_mode: str = "off",
        graph_temporal: str | None = None,
    ) -> KnowledgeAnswerResult:
        prefs = self.workspace_prefs()
        retrieval = prefs.knowledge.retrieval
        graph_builder = KnowledgeAgentGraph(
            LedgerSinkRef(ledger_sink=workspace_ledger_sink(self.workspace_path))
        )
        graph = graph_builder.build(
            knowledge_graph_config(self, prefs, self.workspace_path, workspace_id=workspace_id)
        )
        # graph_mode == "graphiti" turns on the graph_expand node. Useful only when
        # rewrite=True too (rewrite extracts query entities for the graph); a graph
        # mode with rewrite=False is a no-op + a warning.
        if graph_mode == "graphiti" and not rewrite:
            log.warning(
                "⚠️ knowledge.answer — graph_mode=%s without rewrite=True · "
                "graph_expand needs entities from rewrite_query · effectively off",
                graph_mode,
            )
        initial_state = answer_state(
            query,
            top_k=top_k if top_k is not None else retrieval.top_k,
            min_score=min_score if min_score is not None else retrieval.min_score,
            filters=filters,
            explain=explain,
            rewrite=rewrite,
            graph_mode=graph_mode,
            graph_temporal=graph_temporal,
        )
        run = await run_answer(graph, sink=graph_builder._ledger_sink, query=query, initial_state=initial_state)
        result = answer_result(query, run)
        log_knowledge_answer(
            log,
            build_answer_audit(
                query=query,
                answer=result.answer,
                top_k=int(initial_state["top_k"]),
                min_score=float(initial_state["min_score"]),
                filters=filters or {},
                sources=result.sources,
                model_id=result.model_id,
                usage=result.usage,
                elapsed_ms=result.elapsed_ms,
                no_results=result.no_results,
            ),
        )
        return result

    async def compare(
        self,
        query: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
        filters: dict[str, Any] | None = None,
        workspace_id: str | None = None,
        explain: bool = False,
        rewrite: bool = False,
        graph_temporal: str | None = None,
    ) -> "KnowledgeAnswerComparison":
        """L3 — run :meth:`answer` twice (use_graph False/True) **concurrently** and
        return a side-by-side comparison.

        Same query, same filters, same tuning — only ``use_graph`` differs. Used by
        the Ask tab's compare mode (5d). Wall-clock is
        ~max(leg1, leg2), not sum, because both legs run via ``asyncio.gather``.

        ``rewrite=True`` is recommended (graph_expand needs entities from the rewrite
        step); the no-rewrite case is allowed but the graph leg becomes a no-op,
        making the comparison degenerate. A warning is logged when this happens.
        """
        from hiro_memory.knowledge.models import KnowledgeAnswerComparison

        if not rewrite:
            log.warning(
                "⚠️ knowledge.compare — rewrite=False · graph_expand has no entities "
                "to resolve · the 'graph' leg will degrade to flat; consider rewrite=True",
            )
        t0 = time.perf_counter()
        # asyncio.gather preserves order. Both legs use independent agent graphs
        # (each call creates its own KnowledgeAgentGraph in answer()), so there's
        # no shared LangGraph state contention. Qdrant/graph reads are safe to
        # interleave (MVCC under the hood for both).
        flat_result, graph_result = await asyncio.gather(
            self.answer(
                query,
                top_k=top_k,
                min_score=min_score,
                filters=filters,
                workspace_id=workspace_id,
                explain=explain,
                rewrite=rewrite,
                graph_mode="off",
            ),
            self.answer(
                query,
                top_k=top_k,
                min_score=min_score,
                filters=filters,
                workspace_id=workspace_id,
                explain=explain,
                rewrite=rewrite,
                graph_mode="graphiti",
                graph_temporal=graph_temporal,
            ),
        )
        return KnowledgeAnswerComparison(
            query=query,
            flat=flat_result,
            graph=graph_result,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )

    async def list_documents(
        self,
        *,
        status: str | None = None,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        category_id: int | None = None,
        subcategory_id: int | None = None,
        tag: str | None = None,
        source_type: str | None = None,
        title: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> KnowledgeListDocumentsResult:
        return await asyncio.to_thread(
            self.catalog.list_documents,
            status,
            owner_kind,
            owner_id,
            category_id,
            subcategory_id,
            tag,
            source_type,
            title,
            limit,
            offset,
        )

    async def get_chunk_details(self, point_ids: list[str]) -> list[dict[str, Any]]:
        """Resolve chunk point_ids → text + document title for the graph viz panel.

        Two ingest paths write chunks to two stores, so this resolver routes by origin:
          - **Knowledge** ingest writes chunk text to Qdrant (payload.text) AND a graph
            episode to Kuzu. Resolve from Qdrant; Kuzu only supplies ``valid_at``.
          - **Memory** ingest writes ONLY a Graphiti episode to Kuzu (group_id starts
            with ``mem_``). ``EpisodicNode.content`` is the authoritative text — Qdrant
            never saw these ids. Resolve from Kuzu; skip the Qdrant call entirely.

        Routing is determined by reading the episode's ``group_id`` once from Kuzu
        (cheap; we already needed ``valid_at`` from there). The bug this replaces:
        the resolver used to query Qdrant for every id, silently dropping all memory
        chunks → the Graph panel showed "Chunk text unavailable" even though the text
        was right there in ``EpisodicNode.content``.
        """
        from hiro_memory.graph.graphiti_service import (
            graphiti_db_path,
            read_episode_chunks,
        )

        from hirocli.services.knowledge.graph_factory import graph_query_timeout
        from hiro_memory.graph.group_scope import (
            is_kuzu_only_chunk_group_id,
        )

        ids = [str(p) for p in (point_ids or []) if p]
        if not ids:
            return []
        # One Kuzu read covers BOTH legs: text+group_id+valid_at for Kuzu-only (memory)
        # chunks, group_id+valid_at for knowledge chunks (their text still
        # comes from Qdrant).
        episode_by_id = await read_episode_chunks(
            graphiti_db_path(self.workspace_path),
            ids,
            query_timeout_s=graph_query_timeout(self.workspace_path),
        )
        knowledge_ids = [
            pid
            for pid in ids
            if not is_kuzu_only_chunk_group_id(episode_by_id.get(pid, {}).get("group_id", ""))
        ]
        # Only hit Qdrant for ids that aren't memory chunks — saves the round-trip and
        # the misleading "not found in Qdrant" warning for memory ids that were never
        # written there.
        hits_by_id: dict[str, Any] = {}
        if knowledge_ids:
            hits = await asyncio.to_thread(
                self.vector_store.hits_from_point_ids, knowledge_ids
            )
            hits_by_id = {hit.point_id: hit for hit in hits}
            missing = [pid for pid in knowledge_ids if pid not in hits_by_id]
            if missing:
                # Real provenance gap (knowledge chunks the resolver expected but didn't
                # find in Qdrant — e.g. the collection was rebuilt). NOT a memory chunk.
                log.warning(
                    "⚠️ knowledge.graph — %d/%d knowledge chunk id(s) not found in Qdrant "
                    "(collection=%s) · graph provenance may predate a rebuild/reset · sample=%s",
                    len(missing),
                    len(knowledge_ids),
                    self.vector_store.collection_name,
                    missing[:5],
                )
        details: list[dict[str, Any]] = []
        for pid in ids:
            episode = episode_by_id.get(pid, {})
            group_id = str(episode.get("group_id", "") or "")
            valid_at = episode.get("valid_at")
            if is_kuzu_only_chunk_group_id(group_id):
                text = str(episode.get("text", "") or "")
                if not text:
                    continue  # episode exists but has no body — skip
                details.append(
                    {
                        "id": pid,
                        "text": text,
                        # Conversation memory has no Qdrant doc; surface the thread id
                        # (set as ``source_description`` at ingest: "conv:{run_id}") so
                        # the panel can still group + label memory chunks coherently.
                        "document_id": episode.get("source_description") or group_id,
                        "document_title": "Conversation",
                        "ord": None,
                        "heading_path": None,
                        "valid_at": valid_at,
                    }
                )
                continue
            hit = hits_by_id.get(pid)
            if hit is None:
                continue
            details.append(
                {
                    "id": hit.point_id,
                    "text": hit.text,
                    "document_id": hit.document_id,
                    "document_title": hit.title,
                    "ord": hit.ord,
                    "heading_path": hit.heading_path,
                    # Episode event time (ISO) — null when no episode / no temporal date.
                    "valid_at": valid_at,
                }
            )
        return details

    async def search_chunk_ids_by_text(self, text: str, *, limit: int = 200) -> list[str]:
        """Graph viz — chunk-text search → matching Qdrant point_ids (== graph chunk_ids).

        Literal case-insensitive substring scan; the Graph tab maps the returned ids onto
        nodes/edges (via their ``chunk_ids``, G6) to highlight everything sourced from a
        chunk whose text matches. Blank query → ``[]``."""
        return await asyncio.to_thread(
            self.vector_store.point_ids_matching_text, text, limit=limit
        )

    async def list_tags(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.catalog.list_table, "knowledge_tags")

    async def list_categories(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.catalog.list_table, "knowledge_categories")

    async def create_category(self, name: str, *, parent_id: int | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self.catalog.create_category, name, parent_id)

    async def create_tag(self, name: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.catalog.create_tag, name)

    async def delete_document(self, document_id: str) -> dict[str, Any]:
        deleted = await asyncio.to_thread(self.remove_document, document_id)
        if deleted:
            # A document delete must also purge its Graphiti episodes — the catalog row
            # + Qdrant chunks alone leave orphaned entities/facts in the knowledge graph.
            # Best-effort/isolated: a graph failure (graph off, never built, DB lock) must
            # NOT undo the already-committed catalog/Qdrant delete, so we log and move on.
            await self._purge_document_graph(document_id)
            self._publish(KNOWLEDGE_DELETED, {"document_id": document_id})
        return {"document_id": document_id, "deleted": deleted}

    async def _purge_document_graph(self, document_id: str) -> int:
        """Remove a deleted document's episodes from the knowledge graph (best-effort).

        Isolated from the caller: any failure is logged and swallowed so it can't roll
        back the catalog/Qdrant delete that already succeeded. Returns the episode count
        removed (0 when the graph is off, never built, or on error)."""
        # Local import avoids a service ↔ tools import cycle (tools imports this module).
        from hirocli.tools.knowledge_graph import remove_document_from_graph

        try:
            return await remove_document_from_graph(self.workspace_path, document_id)
        except Exception as exc:
            log.warning(
                "⚠️ knowledge graph — document delete left graph untouched · doc_id=%s · %s",
                document_id,
                str(exc)[:200],
                exc_info=True,
            )
            return 0

    async def reingest_document(self, document_id: str) -> KnowledgeJobResult:
        row = await asyncio.to_thread(self.catalog.document_row_by_id, document_id)
        if row is None:
            raise KeyError(f"Unknown knowledge document: {document_id}")
        tags = await asyncio.to_thread(self.catalog.tags_for_document, document_id)
        return await self.start_ingest(
            [row["source_uri"]],
            owner_kind=row["owner_kind"],
            owner_id=row["owner_id"],
            category_id=row["category_id"],
            subcategory_id=row["subcategory_id"],
            tags=tags,
            force_reingest=True,
        )

    async def update_document_metadata(
        self,
        document_id: str,
        *,
        owner_kind: str,
        owner_id: str,
        category_id: int | None = None,
        subcategory_id: int | None = None,
        tags: Sequence[str] | None = None,
    ) -> KnowledgeDocumentRow:
        row = await asyncio.to_thread(
            self._update_document_metadata_sync,
            document_id,
            owner_kind,
            owner_id,
            category_id,
            subcategory_id,
            list(tags or []),
        )
        if row is None:
            raise KeyError(f"Unknown knowledge document: {document_id}")
        tags = await asyncio.to_thread(self.catalog.tags_for_document, document_id)
        return document_from_row(row, tags=tags)

    async def _run_ingest_job_story(self, job_id: str, paths: list[str], params: dict[str, Any]) -> None:
        """The job as a named story of its own (the logging plan's phase 6a): it runs on after the request that
        started it has its answer."""
        from ...runtime import stories

        with stories.started(stories.KNOWLEDGE_INGEST, "knowledge.ingest", area="KNOWLEDGE", own=True,
                             title=f"{len(paths)} files", job_id=job_id):
            await self._run_ingest_job(job_id, paths, params)

    async def _run_ingest_job(self, job_id: str, paths: list[str], params: dict[str, Any]) -> None:
        totals = {"requested": len(paths), "skipped": 0, "ingested": 0, "failed": 0, "chunks": 0}
        errors: dict[str, str] = {}
        in_flight: set[str] = set()
        chunking = KnowledgeChunkingSettings.model_validate(self.workspace_prefs().knowledge.chunking.model_dump())
        state_lock = asyncio.Lock()
        job_t0 = time.perf_counter()
        semaphore = asyncio.Semaphore(
            bounded_file_concurrency(
                params.get("file_concurrency"),
                fallback=default_file_concurrency_for_embedder(self.embedder),
            )
        )

        def publish_progress() -> None:
            self._publish(
                KNOWLEDGE_JOB_PROGRESS,
                {
                    "job_id": job_id,
                    "totals": dict(totals),
                    "errors": dict(errors),
                    "in_flight": sorted(in_flight),
                },
            )

        async def ingest_path(raw_path: str) -> None:
            async with semaphore:
                async with state_lock:
                    in_flight.add(raw_path)
                    publish_progress()
                file_label = Path(raw_path).name or raw_path
                file_t0 = time.perf_counter()
                try:
                    chunks = await self._ingest_one(raw_path, params, chunking=chunking)
                    file_elapsed_ms = int((time.perf_counter() - file_t0) * 1000)
                    async with state_lock:
                        if chunks is None:
                            totals["skipped"] += 1
                        else:
                            totals["ingested"] += 1
                            totals["chunks"] += chunks
                    if chunks is None:
                        log.info(
                            "⚠️ ingest skipped — file=%s · unchanged · %dms",
                            file_label,
                            file_elapsed_ms,
                            path=raw_path,
                        )
                    else:
                        log.info(
                            "✅ ingest — file=%s · chunks=%d · %dms",
                            file_label,
                            chunks,
                            file_elapsed_ms,
                            path=raw_path,
                        )
                except Exception as exc:
                    file_elapsed_ms = int((time.perf_counter() - file_t0) * 1000)
                    async with state_lock:
                        totals["failed"] += 1
                        errors[raw_path] = str(exc)
                    log.error(
                        "❌ ingest failed — file=%s · %dms · %s",
                        file_label,
                        file_elapsed_ms,
                        str(exc)[:80],
                        path=raw_path,
                        error=str(exc),
                        exc_info=True,
                    )
                async with state_lock:
                    in_flight.discard(raw_path)
                    await asyncio.to_thread(self.catalog.update_job, job_id, "running", totals, errors)
                    publish_progress()

        try:
            await asyncio.gather(*(ingest_path(raw_path) for raw_path in paths))
            status = "failed" if totals["failed"] and not totals["ingested"] else "completed"
            await asyncio.to_thread(self.catalog.finish_job, job_id, status, totals, errors)
            self._publish(
                KNOWLEDGE_JOB_COMPLETED if status == "completed" else KNOWLEDGE_JOB_FAILED,
                {"job_id": job_id, "totals": totals, "errors": errors},
            )
            log_knowledge_ingest(
                log,
                build_ingest_audit(
                    job_id=job_id,
                    status=status,
                    totals=totals,
                    errors=errors,
                    params=params,
                    elapsed_ms=int((time.perf_counter() - job_t0) * 1000),
                ),
            )
        except Exception as exc:
            errors["job"] = str(exc)
            await asyncio.to_thread(self.catalog.finish_job, job_id, "failed", totals, errors)
            self._publish(KNOWLEDGE_JOB_FAILED, {"job_id": job_id, "totals": totals, "errors": errors})
            log_knowledge_ingest(
                log,
                build_ingest_audit(
                    job_id=job_id,
                    status="failed",
                    totals=totals,
                    errors=errors,
                    params=params,
                    elapsed_ms=int((time.perf_counter() - job_t0) * 1000),
                ),
            )
            raise

    async def _ingest_one(
        self,
        raw_path: str,
        params: dict[str, Any],
        *,
        chunking: KnowledgeChunkingSettings,
    ) -> int | None:
        return await self.ingest_file(
            raw_path,
            params,
            chunking=chunking,
            max_file_size_bytes=MAX_FILE_SIZE_BYTES,
            on_ingested=lambda document_id, source_uri: self._publish(
                KNOWLEDGE_INGESTED, {"document_id": document_id, "source_uri": source_uri}
            ),
        )

    def _update_document_metadata_sync(
        self,
        document_id: str,
        owner_kind: str,
        owner_id: str,
        category_id: int | None,
        subcategory_id: int | None,
        tags: Sequence[str],
    ) -> sqlite3.Row | None:
        row = self.catalog.update_document_metadata(
            document_id,
            owner_kind,
            owner_id,
            category_id,
            subcategory_id,
            tags,
        )
        if row is None:
            return None
        clean_tags = self.catalog.ensure_tags(tags)
        self.vector_store.sync_payload_metadata(
            document_id,
            owner_kind=owner_kind or "system",
            owner_id=owner_id or "0",
            category_id=category_id,
            subcategory_id=subcategory_id,
            tags=clean_tags,
        )
        return row

    def _insert_job(
        self,
        job_id: str,
        status: str,
        totals: dict[str, int],
        errors: dict[str, str],
        params: dict[str, Any],
    ) -> None:
        self.catalog.insert_job(job_id, status, totals, errors, params, owner_token=self.owner_token)

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        get_domain_event_bus().publish(
            DomainEvent(type=event_type, workspace_path=self.workspace_path, payload=payload)
        )
