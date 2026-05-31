"""Admin routes for workspace-local knowledge ingest/search/browse."""

from __future__ import annotations

import asyncio
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
from hirocli.domain.workspace import resolve_workspace
from hirocli.services.knowledge import KnowledgeService, create_knowledge_service
from hirocli.services.knowledge.constants import (
    KNOWLEDGE_DELETED,
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
from hirocli.services.knowledge.live_registry import maybe_recover_abandoned_work

log = Logger.get("ADMIN.KNOWLEDGE")

knowledge_router = APIRouter()


def _success(data: Any) -> dict[str, Any]:
    return {"ok": True, "error": None, "data": data}


def _publish_graph_event(
    workspace_path: Path, event_type: str, payload: dict[str, Any]
) -> None:
    """Publish a graph-viz Domain Event (workspace-scoped). Module-level so the
    ingest ``event_sink`` can be ``functools.partial(_publish_graph_event, ws)``
    — no nested closure. The bus drops with a warning if no loop is attached."""
    get_domain_event_bus().publish(
        DomainEvent(type=event_type, workspace_path=workspace_path, payload=payload)
    )


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

    @model_validator(mode="after")
    def _validate_graph_mode(self) -> AnswerBody:
        if self.graph_mode not in ("off", "on", "compare"):
            raise ValueError(
                f"graph_mode must be 'off', 'on', or 'compare', got {self.graph_mode!r}"
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

    ingest_synthetic: bool = False
    build_graph: bool = False
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

        bus = get_domain_event_bus()
        for event_type in event_types:
            bus.subscribe(event_type, handler)
        try:
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(event.payload, separators=(",", ":"))
                yield f"event: {event.type}\ndata: {payload}\n\n"
        except asyncio.CancelledError:
            return
        finally:
            for event_type in event_types:
                bus.unsubscribe(event_type, handler)

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
                    use_graph=(body.graph_mode == "on"),
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
    to extract entities/relations into the LadybugDB graph. Per-document failure
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
    the Phase 2 filters and ignored in the MVP; the limits are safety caps."""

    node_types: list[str] | None = None
    document_id: str | None = None
    node_limit: int | None = None
    edge_limit: int | None = None


@knowledge_router.post("/knowledge/graph/export")
async def graph_export(
    body: GraphExportBody,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
) -> dict[str, Any]:
    """L3 graph viz (MVP) — whole-graph export, the Graph tab's load path.

    Read-only and independent of Qdrant: resolves the workspace path and returns
    all nodes/edges from the LadybugDB graph. Empty graph when none built yet.
    """
    from hirocli.tools.knowledge_graph import graph_snapshot_payload

    try:
        entry, _ = resolve_workspace(workspace_id)
        workspace_path = Path(entry.path).resolve()
        payload = await run_in_threadpool(
            graph_snapshot_payload,
            workspace_path,
            node_limit=body.node_limit,
            edge_limit=body.edge_limit,
        )
        return _success(payload)
    except Exception as exc:
        log.error("knowledge graph export failed", error=str(exc), exc_info=True)
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
    from hirocli.services.knowledge.eval_runner import (
        collect_synthetic_doc_ids,
        ingest_synthetic_corpus_via_service,
        run_eval,
    )
    from hirocli.tools.knowledge_graph import _run_graph_ingest_for_documents

    try:
        service, owned = await _resolve_service(request, workspace_id)
        run_id = (body.run_id or "").strip() or f"l3eval-{uuid.uuid4()}"
        workspace_path = service.workspace_path

        async def _runner() -> None:
            # All exceptions caught inside the task: a background-task crash that
            # bubbles up to the asyncio loop has nowhere to go (no awaiter) and
            # the UI would see "FAILED" event but no error context. We log the
            # full traceback ourselves and emit the FAILED event (run_eval
            # already does on its own exceptions; setup-phase exceptions are
            # handled explicitly here).
            try:
                ingested_ids: list[str] = []
                if body.ingest_synthetic:
                    log.info(
                        "⬇️ knowledge.eval — ingesting synthetic corpus · run_id=%s",
                        run_id,
                    )
                    ingested_ids = await ingest_synthetic_corpus_via_service(
                        service, workspace_path
                    )
                if body.build_graph:
                    doc_ids = ingested_ids or await collect_synthetic_doc_ids(service)
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
                        )
                    else:
                        log.warning(
                            "⚠️ knowledge.eval — build_graph requested but no "
                            "synthetic docs in workspace · run_id=%s",
                            run_id,
                        )
                # run_eval emits started / question_completed / completed / failed
                # events on its own — no need for us to wrap those.
                await run_eval(service, workspace_path, run_id=run_id)
            except Exception:
                log.error(
                    "❌ knowledge.eval — background run failed · run_id=%s",
                    run_id,
                    exc_info=True,
                )
            finally:
                if owned:
                    await _close_if_owned(service, owned)

        # ``create_task`` is fire-and-forget here. The route returns immediately
        # so the UI gets ``run_id`` without blocking on the eval (which can take
        # minutes for a real corpus). The task ref is kept by the loop until done.
        asyncio.create_task(_runner())
        return _success({"run_id": run_id})
    except Exception as exc:
        log.error(
            "knowledge eval run failed to start · workspace=%s · %s",
            workspace_id,
            str(exc),
            exc_info=True,
        )
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
