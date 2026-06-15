"""Admin routes for workspace-local knowledge ingest/search/browse."""

from __future__ import annotations

import asyncio
import functools
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from hiro_commons.log import Logger

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import envelope_failure
from hirocli.admin_svelte.workspace_ctx import _selected_workspace_id
from hirocli.domain.character import list_characters_detailed
from hirocli.domain.data_store import data_db_path, ensure_data_db
from hirocli.domain.events import DomainEvent, get_domain_event_bus
from hirocli.services.knowledge.graph.graph_events import publish_graph_event
from hirocli.domain.workspace import resolve_workspace
from hirocli.services.knowledge import KnowledgeService, create_knowledge_service
from hirocli.services.knowledge.constants import (
    KNOWLEDGE_DELETED,
    KNOWLEDGE_EVAL_CANCELLED,
    KNOWLEDGE_EVAL_COMPLETED,
    KNOWLEDGE_EVAL_FAILED,
    KNOWLEDGE_EVAL_QUESTION_COMPLETED,
    KNOWLEDGE_EVAL_SETUP_PROGRESS,
    KNOWLEDGE_EVAL_STARTED,
    KNOWLEDGE_GRAPH_EDGE_UPSERTED,
    KNOWLEDGE_GRAPH_INGEST_COMPLETED,
    KNOWLEDGE_GRAPH_INGEST_PROGRESS,
    KNOWLEDGE_GRAPH_NODE_UPSERTED,
    KNOWLEDGE_INGESTED,
    KNOWLEDGE_JOB_COMPLETED,
    KNOWLEDGE_JOB_FAILED,
    KNOWLEDGE_JOB_PROGRESS,
    KNOWLEDGE_JOB_STARTED,
)
from hirocli.services.knowledge.graph.group_scope import KNOWLEDGE_GROUP_ID
from hirocli.services.knowledge.live_registry import maybe_recover_abandoned_work

log = Logger.get("ADMIN.KNOWLEDGE")

knowledge_router = APIRouter()

# Process-wide count of OPEN ``/knowledge/events`` SSE streams. After the frontend
# multiplexer change each browser tab on the Knowledge page holds exactly ONE such stream
# (not one per feature). Logged on connect/disconnect so a later run shows (a) how many
# live streams are open during an ingest/eval — the "connection budget" the admin keeps
# hitting — and (b) whether a stream is even connected while a graph build emits deltas
# (the live-updates question). Mutated only on the single server event loop → plain int.
_active_sse_streams = 0


def _success(data: Any) -> dict[str, Any]:
    return {"ok": True, "error": None, "data": data}


def _publish_graph_event(
    workspace_path: Path, event_type: str, payload: dict[str, Any]
) -> None:
    """Publish a graph-viz Domain Event (workspace-scoped). Module-level so the
    ingest ``event_sink`` can be ``functools.partial(_publish_graph_event, ws)``
    — no nested closure. Delegates to the shared publisher so knowledge ingest and the
    conversation-memory facade emit live deltas through one path."""
    publish_graph_event(workspace_path, event_type, payload)


def _live_knowledge_service(request: Request, workspace_path: Path) -> tuple[bool, KnowledgeService | None]:
    state = getattr(getattr(request, "app", None), "state", None)
    ctx = getattr(state, "ctx", None)
    ctx_workspace_path = getattr(ctx, "workspace_path", None)
    if ctx_workspace_path is None:
        return False, None
    try:
        is_live_workspace = Path(ctx_workspace_path).resolve() == workspace_path.resolve()
    except OSError:
        is_live_workspace = Path(ctx_workspace_path) == workspace_path
    if not is_live_workspace:
        return False, None
    manager = getattr(ctx, "knowledge_manager", None)
    if manager is None:
        return True, None
    return True, manager.service


async def _resolve_service(
    request: Request,
    workspace_id: str | None,
) -> tuple[KnowledgeService, bool]:
    entry, _ = resolve_workspace(workspace_id)
    workspace_path = Path(entry.path)
    is_live_workspace, service = _live_knowledge_service(request, workspace_path)
    if is_live_workspace and service is not None:
        return service, False
    return create_knowledge_service(workspace_path), True


async def _close_if_owned(service: KnowledgeService, owned: bool) -> None:
    if owned:
        await service.close()


class ScanFolderBody(BaseModel):
    folder: str
    recursive: bool = True


class PreviewFileBody(BaseModel):
    path: str


class IngestBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    owner_kind: str = "system"
    owner_id: str = "0"
    category_id: int | None = None
    subcategory_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    wait: bool = False

    @model_validator(mode="after")
    def subcategory_requires_category(self) -> IngestBody:
        if self.subcategory_id is not None and self.category_id is None:
            raise ValueError("subcategory_id requires category_id.")
        return self


class SearchBody(BaseModel):
    query: str
    top_k: int = 10
    min_score: float = 0.0
    filters: dict[str, Any] = Field(default_factory=dict)
    # Opt-in: return per-branch (cosine / BM25) scores and matched terms for human evaluation.
    explain: bool = False


class AnswerBody(SearchBody):
    # Opt-in: run the LLM query-rewrite step (normalize + keyword-extract) before retrieval.
    rewrite: bool = False
    # L3 retrieval mode (Phase 5d): 'off' = today's flat hybrid+rerank,
    # 'on' = graph_expand focuses Qdrant on chunks linked to query entities,
    # 'compare' = run both concurrently and return both legs side-by-side.
    graph_mode: str = "off"
    # Per-query temporal lens override (§7). None = use the admin pref
    # ``knowledge.graph.temporal_default``; 'current' = facts valid now only;
    # 'all' = include superseded/historical facts.
    graph_temporal: str | None = None

    @model_validator(mode="after")
    def _validate_graph_mode(self) -> AnswerBody:
        if self.graph_mode not in ("off", "on", "compare"):
            raise ValueError(
                f"graph_mode must be 'off', 'on', or 'compare', got {self.graph_mode!r}"
            )
        if self.graph_temporal is not None and self.graph_temporal not in ("current", "all"):
            raise ValueError(
                f"graph_temporal must be 'current', 'all', or null, got {self.graph_temporal!r}"
            )
        return self


class DownloadRerankerBody(BaseModel):
    model_id: str


class CreateCategoryBody(BaseModel):
    name: str
    parent_id: int | None = None


class CreateTagBody(BaseModel):
    name: str


