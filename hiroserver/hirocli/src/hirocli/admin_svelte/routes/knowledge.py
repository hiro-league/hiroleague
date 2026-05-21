"""Admin routes for workspace-local knowledge ingest/search/browse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from hiro_commons.log import Logger

from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import envelope_failure
from hirocli.domain.workspace import resolve_workspace
from hirocli.services.knowledge import KnowledgeService, create_knowledge_service

log = Logger.get("ADMIN.KNOWLEDGE")

knowledge_router = APIRouter()


def _success(data: Any) -> dict[str, Any]:
    return {"ok": True, "error": None, "data": data}


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
    return True, getattr(ctx, "knowledge_service", None)


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


class IngestBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    owner_kind: str = "system"
    owner_id: str = "0"
    category_id: int | None = None
    subcategory_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    wait: bool = False


class SearchBody(BaseModel):
    query: str
    top_k: int = 10
    min_score: float = 0.0
    filters: dict[str, Any] = Field(default_factory=dict)


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
                )
            )
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge search failed", error=str(exc), exc_info=True)
        return envelope_failure(str(exc))


@knowledge_router.get("/knowledge/documents")
async def list_documents(
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
    status: str | None = None,
    owner_kind: str | None = None,
    owner_id: str | None = None,
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


@knowledge_router.get("/knowledge/documents/{document_id}")
async def get_document(
    document_id: str,
    workspace_id: SelectedWorkspaceIdDep,
    request: Request,
    chunk_limit: int = 100,
) -> dict[str, Any]:
    try:
        service, owned = await _resolve_service(request, workspace_id)
        try:
            return _success(await service.get_document(document_id, chunk_limit=chunk_limit))
        finally:
            await _close_if_owned(service, owned)
    except Exception as exc:
        log.error("knowledge get document failed", document_id=document_id, error=str(exc), exc_info=True)
        return envelope_failure(str(exc))
