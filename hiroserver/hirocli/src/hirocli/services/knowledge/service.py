"""Workspace-local knowledge service for markdown ingest and vector search."""

from __future__ import annotations

import asyncio
import hashlib
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

from hiro_commons.log import Logger
from qdrant_client import models as qm

from hirocli.domain.events import DomainEvent, get_domain_event_bus
from hirocli.domain.preferences import load_preferences

if TYPE_CHECKING:
    from hirocli.domain.preferences import KnowledgeChunkingPreferences, WorkspacePreferences
from hirocli.runtime.agent_graph.ledger import current_run
from hirocli.services.knowledge.agent import KnowledgeAgentGraph, build_qdrant_filter
from hirocli.services.knowledge.audit_log import (
    build_answer_audit,
    build_ingest_audit,
    build_search_audit,
    log_knowledge_answer,
    log_knowledge_ingest,
    log_knowledge_search,
)
from hirocli.services.knowledge.ledger_runner import (
    finalize_standalone_run,
    knowledge_answer_ledger,
    ledger_identity_from_parent,
)
from hirocli.services.knowledge.catalog_store import CatalogStore
from hirocli.services.knowledge.chunker import embed_text_for_chunk
from hirocli.services.knowledge.constants import (
    DB_FILENAME,
    DEFAULT_FILE_CONCURRENCY,
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
from hirocli.services.knowledge.converters import (
    bounded_file_concurrency,
    default_file_concurrency_for_embedder,
    document_from_row,
    job_from_row,
    utc_now_iso,
)
from hirocli.services.knowledge.embedding_backends import (
    EmbeddingBackend,
    SparseEmbeddingBackend,
    SparseVectorData,
)
from hirocli.services.knowledge.live_registry import register_live_service, unregister_live_service
from hirocli.services.knowledge.runtime_owner import current_owner_token
from hirocli.services.knowledge.loaders import DEFAULT_LOADER_REGISTRY, LoaderRegistry
from hirocli.services.knowledge.models import (
    KnowledgeAnswerResult,
    KnowledgeDocumentDetailResult,
    KnowledgeDocumentRow,
    KnowledgeJobResult,
    KnowledgeListDocumentsResult,
    KnowledgeListJobsResult,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    ScanFolderResult,
)
from hirocli.services.knowledge.preview import FilePreviewResult, read_file_preview
from hirocli.services.knowledge.scanner import SourceScanner
from hirocli.services.knowledge.vector_store import KnowledgeVectorStore

log = Logger.get("SVC.KNOWLEDGE")


@dataclass
class _RerankerDownloadJob:
    """A running local-reranker download (a killable subprocess + progress baseline)."""

    process: subprocess.Popen  # the download subprocess
    baseline_bytes: int  # cache size at start; progress = (current - baseline) / expected
    expected_bytes: int  # approximate total from the model's size label
    cancelled: bool = False


class KnowledgeService:
    """Phase 1 knowledge service: scan, ingest markdown, search, browse chunks."""

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
        self.knowledge_path = self.workspace_path / KNOWLEDGE_DIR
        self.db_path = self.knowledge_path / DB_FILENAME
        self.qdrant_path = self.knowledge_path / QDRANT_DIR
        self.embedder = embedder or self._default_embedder_for_workspace()
        # BM25 sparse backend for hybrid retrieval — local and independent of the dense model.
        self.sparse_embedder = sparse_embedder or self._default_sparse_embedder_for_workspace()
        self.loader_registry = loader_registry or DEFAULT_LOADER_REGISTRY
        self.catalog = CatalogStore(self.db_path)
        self.vector_store = KnowledgeVectorStore(self.qdrant_path, self.embedder)
        self.scanner = SourceScanner(self.loader_registry, self.catalog)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._uri_locks: dict[str, asyncio.Lock] = {}
        # Cached reranker compressor (model load is expensive — keyed by model/top_n/device).
        self._reranker_key: tuple[str, int, str] | None = None
        self._reranker_compressor: Any | None = None
        self._reranker_calibrated: bool = True
        # In-flight local-reranker downloads (killable spawn processes), keyed by model_id, and
        # terminal error messages for the last failed download. The downloaded marker is the
        # source of truth for "ready". Surfaced via reranker_options() for the admin poll.
        self._reranker_jobs: dict[str, _RerankerDownloadJob] = {}
        self._reranker_errors: dict[str, str] = {}
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
        from hirocli.services.knowledge.embedder import resolve_knowledge_embedder

        prefs = self.workspace_prefs()
        return resolve_knowledge_embedder(
            self.workspace_path,
            prefs.knowledge.default_embedding_model_resolved,
        )

    def _default_sparse_embedder_for_workspace(self) -> SparseEmbeddingBackend:
        from hirocli.services.knowledge.embedder import resolve_knowledge_sparse_embedder

        prefs = self.workspace_prefs()
        return resolve_knowledge_sparse_embedder(
            self.workspace_path,
            prefs.knowledge.retrieval.sparse_model,
        )

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
        # Terminate any in-flight reranker download processes so they don't outlive the service.
        for model_id in list(self._reranker_jobs):
            self.cancel_reranker_download(model_id)
        self.vector_store.close()
        unregister_live_service(self)

    async def scan_folder(self, folder: str, *, recursive: bool = True) -> ScanFolderResult:
        root = Path(folder).expanduser().resolve()
        if not root.exists() or not root.is_dir():
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
        clean_paths = [str(Path(p).expanduser().resolve()) for p in paths if str(p).strip()]
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
        from hirocli.services.knowledge.reranker import rerank_hits as _rerank_hits
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
            [sys.executable, "-m", "hirocli.services.knowledge.download_entry", model_id, str(cache)],
        )
        self._reranker_jobs[model_id] = _RerankerDownloadJob(
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
        use_graph: bool = False,
    ) -> KnowledgeAnswerResult:
        prefs = self.workspace_prefs()
        retrieval = prefs.knowledge.retrieval
        graph_builder = KnowledgeAgentGraph(
            workspace_path=self.workspace_path,
            service=self,
            prefs=prefs,
            workspace_id=workspace_id,
        )
        graph = graph_builder.build()
        # L3 — use_graph=True turns on the graph_expand node. Useful only when
        # rewrite=True too (the rewrite step is what extracts query entities for
        # the graph). use_graph=True with rewrite=False is a no-op + a warning.
        if use_graph and not rewrite:
            log.warning(
                "⚠️ knowledge.answer — use_graph=True without rewrite=True · "
                "graph_expand needs entities from rewrite_query · effectively off"
            )
        initial_state: dict[str, Any] = {
            "query": query,
            "filters": filters or {},
            "top_k": top_k if top_k is not None else retrieval.top_k,
            "min_score": min_score if min_score is not None else retrieval.min_score,
            "explain": explain,
            "rewrite": rewrite,
            "use_graph": use_graph,
        }
        parent = current_run.get()
        if parent is not None:
            initial_state.update(ledger_identity_from_parent(parent))

        terminal_status = "completed"
        terminal_error = ""
        state: dict[str, Any] = {}
        ledger_run_id: str | None = None
        async with knowledge_answer_ledger(
            sink=graph_builder._ledger_sink,
            query=query,
        ) as ledger_run:
            ledger_run_id = ledger_run.run_id
            try:
                state = await graph.ainvoke(
                    initial_state,
                    config=ledger_run.runnable_config,
                )
            except asyncio.CancelledError:
                terminal_status = "cancelled"
                terminal_error = "cancelled"
                raise
            except Exception as exc:
                terminal_status = "failed"
                terminal_error = str(exc)[:80]
                log.error(
                    "❌ knowledge answer graph failed",
                    error=str(exc),
                    exc_info=True,
                )
                raise
            finally:
                if ledger_run.accumulator is not None:
                    finalize_standalone_run(
                        ledger_run.accumulator,
                        query=query,
                        answer=str(state.get("answer") or ""),
                        no_results=bool(state.get("no_results")),
                        status=terminal_status,
                        error_code=terminal_error,
                    )
        result = KnowledgeAnswerResult(
            query=query,
            answer=str(state.get("answer") or ""),
            sources=list(state.get("sources") or []),
            elapsed_ms=int(state.get("elapsed_ms") or 0),
            model_id=state.get("model_id"),
            usage=dict(state.get("usage") or {}),
            no_results=bool(state.get("no_results")),
            run_id=ledger_run_id,
            rewritten_query=state.get("rewritten_query"),
            keywords=list(state.get("rewrite_keywords") or []),
        )
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
    ) -> "KnowledgeAnswerComparison":
        """L3 — run :meth:`answer` twice (use_graph False/True) **concurrently** and
        return a side-by-side comparison.

        Same query, same filters, same tuning — only ``use_graph`` differs. Used by
        the Ask tab's compare mode (5d) and by the L3 eval batch (5e). Wall-clock is
        ~max(leg1, leg2), not sum, because both legs run via ``asyncio.gather``.

        ``rewrite=True`` is recommended (graph_expand needs entities from the rewrite
        step); the no-rewrite case is allowed but the graph leg becomes a no-op,
        making the comparison degenerate. A warning is logged when this happens.
        """
        from hirocli.services.knowledge.models import KnowledgeAnswerComparison

        if not rewrite:
            log.warning(
                "⚠️ knowledge.compare — rewrite=False · graph_expand has no entities "
                "to resolve · the 'graph' leg will degrade to flat; consider rewrite=True",
            )
        t0 = time.perf_counter()
        # asyncio.gather preserves order. Both legs use independent agent graphs
        # (each call creates its own KnowledgeAgentGraph in answer()), so there's
        # no shared LangGraph state contention. Qdrant/Ladybug reads are safe to
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
                use_graph=False,
            ),
            self.answer(
                query,
                top_k=top_k,
                min_score=min_score,
                filters=filters,
                workspace_id=workspace_id,
                explain=explain,
                rewrite=rewrite,
                use_graph=True,
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

    async def list_tags(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.catalog.list_table, "knowledge_tags")

    async def list_categories(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.catalog.list_table, "knowledge_categories")

    async def create_category(self, name: str, *, parent_id: int | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self.catalog.create_category, name, parent_id)

    async def create_tag(self, name: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.catalog.create_tag, name)

    async def delete_document(self, document_id: str) -> dict[str, Any]:
        deleted = await asyncio.to_thread(self._delete_document_sync, document_id)
        if deleted:
            self._publish(KNOWLEDGE_DELETED, {"document_id": document_id})
        return {"document_id": document_id, "deleted": deleted}

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

    async def _run_ingest_job(self, job_id: str, paths: list[str], params: dict[str, Any]) -> None:
        totals = {"requested": len(paths), "skipped": 0, "ingested": 0, "failed": 0, "chunks": 0}
        errors: dict[str, str] = {}
        in_flight: set[str] = set()
        chunking = self.workspace_prefs().knowledge.chunking
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
        chunking: KnowledgeChunkingPreferences,
    ) -> int | None:
        path = Path(raw_path).expanduser().resolve()
        loader = self.loader_registry.resolve(path.suffix.lower())
        if loader is None:
            raise ValueError(f"Unsupported file extension: {path.suffix}")
        lock = self._uri_locks.setdefault(str(path), asyncio.Lock())
        async with lock:
            size_bytes = await asyncio.to_thread(lambda: path.stat().st_size)
            if size_bytes > MAX_FILE_SIZE_BYTES:
                raise ValueError(
                    f"File exceeds maximum knowledge ingest size "
                    f"({size_bytes} bytes > {MAX_FILE_SIZE_BYTES} bytes): {path}"
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
                    self._publish(KNOWLEDGE_INGESTED, {"document_id": document_id, "source_uri": str(path)})
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
                    self._upsert_document_and_vectors,
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
            self._publish(KNOWLEDGE_INGESTED, {"document_id": document_id, "source_uri": str(path)})
            return len(chunks)

    def _upsert_document_and_vectors(
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

    def _delete_document_sync(self, document_id: str) -> bool:
        if not self.catalog.delete_document_row(document_id):
            return False
        self.vector_store.delete_document(document_id)
        return True

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