class EvalRunBody(BaseModel):
    """L3 (Phase 5e) — request body for ``POST /knowledge/eval/run``.

    The eval runs in the background; the response returns the ``run_id``
    immediately, and progress events stream out on ``/knowledge/events``."""

    # Eval track (docs/eval-corpus-tracks-design.md): "knowledge" (document/chunk corpus →
    # ingest+retrieval) or "memory" (turn corpus → conversation remember/recall, eval_mem_{set}).
    track: str = "knowledge"
    # Chosen corpus (from the corpus picker): the id doubles as the eval drawer suffix
    # (eval_mem_{id} / eval_kb_{id}); corpus_path is the .episodes.jsonl file (memory) or the
    # folder of .md docs (knowledge); questions_path is the paired <id>.questions.yaml.
    corpus_id: str = ""
    corpus_path: str = ""
    questions_path: str = ""
    # Remember the turn corpus (memory) / ingest the doc corpus (knowledge) before running.
    ingest_synthetic: bool = False
    build_graph: bool = False  # knowledge only
    # Memory track — explicitly wipe the eval graph BEFORE remembering. Decoupled from
    # ``ingest_synthetic`` so a corpus can be built across appended batches without each batch
    # wiping the last; set it only for a from-scratch rebuild (first batch). Default off ⇒ the
    # graph is never cleared implicitly.
    clear_before: bool = False
    # Memory track — episode batch window for the remember phase: start index + max count into
    # the (chronologically sorted) corpus. 0 / None = from the start / to the end. Lets a large
    # corpus be remembered in monitored chunks. Ignored on the knowledge track.
    episode_offset: int = 0
    episode_limit: int | None = None
    # Optional LLM judge step: grade the model's answer against the ideal answer. When off, the
    # eval generates answers but assigns no marks (and no PROCEED/PIVOT gate).
    judge: bool = False
    # Memory track — max questions running their recall→answer→judge legs at once (1 = serial).
    # Clamped server-side to [1, MAX_QUESTION_CONCURRENCY] rather than 422-ing an out-of-range
    # value. Ignored on the knowledge track (its leg loop is still serial — named follow-up).
    question_concurrency: int = 1
    # Selected question ids — REQUIRED and non-empty (the UI forces an explicit selection;
    # there is no implicit "run all").
    question_ids: list[str] | None = None
    # Knowledge track only — legs to compare, subset of ["flat", "graphiti"] (one is fine).
    # None/empty = both. Normalized server-side. Ignored on the memory track (single recall leg).
    modes: list[str] | None = None
    run_id: str | None = None


class GraphIngestBatchBody(BaseModel):
    """L3 (Phase 5f) — request body for ``POST /knowledge/graph/ingest_batch``.

    Synchronous: the response waits for the whole batch to complete (per-doc
    failure isolation means one bad doc never aborts the rest). For a long
    batch the caller blocks for minutes; that's acceptable for the Tab 1
    "also build graph after ingest" path where the user is already watching
    the ingest progress."""

    document_ids: list[str] = Field(default_factory=list)
    source_role: str = "user_document"


class UpdateMetadataBody(BaseModel):
    owner_kind: str = "system"
    owner_id: str = "0"
    category_id: int | None = None
    subcategory_id: int | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def subcategory_requires_category(self) -> UpdateMetadataBody:
        if self.subcategory_id is not None and self.category_id is None:
            raise ValueError("subcategory_id requires category_id.")
        return self


def _list_users(workspace_path: Path) -> list[dict[str, Any]]:
    ensure_data_db(workspace_path)
    with sqlite3.connect(str(data_db_path(workspace_path))) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT id, name, created_at FROM users ORDER BY name").fetchall()
        return [dict(row) for row in rows]


def _pick_folder_dialog(initial_folder: str | None = None) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            initialdir=initial_folder or None,
            title="Select knowledge folder",
            mustexist=True,
        )
        return selected or None
    finally:
        root.destroy()


@knowledge_router.post("/knowledge/scan-folder")
async def scan_folder(
    body: ScanFolderBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(await service.scan_folder(body.folder, recursive=body.recursive))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge scan failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/preview-file")
async def preview_file(
    body: PreviewFileBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            result = await service.preview_file(body.path)
            return _success(result.__dict__)
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge file preview failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/options")
async def options(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        service, owned = await _resolve_service(request, workspace_id)
        try:
            categories, tags, characters, users = await asyncio.gather(
                service.list_categories(),
                service.list_tags(),
                run_in_threadpool(list_characters_detailed, workspace_path),
                run_in_threadpool(_list_users, workspace_path),
            )
            prefs = service.workspace_prefs()
            return _success(
                {
                    "categories": categories,
                    "tags": tags,
                    "characters": [
                        {"id": row.get("id"), "name": row.get("name") or row.get("id")}
                        for row in characters
                    ],
                    "users": users,
                    "rewrite_default_on": prefs.knowledge.rewrite.default_on,
                }
            )
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge options failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/rerankers")
async def list_rerankers(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Local reranker registry rows with per-model download status.

    Cloud rerankers come from the catalog (``/catalog/models?model_kind=rerank``); the admin
    picker merges the two sources.
    """
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success({"local": service.reranker_options()})
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge list rerankers failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/rerankers/download")
async def download_reranker(
    body: DownloadRerankerBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Download a local reranker's weights (no model is fetched silently).

    On the live workspace the download runs in the background and returns immediately with
    ``status: downloading`` — the UI polls ``GET /knowledge/rerankers`` for the live transition
    to ``ready`` / ``error``. For a short-lived (owned) service the task would not outlive the
    request, so it falls back to a blocking download.
    """
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            if owned:
                return _success(await service.download_reranker(body.model_id))
            return _success(service.start_reranker_download(body.model_id))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error(
            "knowledge reranker download failed",
            model_id=body.model_id,
            error=str(exc),
            exc_info=True,
        )
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/rerankers/cancel")
async def cancel_reranker_download(
    body: DownloadRerankerBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Cancel an in-flight local-reranker download (terminates the download process)."""
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            if owned:
                return _success({"model_id": body.model_id, "status": "available"})
            return _success(service.cancel_reranker_download(body.model_id))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error(
            "knowledge reranker cancel failed",
            model_id=body.model_id,
            error=str(exc),
            exc_info=True,
        )
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/pick-folder")
async def pick_folder(body: dict[str, str | None]) -> dict[str, Any]:
    try:
        folder = await run_in_threadpool(_pick_folder_dialog, body.get("initial_folder"))
        return _success({"folder": folder})
    except Exception as exc:
        log.error("knowledge folder picker failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/ingest")
async def ingest(
    body: IngestBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            wait = body.wait or owned
            kwargs = {
                "owner_kind": body.owner_kind or "system",
                "owner_id": body.owner_id or "0",
                "category_id": body.category_id,
                "subcategory_id": body.subcategory_id,
                "tags": body.tags,
            }
            maybe_recover_abandoned_work(service.workspace_path)
            result = (
                await service.ingest_and_wait(body.paths, **kwargs)
                if wait
                else await service.start_ingest(body.paths, **kwargs)
            )
            return _success(result)
        finally:
            if owned:
                await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge ingest failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/categories")
async def create_category(
    body: CreateCategoryBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(await service.create_category(body.name, parent_id=body.parent_id))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge create category failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/tags")
async def create_tag(
    body: CreateTagBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(await service.create_tag(body.name))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge create tag failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/jobs")
async def list_jobs(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
    limit: int = 20,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(await service.list_jobs(limit=limit))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge list jobs failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/jobs/{job_id}")
async def job_status(
    job_id: str,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(await service.job_status(job_id))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge job status failed", job_id=job_id, error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/events")
async def stream_knowledge_events(
    request: Request,
    workspace: str | None = None,
) -> StreamingResponse:
    selected_workspace_id = _selected_workspace_id(workspace)
    entry, _ = resolve_workspace(selected_workspace_id)
    workspace_path = Path(entry.path).resolve()
    event_types = (
        KNOWLEDGE_JOB_STARTED,
        KNOWLEDGE_JOB_PROGRESS,
        KNOWLEDGE_JOB_COMPLETED,
        KNOWLEDGE_JOB_FAILED,
        KNOWLEDGE_INGESTED,
        KNOWLEDGE_DELETED,
        # L3 eval batch (Phase 5c) — same SSE stream, separate event types
        # so the UI subscriber can dispatch on event.type.
        KNOWLEDGE_EVAL_STARTED,
        KNOWLEDGE_EVAL_SETUP_PROGRESS,
        KNOWLEDGE_EVAL_QUESTION_COMPLETED,
        KNOWLEDGE_EVAL_COMPLETED,
        KNOWLEDGE_EVAL_FAILED,
        KNOWLEDGE_EVAL_CANCELLED,
        # L3 graph viz (MVP) — live node/edge updates for the admin Graph tab.
        KNOWLEDGE_GRAPH_NODE_UPSERTED,
        KNOWLEDGE_GRAPH_EDGE_UPSERTED,
        KNOWLEDGE_GRAPH_INGEST_PROGRESS,
        KNOWLEDGE_GRAPH_INGEST_COMPLETED,
    )

    async def events():
        queue: asyncio.Queue[DomainEvent] = asyncio.Queue(maxsize=100)

        async def handler(event: DomainEvent) -> None:
            try:
                if Path(event.workspace_path).resolve() != workspace_path:
                    return
            except OSError:
                if Path(event.workspace_path) != workspace_path:
                    return
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("knowledge event stream queue full", event_type=event.type)

        global _active_sse_streams
        bus = get_domain_event_bus()
        for event_type in event_types:
            bus.subscribe(event_type, handler)
        # Per-stream delivery tally (per event type) so the disconnect log shows what this
        # connection actually carried — e.g. did it deliver knowledge.graph.* deltas?
        delivered: dict[str, int] = {}
        client = getattr(request.client, "host", "?")
        _active_sse_streams += 1
        log.fineinfo(
            "🔌 SSE connect — knowledge events · active=%d · ws=%s · client=%s",
            _active_sse_streams,
            workspace_path.name,
            client,
        )
        try:
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(event.payload, separators=(",", ":"))
                delivered[event.type] = delivered.get(event.type, 0) + 1
                yield f"event: {event.type}\ndata: {payload}\n\n"
        except asyncio.CancelledError:
            return
        finally:
            for event_type in event_types:
                bus.unsubscribe(event_type, handler)
            _active_sse_streams -= 1
            # `delivered` summarizes the whole stream lifetime — graph.* counts here being
            # 0 during a build that ran means no consumer was attached for those deltas.
            log.fineinfo(
                "🔌 SSE disconnect — knowledge events · active=%d · ws=%s · delivered=%s",
                _active_sse_streams,
                workspace_path.name,
                delivered or "{}",
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@knowledge_router.post("/knowledge/search")
async def search(
    body: SearchBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(
                await service.search(
                    body.query,
                    top_k=body.top_k,
                    min_score=body.min_score,
                    filters=body.filters,
                    explain=body.explain,
                )
            )
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge search failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/answer")
async def answer(
    body: AnswerBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    # Two response shapes:
    #  * graph_mode=off/on  → KnowledgeAnswerResult (today's shape)
    #  * graph_mode=compare → KnowledgeAnswerComparison { query, flat, graph,
    #                          elapsed_ms, sources_delta, both_no_results }
    # The frontend discriminates on the presence of `flat`/`graph` keys.
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            if body.graph_mode == "compare":
                comparison = await service.compare(
                    body.query,
                    top_k=body.top_k,
                    min_score=body.min_score,
                    filters=body.filters,
                    workspace_id=workspace_id,
                    explain=body.explain,
                    rewrite=body.rewrite,
                    graph_temporal=body.graph_temporal,
                )
                # Serialize manually: KnowledgeAnswerComparison's helpers
                # (sources_delta / both_no_results) are @properties and
                # wouldn't survive dataclass auto-serialization.
                return _success(
                    {
                        "query": comparison.query,
                        "flat": comparison.flat,
                        "graph": comparison.graph,
                        "elapsed_ms": comparison.elapsed_ms,
                        "sources_delta": comparison.sources_delta,
                        "both_no_results": comparison.both_no_results,
                    }
                )
            return _success(
                await service.answer(
                    body.query,
                    top_k=body.top_k,
                    min_score=body.min_score,
                    filters=body.filters,
                    workspace_id=workspace_id,
                    explain=body.explain,
                    rewrite=body.rewrite,
                    # Ask tab keeps its off/on toggle; "on" maps to the graphiti leg
                    # (graph facts + their by-id passages). The single-answer Ask path
                    # has no leg selector — that lives in the eval batch.
                    graph_mode=("graphiti" if body.graph_mode == "on" else "off"),
                    graph_temporal=body.graph_temporal,
                )
            )
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge answer failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/graph/ingest_batch")
async def graph_ingest_batch(
    body: GraphIngestBatchBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """L3 (Phase 5f) — graph-ingest N already-Qdrant-ingested documents.

    Used by Tab 1's "Also build entity graph (L3)" checkbox: after a regular
    ingest job completes, the frontend POSTs the freshly-ingested doc_ids here
    to extract entities/relations into the knowledge graph. Per-document failure
    isolation; aggregated totals returned.
    """
    from hirocli.tools.knowledge_graph import _run_graph_ingest_for_documents

    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            # Defensive dedupe (matches the Tool's behavior — callers iterating
            # over uploaded paths may pass duplicates from race conditions).
            deduped: list[str] = []
            seen: set[str] = set()
            for did in body.document_ids:
                did_clean = (did or "").strip()
                if did_clean and did_clean not in seen:
                    seen.add(did_clean)
                    deduped.append(did_clean)
            result = await _run_graph_ingest_for_documents(
                service,
                service.workspace_path,
                deduped,
                source_role=body.source_role,
                # Live viz: emit per-node/edge events so the Graph tab pops new
                # elements while this ingest runs (graph viz MVP).
                event_sink=functools.partial(
                    _publish_graph_event, service.workspace_path
                ),
            )
            # Burst is over — let the Graph tab run one reconciling full export
            # to heal any deltas dropped under the SSE queue cap.
            _publish_graph_event(
                service.workspace_path,
                KNOWLEDGE_GRAPH_INGEST_COMPLETED,
                {
                    "document_count": result.get("document_count", 0),
                    "totals": result.get("totals", {}),
                    # Scope the completion to the partition that was written (knowledge docs land
                    # in the default kb_main group) so the Graph tab only clears/reconciles when
                    # it's viewing that group — matches the group_id carried on ingest_progress.
                    "group_id": KNOWLEDGE_GROUP_ID,
                },
            )
            return _success(result)
        finally:
            if owned:
                await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge graph ingest batch failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


class GraphExportBody(BaseModel):
    """Graph export request. ``node_types`` / ``document_id`` are reserved for
    the Phase 2 filters and ignored in the MVP; the limits are safety caps.
    ``group_ids`` selects the partition (default knowledge group, or a
    ``mem_{user}_{character}`` conversation-memory group)."""

    node_types: list[str] | None = None
    document_id: str | None = None
    node_limit: int | None = None
    edge_limit: int | None = None
    group_ids: list[str] | None = None


class GraphChunksDetailBody(BaseModel):
    """Graph viz — resolve a selected node/edge's provenance chunk_ids to text."""

    chunk_ids: list[str] = []


class GraphSearchChunksBody(BaseModel):
    """Graph viz — chunk-text search: find point_ids whose chunk text matches ``text``."""

    text: str = ""
    limit: int = 200


@knowledge_router.post("/knowledge/graph/export")
async def graph_export(
    body: GraphExportBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Graph viz — whole-graph export, the Graph tab's load path.

    Read-only and independent of Qdrant: resolves the workspace path and returns
    all entity nodes + RELATES_TO facts from the Graphiti (Kuzu) graph. Empty graph
    when none built yet.
    """
    from hirocli.services.knowledge.graph.group_scope import GroupPolicyError, validate_group_id
    from hirocli.tools.knowledge_graph import graph_snapshot_payload

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path).resolve()
        # API-boundary scope guard (docs/graph-group-policy-design.md §6): never trust a raw
        # client group_id. Re-validate each against the firm grammar so a crafted/empty group
        # can't trigger an all-groups scan or read a non-namespaced partition. This is the
        # admin Graph tab (admin-scoped), so viewing any *named* partition is intentional;
        # validation rejects only malformed/empty/unknown-namespace ids.
        if body.group_ids:
            try:
                validated_groups: list[str] | None = [
                    validate_group_id(g) for g in body.group_ids
                ]
            except GroupPolicyError as exc:
                return envelope_failure(f"Invalid graph group: {exc}")
        else:
            validated_groups = None
        payload = await graph_snapshot_payload(
            workspace_path,
            node_limit=body.node_limit,
            edge_limit=body.edge_limit,
            group_ids=validated_groups,
        )
        return _success(payload)
    except Exception as exc:
        # With the shared driver, in-process opens no longer collide; a lock error here
        # means an EXTERNAL process holds the file (a 2nd hiro / stale handle). Return a
        # clean "busy" message instead of a raw stack (docs §4.5).
        from hirocli.services.knowledge.graph.graphiti_service import is_kuzu_lock_error

        if is_kuzu_lock_error(exc):
            log.warning("⚠️ knowledge graph export — graph DB busy (external lock held)")
            return envelope_failure(
                "Graph database is busy (a build may be running in another process) — "
                "try again shortly."
            )
        log.error("knowledge graph export failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/graph/groups")
async def graph_groups(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """List the graph's partitions for the Graph tab's group selector — "Knowledge" plus
    each ``mem_{user}_{character}`` conversation-memory graph. Read-only; empty when no
    graph is built yet."""
    from hirocli.tools.knowledge_graph import graph_groups_payload

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path).resolve()
        payload = await graph_groups_payload(workspace_path)
        return _success(payload)
    except Exception as exc:
        from hirocli.services.knowledge.graph.graphiti_service import is_kuzu_lock_error

        if is_kuzu_lock_error(exc):
            log.warning("⚠️ knowledge graph groups — graph DB busy (external lock held)")
            return envelope_failure(
                "Graph database is busy (a build may be running in another process) — "
                "try again shortly."
            )
        log.error("knowledge graph groups failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


class GraphRemoveDocumentBody(BaseModel):
    """Per-document graph delete — drops one document's episodes/entities/facts."""

    document_id: str


@knowledge_router.post("/knowledge/graph/clear")
async def graph_clear(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Delete the ENTIRE knowledge graph (all entities + facts) for the workspace.

    Qdrant chunks/documents are untouched, so the graph can be rebuilt from them.
    Backs the Graph tab's "Clear graph" action.
    """
    from hirocli.tools.knowledge_graph import clear_knowledge_graph

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path).resolve()
        removed = await clear_knowledge_graph(workspace_path)
        return _success({"removed_episodes": removed})
    except Exception as exc:
        from hirocli.services.knowledge.graph.graphiti_service import is_kuzu_lock_error

        if is_kuzu_lock_error(exc):
            log.warning("⚠️ knowledge graph clear — graph DB busy (external lock held)")
            return envelope_failure(
                "Graph database is busy (a build may be running in another process) — "
                "try again shortly."
            )
        log.error("knowledge graph clear failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/graph/remove-document")
async def graph_remove_document(
    body: GraphRemoveDocumentBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Delete one document's episodes (+ exclusively-owned entities/facts) from the
    knowledge graph, keeping its Qdrant chunks. Closes the orphan-on-document-delete gap;
    backs the Browse tab's per-document "Remove from graph" action.
    """
    from hirocli.tools.knowledge_graph import remove_document_from_graph

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path).resolve()
        removed = await remove_document_from_graph(workspace_path, body.document_id)
        return _success({"document_id": body.document_id, "removed_episodes": removed})
    except Exception as exc:
        from hirocli.services.knowledge.graph.graphiti_service import is_kuzu_lock_error

        if is_kuzu_lock_error(exc):
            log.warning(
                "⚠️ knowledge graph remove-document — graph DB busy (external lock held)"
            )
            return envelope_failure(
                "Graph database is busy (a build may be running in another process) — "
                "try again shortly."
            )
        log.error("knowledge graph remove-document failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/graph/chunks-detail")
async def graph_chunks_detail(
    body: GraphChunksDetailBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Graph viz — chunk text + document titles for a selected node/edge's chunk_ids.

    Lazy provenance lookup (Qdrant-backed): the Graph tab calls this when a node or
    edge is selected so the detail panel can show real chunk text + document names
    instead of opaque chunk ids. Mirrors the get_document route's service wiring.
    """
    # Cap one selection's lookup — a node rolls up the chunks of every touching edge.
    ids = [str(c) for c in (body.chunk_ids or []) if c][:200]
    if not ids:
        return _success({"chunks": []})
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success({"chunks": await service.get_chunk_details(ids)})
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge graph chunks-detail failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/graph/search-chunks")
async def graph_search_chunks(
    body: GraphSearchChunksBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """Graph viz — chunk-text search → matching Qdrant point_ids (== graph chunk_ids).

    Literal case-insensitive substring scan over chunk payloads. The Graph tab maps the
    returned ids onto nodes/edges via their ``chunk_ids`` (G6) to highlight everything
    sourced from a matching chunk. Blank query → empty result (caller clears the search).
    """
    text = (body.text or "").strip()
    if not text:
        return _success({"point_ids": []})
    # Cap the scan so a hot search box can't sweep an unbounded collection per keystroke.
    limit = max(1, min(int(body.limit or 200), 500))
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            point_ids = await service.search_chunk_ids_by_text(text, limit=limit)
            return _success({"point_ids": point_ids})
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge graph search-chunks failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/eval/run")
async def eval_run(
    body: EvalRunBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """L3 (Phase 5e) — kick the synthetic eval batch in the background.

    Returns ``{run_id}`` immediately. The eval emits ``knowledge.eval.*`` Domain
    Events as it goes; the admin UI subscribes via ``/knowledge/events`` to
    update the live progress table. Tied to the workspace_id; the SSE filter
    drops events for other workspaces.
    """
    # Local imports keep the module's top-level deps thin — eval is a niche path.
    from hirocli.services.knowledge.eval_registry import get_eval_registry
    from hirocli.services.knowledge.eval_runner import (
        MAX_QUESTION_CONCURRENCY,
        eval_kb_tag,
        ingest_synthetic_corpus_via_service,
        load_questions,
        normalize_modes,
        run_eval,
        run_memory_eval,
    )
    from hirocli.tools.knowledge_graph import (
        _run_graph_ingest_for_documents,
        remove_document_from_graph,
    )

    try:
        service, owned = await _resolve_service(request, workspace_id)
        run_id = (body.run_id or "").strip() or f"l3eval-{uuid.uuid4()}"
        workspace_path = service.workspace_path
        # Memory track runs a single recall leg (no flat/graphiti); knowledge keeps the leg set.
        run_modes = ["recall"] if body.track == "memory" else normalize_modes(body.modes)

        # Resolve + validate the chosen corpus and question selection up front, so a bad
        # request fails the HTTP call directly (not as a silent background crash). Questions are
        # an explicit selection (no implicit "run all"), but may be empty for a setup-only batch
        # (remember/ingest/build/clear) — see the setup_only check below.
        corpus_id = (body.corpus_id or "").strip()
        corpus_path = (body.corpus_path or "").strip()
        questions_path = (body.questions_path or "").strip()
        selected_ids = [q for q in (body.question_ids or []) if q]
        if not corpus_id or not corpus_path:
            return envelope_failure("Pick a corpus before running the eval.")
        # Setup-only runs (remember/ingest/build/clear a batch with NO questions) are allowed —
        # that's how a large corpus gets built in monitored chunks before any recall. A run with
        # neither questions nor a setup action would do nothing, so reject only that case.
        setup_only = body.ingest_synthetic or body.build_graph or body.clear_before
        if not selected_ids and not setup_only:
            return envelope_failure(
                "Select at least one question, or enable Remember / Clear for a setup-only batch."
            )
        # Questions need their bank; a setup-only batch doesn't. Load + filter to the explicit
        # selection (preserving bank order). Empty selection ⇒ no questions (setup-only run).
        questions: list[dict[str, Any]] = []
        if selected_ids:
            if not questions_path or not Path(questions_path).exists():
                return envelope_failure(
                    f"No question bank found for corpus '{corpus_id}' "
                    f"(expected {corpus_id}.questions.yaml beside the corpus)."
                )
            wanted = set(selected_ids)
            questions = [q for q in load_questions(Path(questions_path)) if q["id"] in wanted]
            if not questions:
                return envelope_failure("None of the selected question ids exist in the bank.")
        # Subscribe the per-workspace run registry BEFORE the task starts so it
        # captures the full event trail for mid-run replay / cross-origin reads.
        registry = get_eval_registry()
        registry.ensure_subscribed()

        async def _runner() -> None:
            # All exceptions caught inside the task: a background-task crash that
            # bubbles up to the asyncio loop has nowhere to go (no awaiter) and
            # the UI would see "FAILED" event but no error context. We log the
            # full traceback ourselves and emit the FAILED event (run_eval
            # already does on its own exceptions; setup-phase exceptions are
            # handled explicitly here).
            try:
                # Memory track: remember the chosen turn corpus into its eval_mem_{corpus_id}
                # drawer via an eval-scoped memory facade, then recall per question. Single recall
                # leg, no gate (docs §8). ``ingest_synthetic`` doubles as "remember the corpus" so
                # question subsets re-run without re-remembering. Independent of memory.enabled.
                if body.track == "memory":
                    from hirocli.domain.preferences import load_preferences
                    from hirocli.services.memory import create_eval_memory_service

                    prefs = load_preferences(workspace_path)
                    memory = create_eval_memory_service(
                        workspace_path, prefs, set_id=corpus_id
                    )
                    # Clamp (don't reject) the question-phase cap — a stale/edited client
                    # value should degrade to the nearest legal cap, not fail the run.
                    concurrency = max(
                        1, min(int(body.question_concurrency or 1), MAX_QUESTION_CONCURRENCY)
                    )
                    try:
                        log.info(
                            "⬇️ knowledge.eval — memory track · corpus=%s · remember=%s · "
                            "clear=%s · range=[%s:%s] · concurrency=%d · run_id=%s",
                            corpus_id,
                            body.ingest_synthetic,
                            body.clear_before,
                            body.episode_offset,
                            body.episode_limit,
                            concurrency,
                            run_id,
                        )
                        await run_memory_eval(
                            memory,
                            workspace_path,
                            set_id=corpus_id,
                            corpus_path=Path(corpus_path),
                            questions=questions,
                            run_id=run_id,
                            remember=body.ingest_synthetic,
                            clear_before=body.clear_before,
                            episode_offset=body.episode_offset,
                            episode_limit=body.episode_limit,
                            judge=body.judge,
                            question_concurrency=concurrency,
                        )
                    finally:
                        await memory.close()
                    return

                # Knowledge track: ingest the chosen .md corpus folder (tagged per corpus so
                # retrieval scopes to it), optionally build the graph, then run flat/graphiti.
                eval_tag = eval_kb_tag(corpus_id)
                ingested_ids: list[str] = []
                if body.ingest_synthetic:
                    # Re-ingest = clean slate. Drop this corpus's prior eval docs (catalog +
                    # Qdrant chunks + their graph episodes) BEFORE re-ingesting, so a re-run
                    # starts fresh. Re-ingesting over existing chunks/graph let stale state
                    # contaminate retrieval + Graphiti dedup (memory-track parity). Gated on the
                    # checkbox: a subset re-run (both off) reuses the existing index.
                    prior = await service.list_documents(tag=eval_tag, limit=500)
                    for doc in prior.documents:
                        await service.delete_document(doc.id)
                    if prior.documents:
                        log.info(
                            "🧹 knowledge.eval — cleared %d prior eval doc(s) · corpus=%s",
                            len(prior.documents),
                            corpus_id,
                        )
                    log.info(
                        "⬇️ knowledge.eval — ingesting corpus '%s' · run_id=%s",
                        corpus_id,
                        run_id,
                    )
                    ingested_ids = await ingest_synthetic_corpus_via_service(
                        service,
                        workspace_path,
                        corpus_dir=Path(corpus_path),
                        tag=eval_tag,
                        run_id=run_id,
                    )
                if body.build_graph:
                    # When ingest was skipped, find this corpus's docs by its eval tag.
                    if ingested_ids:
                        doc_ids = ingested_ids
                    else:
                        docs = await service.list_documents(tag=eval_tag, limit=500)
                        doc_ids = [d.id for d in docs.documents]
                    # Rebuild = clean slate. On a build-ONLY run (ingest off, reusing existing
                    # chunks) wipe these docs' prior graph episodes first so the graph rebuilds
                    # clean — re-ingesting episodes over the old graph let Graphiti dedup against
                    # stale state. When ingest just ran, the docs are fresh with no graph yet, so
                    # the delete_document above already cleared it → skip this pass.
                    if doc_ids and not body.ingest_synthetic:
                        for did in doc_ids:
                            await remove_document_from_graph(workspace_path, did)
                        log.info(
                            "🧹 knowledge.eval — cleared prior graph for %d doc(s) · corpus=%s",
                            len(doc_ids),
                            corpus_id,
                        )
                    if doc_ids:
                        log.info(
                            "⬇️ knowledge.eval — graph-ingesting %d doc(s) · run_id=%s",
                            len(doc_ids),
                            run_id,
                        )
                        await _run_graph_ingest_for_documents(
                            service,
                            workspace_path,
                            doc_ids,
                            source_role="user_document",
                            # Emit live node/edge events so the Graph tab updates while the
                            # eval's graph build runs (matches the ingest_batch path). Without
                            # this sink the eval build was silent → no live viz updates.
                            event_sink=functools.partial(
                                _publish_graph_event, workspace_path
                            ),
                        )
                        # Burst over — let the Graph tab run one reconciling full export to
                        # heal any deltas dropped under the SSE queue cap (mirrors ingest_batch).
                        _publish_graph_event(
                            workspace_path,
                            KNOWLEDGE_GRAPH_INGEST_COMPLETED,
                            # Knowledge-eval graph docs ingest into the default kb_main group;
                            # tag the completion so the Graph tab gates the clear/reconcile by
                            # the partition it's viewing (mirrors ingest_progress' group_id).
                            {
                                "document_count": len(doc_ids),
                                "totals": {},
                                "group_id": KNOWLEDGE_GROUP_ID,
                            },
                        )
                    else:
                        log.warning(
                            "⚠️ knowledge.eval — build_graph requested but no "
                            "synthetic docs in workspace · run_id=%s",
                            run_id,
                        )
                # run_eval emits started / question_completed / completed / failed
                # events on its own — scoped to this corpus's docs + selected questions.
                await run_eval(
                    service,
                    workspace_path,
                    questions=questions,
                    run_id=run_id,
                    filters={"tags": [eval_tag]},
                    modes=run_modes,
                    judge=body.judge,
                )
            except asyncio.CancelledError:
                # User pressed Cancel (the cancel route called task.cancel(), which
                # raises here at the next await). Emit the neutral terminal CANCELLED
                # event so the panel stops spinning and reads it as "stopped", not
                # "failed". Re-raise so the task is properly marked cancelled.
                log.info("🛑 knowledge.eval — run cancelled · run_id=%s", run_id)
                get_domain_event_bus().publish(
                    DomainEvent(
                        type=KNOWLEDGE_EVAL_CANCELLED,
                        workspace_path=workspace_path,
                        payload={"run_id": run_id},
                    )
                )
                raise
            except Exception as exc:
                log.error(
                    "❌ knowledge.eval — background run failed · run_id=%s",
                    run_id,
                    exc_info=True,
                )
                # Emit the terminal FAILED event. run_eval emits this on its OWN
                # failures, but a SETUP-phase crash (corpus ingest / build-graph) happens
                # before run_eval runs — without this the admin Eval panel never receives
                # a terminal event and spins forever. Same payload shape as run_eval.
                get_domain_event_bus().publish(
                    DomainEvent(
                        type=KNOWLEDGE_EVAL_FAILED,
                        workspace_path=workspace_path,
                        payload={
                            "run_id": run_id,
                            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        },
                    )
                )
            finally:
                if owned:
                    await _close_if_owned(service, owned)

        # ``create_task`` is fire-and-forget here. The route returns immediately
        # so the UI gets ``run_id`` without blocking on the eval (which can take
        # minutes for a real corpus). Register the task with the run registry
        # synchronously (before it gets a chance to run) so a Cancel that arrives
        # before the first event still finds a handle, and so the registry holds
        # the live state for replay.
        task = asyncio.create_task(_runner())
        registry.begin_run(
            workspace_path,
            run_id,
            corpus_source=corpus_id,
            modes=run_modes,
            task=task,
            track=body.track,
        )
        return _success({"run_id": run_id})
    except Exception as exc:
        log.error(
            "knowledge eval run failed to start · workspace=%s · %s",
            workspace_id,
            str(exc),
            exc_info=True,
        )
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/eval/state")
async def eval_state(
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """L3 — replay the latest eval run's live state for this workspace.

    The admin panel calls this on mount so leaving + returning (or opening the
    Vite dev UI vs the packaged UI — different origins, separate sessionStorage)
    shows the SAME run: the setup activity trail, the per-question rows with full
    answers, and the summary. ``data`` is ``null`` when no run exists (idle, or
    the server restarted since the last run)."""
    from hirocli.services.knowledge.eval_registry import get_eval_registry

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        state = get_eval_registry().get_run(workspace_path)
        return _success(state.to_payload() if state is not None else None)
    except Exception as exc:
        log.error("knowledge eval state failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


class EvalCancelBody(BaseModel):
    """L3 — cancel a running eval. ``run_id`` is optional (defensive): when
    present we only cancel if it matches the live run, so a stale Cancel click
    from a previous run can't kill a new one."""

    run_id: str | None = None


@knowledge_router.post("/knowledge/eval/cancel")
async def eval_cancel(
    body: EvalCancelBody,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """L3 — request cancellation of the in-flight eval run for this workspace.

    Cancels the background task; the runner catches ``CancelledError`` and emits
    the terminal ``knowledge.eval.cancelled`` event. Returns whether a live run
    was actually signalled."""
    from hirocli.services.knowledge.eval_registry import get_eval_registry

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        cancelled = get_eval_registry().request_cancel(workspace_path, body.run_id)
        return _success({"cancelled": cancelled, "run_id": body.run_id})
    except Exception as exc:
        log.error("knowledge eval cancel failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/eval/clear")
async def eval_clear(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
    track: str = "knowledge",
    corpus_id: str = "",
) -> dict[str, Any]:
    """Delete a track's eval data from the workspace. Backs the Eval panel's "Clear eval data".

    - **knowledge** (default): document-scoped wipe of the chosen corpus's eval-tagged docs
      (``_eval_kb_{corpus_id}`` → catalog + Qdrant + graph episodes) via ``clear_eval_data``.
    - **memory**: group-scoped wipe of the chosen ``eval_mem_{corpus_id}`` drawer via the
      eval-scoped memory facade's ``clear_all`` (docs/eval-corpus-tracks-design.md §8.5).
    """
    if track == "memory":
        from hirocli.domain.preferences import load_preferences
        from hirocli.services.knowledge.eval_runner import MEMORY_EVAL_USER_ID
        from hirocli.services.memory import create_eval_memory_service

        set_id = (corpus_id or "").strip()
        if not set_id:
            return envelope_failure("corpus_id is required to clear a memory eval drawer.")
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        try:
            prefs = load_preferences(workspace_path)
            memory = create_eval_memory_service(workspace_path, prefs, set_id=set_id)
            try:
                removed = await memory.clear_all(
                    user_id=MEMORY_EVAL_USER_ID, character_id=set_id
                )
            finally:
                await memory.close()
            # Wiping the drawer invalidates the ingested-range readout — drop it in the same
            # call so the panel can't show a range for data that's gone.
            from hirocli.services.knowledge.eval_store import get_eval_result_store

            get_eval_result_store(workspace_path).clear_ranges(set_id)
            return _success({"removed_facts": removed})
        except Exception as exc:
            log.error("knowledge eval clear (memory) failed · %s", str(exc), exc_info=True)
            return envelope_failure(str(exc))

    from hirocli.services.knowledge.eval_runner import clear_eval_data

    kb_corpus = (corpus_id or "").strip()
    if not kb_corpus:
        return envelope_failure("corpus_id is required to clear a knowledge eval corpus.")
    service, owned = await _resolve_service(request, workspace_id)
    try:
        removed = await clear_eval_data(service, kb_corpus)
        return _success({"removed_documents": removed})
    except Exception as exc:
        log.error("knowledge eval clear failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))
    finally:
        await _close_if_owned(service, owned)


@knowledge_router.get("/knowledge/eval/results")
async def eval_results(
    workspace_id: SelectedWorkspaceIdDep,
    track: str = "memory",
    corpus_id: str = "",
    questions_path: str = "",
) -> dict[str, Any]:
    """Persisted per-corpus eval results (the merged snapshot) — backs "show latest".

    Memory track only. Joins the CURRENT question bank (the spine — so edited
    question text/category/ideal show fresh) with the saved per-question rows, in
    bank order, and recomputes the merged summary over the whole accumulated set.
    Questions in the bank with no saved row are simply absent here (the checklist
    surfaces them as "not run"). Returns ``{rows, summary}``; both empty when
    nothing has been saved for the corpus."""
    if track != "memory":
        # Knowledge results aren't persisted yet (the store is memory-only for now).
        return _success({"rows": [], "summary": None})
    cid = (corpus_id or "").strip()
    if not cid:
        return envelope_failure("corpus_id is required to read eval results.")
    from hirocli.services.knowledge.eval_runner import load_questions, summarize_memory_rows
    from hirocli.services.knowledge.eval_store import (
        coalesce_ingested_ranges,
        get_eval_result_store,
    )

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        store = get_eval_result_store(workspace_path)
        stored = store.read_corpus(cid)
        # Ingested-range readout (build progress). Read BEFORE the no-rows early-return: a
        # remember-only build has ingested ranges but zero saved question rows, so returning
        # early on empty `stored` would hide its progress.
        raw_ranges = store.read_ranges(cid)
        spans = coalesce_ingested_ranges(raw_ranges)
        # Cumulative per-corpus ingest cost = sum of every recorded batch's cost (re-ingesting an
        # offset overwrites that batch's row, so this never double-counts). This is the ONLY place
        # ingest cost survives a reload — the per-question rows never carry it — so the panel's Cost
        # strip reads it even for a remember-only corpus with zero saved questions.
        ingest_cost_usd = sum(float(r.get("cost_usd") or 0.0) for r in raw_ranges)
        ingested = {
            "ranges": spans,  # sorted, inclusive [start, end] episode-index spans
            "count": sum(end - start + 1 for start, end in spans),  # distinct episodes ingested
            "batches": len(raw_ranges),  # how many remember batches recorded
            "cost_usd": ingest_cost_usd,  # cumulative ingest (graph-build) spend for this corpus
        }
        if not stored:
            return _success({"rows": [], "summary": None, "ingested": ingested})
        # Bank is the spine: order rows by the bank and refresh their display fields
        # from it. Falls back to stored order/fields if the bank is missing (corpus
        # moved/renamed) so saved results are never lost behind a path mismatch.
        qpath = Path(questions_path.strip()) if questions_path.strip() else None
        bank = load_questions(qpath) if qpath and qpath.exists() else []
        if bank:
            bank_by_id = {q["id"]: q for q in bank}
            ordered_ids = [q["id"] for q in bank if q["id"] in stored]
        else:
            bank_by_id = {}
            ordered_ids = list(stored.keys())
        total = len(ordered_ids)
        merged: list[dict[str, Any]] = []
        for index, qid in enumerate(ordered_ids):
            row = dict(stored[qid])
            q = bank_by_id.get(qid)
            if q is not None:
                # Refresh spine fields from the bank (edits show immediately); keep the
                # saved legs/answer/recall/mark/cost — those are the actual results.
                row["question"] = q.get("question", row.get("question", ""))
                row["category"] = q.get("category", row.get("category", ""))
                row["subcategory"] = q.get("subcategory", row.get("subcategory", ""))
                row["difficulty"] = q.get("difficulty", row.get("difficulty", ""))
                row["requires_graph"] = bool(
                    q.get("requires_graph", row.get("requires_graph"))
                )
                row["gold"] = q.get("expected_answer", row.get("gold", ""))
            # Stable display position within the merged snapshot (bank order).
            row["index"] = index
            row["total"] = total
            merged.append(row)
        # Evidence recall (LoCoMo corpora only): per question, how many gold evidence episodes the
        # recalled context covered (X/Y in the table + per-episode matched/missed in the fold).
        # Read-path enrichment computed from the saved `recalled` + the corpus sidecar — works on
        # already-saved results with no re-run. Best-effort: never let it break the results read.
        if qpath is not None:
            try:
                from hirocli.services.knowledge.eval_locomo import compute_evidence_recall_map

                ev_map = compute_evidence_recall_map(
                    corpus_id=cid, questions_path=qpath, rows=merged
                )
                for row in merged:
                    ev = ev_map.get(str(row.get("id") or ""))
                    if ev is not None:
                        row["evidence_recall"] = ev
            except Exception as exc:
                log.warning(
                    "knowledge eval evidence-recall enrichment failed · %s", str(exc), exc_info=True
                )
        summary = summarize_memory_rows(merged, run_id=f"saved-{cid}")
        # The merged snapshot spans many runs, so summarize_memory_rows can't know a single ingest
        # cost (it leaves ingest_cost_usd=0). Override with the persisted CUMULATIVE ingest spend so
        # a reloaded run shows the corpus's full build cost, not just the question cost.
        summary["ingest_cost_usd"] = ingest_cost_usd
        summary["total_cost_usd"] = ingest_cost_usd + summary.get("questions_cost_usd", 0.0)
        return _success({"rows": merged, "summary": summary, "ingested": ingested})
    except Exception as exc:
        log.error("knowledge eval results read failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


class EvalResultsClearBody(BaseModel):
    """Results-only clear of a corpus's persisted eval snapshot (memory track)."""

    track: str = "memory"
    corpus_id: str = ""


@knowledge_router.post("/knowledge/eval/results/clear")
async def eval_results_clear(
    body: EvalResultsClearBody,
    workspace_id: SelectedWorkspaceIdDep,
) -> dict[str, Any]:
    """Delete a corpus's persisted eval RESULTS from disk (results-only).

    Distinct from ``/knowledge/eval/clear`` (which wipes the ingested memory
    drawer): this removes only the saved result snapshot, leaving ingested memory
    intact so a re-run reuses it. Memory track only."""
    if body.track != "memory":
        return envelope_failure("Only the memory track persists eval results.")
    cid = (body.corpus_id or "").strip()
    if not cid:
        return envelope_failure("corpus_id is required to clear eval results.")
    from hirocli.services.knowledge.eval_store import get_eval_result_store

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        removed = get_eval_result_store(workspace_path).clear_corpus(cid)
        log.info("🧹 knowledge.eval — cleared %d saved result row(s) · corpus=%s", removed, cid)
        return _success({"removed": removed})
    except Exception as exc:
        log.error("knowledge eval results clear failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/eval/results/locomo")
async def eval_results_locomo(
    workspace_id: SelectedWorkspaceIdDep,
    corpus_id: str = "",
    questions_path: str = "",
    prediction_key: str = "hiro_memory_prediction",
) -> dict[str, Any]:
    """Export saved memory-eval results in LoCoMo's QA-result JSON shape.

    The API envelope carries filename/counts for the admin UI, but ``data.content`` is the
    exact file body to download for LoCoMo evaluation: ``[{sample_id, qa: [...]}]``.
    Partial saved snapshots export the answered subset, matching LoCoMo's evaluator (it
    scores whichever QA rows are present).
    """
    cid = (corpus_id or "").strip()
    qpath = Path(questions_path.strip()) if questions_path.strip() else None
    if not cid:
        return envelope_failure("corpus_id is required to export LoCoMo results.")
    if qpath is None:
        return envelope_failure("questions_path is required to export LoCoMo results.")

    from hirocli.services.knowledge.eval_locomo import (
        LocomoExportError,
        build_locomo_results_export,
    )
    from hirocli.services.knowledge.eval_store import get_eval_result_store

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path)
        stored = get_eval_result_store(workspace_path).read_corpus(cid)
        export = build_locomo_results_export(
            corpus_id=cid,
            questions_path=qpath,
            stored_rows=stored,
            prediction_key=(prediction_key or "hiro_memory_prediction").strip(),
        )
        return _success(export)
    except LocomoExportError as exc:
        return envelope_failure(str(exc))
    except Exception as exc:
        log.error("knowledge eval LoCoMo export failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/eval/corpuses")
async def eval_corpuses(
    workspace_id: SelectedWorkspaceIdDep,
    track: str = "memory",
    folder: str = "",
) -> dict[str, Any]:
    """List the corpuses in ``folder`` for ``track`` (the corpus-picker source).

    ``folder`` defaults to the repo ``eval/`` dir. Each corpus pairs with its
    ``<id>.questions.yaml`` bank by the stem convention (docs §12). The corpus files
    are workspace-independent, but each entry's ``has_graph`` flag (whether a graph was
    already built for it) is read from the selected workspace's graph — it drives the
    picker's "Rebuild graph" default + wipe warning."""
    from hirocli.services.knowledge.eval_runner import DEFAULT_EVAL_FOLDER, discover_corpuses
    from hirocli.services.knowledge.graph import distinct_group_ids_with_prefix, graphiti_db_path
    from hirocli.services.knowledge.graph.group_scope import (
        EVAL_KNOWLEDGE_PREFIX,
        EVAL_MEMORY_PREFIX,
        eval_knowledge_group_id,
        eval_memory_group_id,
    )

    try:
        base = Path(folder.strip()) if folder.strip() else DEFAULT_EVAL_FOLDER
        corpuses = discover_corpuses(base, track)
        # reason: tag each corpus with whether its graph is already built, so the picker can
        # default "Rebuild graph" OFF (reuse) vs ON (build), and warn before a rebuild wipes it.
        # One DISTINCT-by-prefix read covers the whole list (membership test per corpus); a
        # graph-read hiccup degrades to has_graph=False so the picker still works.
        prefix = EVAL_MEMORY_PREFIX if track == "memory" else EVAL_KNOWLEDGE_PREFIX
        group_for = eval_memory_group_id if track == "memory" else eval_knowledge_group_id
        # reason: resolve the workspace once and hand the client its absolute ``logs/`` dir.
        # The eval "Copy for AI" brief uses it to point an investigating agent straight at the
        # on-disk ledger sidecars (retrieval_trace/<run_id>.jsonl, ingest_trace/, graph.log)
        # so it never has to search for them. log_dir is set before the (fallible) graph probe,
        # so a probe hiccup still yields the path; "" only when the workspace can't be resolved.
        log_dir = ""
        existing: set[str] = set()
        try:
            entry, _ = resolve_workspace(workspace_id)
            ws_path = Path(entry.path)
            log_dir = str(ws_path / "logs")
            db_path = graphiti_db_path(ws_path)
            existing = await distinct_group_ids_with_prefix(db_path, prefix)
        except Exception:
            log.warning(
                "⚠️ knowledge.eval — has_graph probe failed · track=%s · defaulting to false",
                track,
                exc_info=True,
            )
        for c in corpuses:
            c["has_graph"] = group_for(c["id"]) in existing
        return _success(
            {"track": track, "folder": str(base), "corpuses": corpuses, "log_dir": log_dir}
        )
    except Exception as exc:
        log.error("knowledge eval corpuses list failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/eval/corpus")
async def eval_corpus(path: str = "") -> dict[str, Any]:
    """Load a memory-track corpus's episodes for the human-readable Corpus review panel.

    ``path`` is the ``<id>.episodes.jsonl`` for the chosen corpus (from the corpuses list).
    Returns each turn as ``{id, timestamp, speaker, type, body}`` in chronological order
    (``load_episodes_file`` sorts by timestamp), plus light meta (episode count + date span)
    for the stats header. Read-only and workspace-independent — episodes live beside their
    question banks. Memory-track only; knowledge corpora are folders of ``.md`` docs."""
    from hirocli.services.knowledge.graph.graphiti_corpus import load_episodes_file

    try:
        cpath = Path(path.strip())
        if not path.strip() or not cpath.exists():
            return envelope_failure(f"Corpus not found: {path or '(none given)'}")
        # Parsing reads + validates the whole file; keep it off the event loop.
        episodes = await run_in_threadpool(load_episodes_file, cpath)
        rows = [
            {
                "id": ep.chunk_id,
                "timestamp": ep.reference_time.isoformat() if ep.reference_time else "",
                "speaker": ep.speaker or "",
                "type": ep.source or "text",
                "body": ep.text,
            }
            for ep in episodes
        ]
        return _success(
            {
                "path": str(cpath),
                "episode_count": len(rows),
                # Episodes are already chronological → first/last bound the corpus date span.
                "first_timestamp": rows[0]["timestamp"] if rows else "",
                "last_timestamp": rows[-1]["timestamp"] if rows else "",
                "episodes": rows,
            }
        )
    except Exception as exc:
        log.error("knowledge eval corpus load failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/eval/questions")
async def eval_questions(path: str = "") -> dict[str, Any]:
    """List a corpus's question bank for the checklist (id/category/subcategory/text/gold).

    ``path`` is the ``<id>.questions.yaml`` for the chosen corpus (from the corpuses list).
    Workspace-independent — banks live beside their corpora."""
    from hirocli.services.knowledge.eval_runner import load_questions

    try:
        qpath = Path(path.strip())
        if not path.strip() or not qpath.exists():
            return envelope_failure(f"Question bank not found: {path or '(none given)'}")
        rows = load_questions(qpath)
        questions = [
            {
                "id": q["id"],
                "category": q.get("category", ""),
                "subcategory": q.get("subcategory", ""),
                # Authored difficulty — surfaced as a chip in the question-picker checklist.
                "difficulty": q.get("difficulty", ""),
                "question": q["question"],
                "requires_graph": bool(q.get("requires_graph")),
                "expected_answer": q.get("expected_answer", ""),
            }
            for q in rows
        ]
        return _success({"path": str(qpath), "questions": questions})
    except Exception as exc:
        log.error("knowledge eval questions list failed · %s", str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/documents")
async def list_documents(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
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
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(
                await service.list_documents(
                    status=status,
                    owner_kind=owner_kind,
                    owner_id=owner_id,
                    category_id=category_id,
                    subcategory_id=subcategory_id,
                    tag=tag,
                    source_type=source_type,
                    title=title,
                    limit=limit,
                    offset=offset,
                )
            )
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge list documents failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.delete("/knowledge/documents/{document_id}")
async def delete_document(
    document_id: str,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(await service.delete_document(document_id))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge delete document failed", document_id=document_id, error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.post("/knowledge/documents/{document_id}/reingest")
async def reingest_document(
    document_id: str,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(await service.reingest_document(document_id))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge reingest document failed", document_id=document_id, error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.patch("/knowledge/documents/{document_id}/metadata")
async def update_document_metadata(
    document_id: str,
    body: UpdateMetadataBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(
                await service.update_document_metadata(
                    document_id,
                    owner_kind=body.owner_kind,
                    owner_id=body.owner_id,
                    category_id=body.category_id,
                    subcategory_id=body.subcategory_id,
                    tags=body.tags,
                )
            )
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge update metadata failed", document_id=document_id, error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/documents/{document_id}")
async def get_document(
    document_id: str,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
    chunk_limit: int = 100,
    chunk_offset: str | None = None,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(
                await service.get_document(
                    document_id,
                    chunk_limit=chunk_limit,
                    chunk_offset=chunk_offset,
                )
            )
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge get document failed", document_id=document_id, error=str(exc), exc_info=True)
        return envelope_failure(str(exc))
