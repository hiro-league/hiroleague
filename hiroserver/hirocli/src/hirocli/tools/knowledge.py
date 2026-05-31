"""Workspace-local knowledge tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..domain.workspace import resolve_workspace
from ..services.knowledge import KnowledgeService, create_knowledge_service
from ..services.knowledge.live_registry import maybe_recover_abandoned_work
from .base import Tool, ToolParam


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def _runtime_workspace(runtime: Any | None) -> Path | None:
    if runtime is None:
        return None
    comm = getattr(runtime, "comm_manager", None)
    ctx = getattr(comm, "ctx", None)
    workspace_path = getattr(ctx, "workspace_path", None)
    return Path(workspace_path) if workspace_path is not None else None


def _runtime_service(runtime: Any | None) -> KnowledgeService | None:
    if runtime is None:
        return None
    comm = getattr(runtime, "comm_manager", None)
    ctx = getattr(comm, "ctx", None)
    manager = getattr(ctx, "knowledge_manager", None)
    if manager is None:
        return None
    return manager.service


def _resolve_service(runtime: Any | None, workspace: str | None) -> tuple[KnowledgeService, bool]:
    service = _runtime_service(runtime)
    if service is not None:
        return service, False
    workspace_path = _runtime_workspace(runtime) or _resolve_path(workspace)
    return create_knowledge_service(workspace_path), True


async def _close_if_owned(service: KnowledgeService, owned: bool) -> None:
    if owned:
        await service.close()


def _tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


class KnowledgeScanFolderTool(Tool):
    runtime = True
    name = "knowledge_scan_folder"
    description = "Scan a folder for knowledge-ingestible files"
    params = {
        "folder": ToolParam(str, "Folder path to scan"),
        "recursive": ToolParam(bool, "Scan subfolders recursively", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, folder: str, recursive: bool = True, workspace: str | None = None) -> Any:
        return asyncio.run(self.execute_async(folder=folder, recursive=recursive, workspace=workspace))

    async def execute_async(self, folder: str, recursive: bool = True, workspace: str | None = None) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.scan_folder(folder, recursive=recursive)
        finally:
            await _close_if_owned(service, owned)


class KnowledgeIngestTool(Tool):
    runtime = True
    name = "knowledge_ingest"
    description = "Ingest selected markdown files into the workspace-local knowledge index"
    params = {
        # list[str] so LangChain/Gemini tool schemas include items.type (bare list breaks Gemini).
        "paths": ToolParam(list[str], "Absolute file paths to ingest"),
        "owner_kind": ToolParam(str, "Owner kind: system, character, or user", required=False),
        "owner_id": ToolParam(str, "Owner id; use 0 for system", required=False),
        "category_id": ToolParam(int, "Category id", required=False),
        "subcategory_id": ToolParam(int, "Subcategory id", required=False),
        "tags": ToolParam(list[str], "Tags to attach", required=False),
        "wait": ToolParam(bool, "Wait for the ingest job to finish", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        paths: list[str],
        owner_kind: str = "system",
        owner_id: str = "0",
        category_id: int | None = None,
        subcategory_id: int | None = None,
        tags: list[str] | str | None = None,
        wait: bool = True,
        workspace: str | None = None,
    ) -> Any:
        return asyncio.run(
            self.execute_async(
                paths=paths,
                owner_kind=owner_kind,
                owner_id=owner_id,
                category_id=category_id,
                subcategory_id=subcategory_id,
                tags=tags,
                wait=wait,
                workspace=workspace,
            )
        )

    async def execute_async(
        self,
        paths: list[str],
        owner_kind: str = "system",
        owner_id: str = "0",
        category_id: int | None = None,
        subcategory_id: int | None = None,
        tags: list[str] | str | None = None,
        wait: bool = False,
        workspace: str | None = None,
    ) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            kwargs = {
                "owner_kind": owner_kind or "system",
                "owner_id": owner_id or "0",
                "category_id": category_id,
                "subcategory_id": subcategory_id,
                "tags": _tags(tags),
            }
            maybe_recover_abandoned_work(service.workspace_path)
            # Mirror admin ingest: ephemeral services must wait before close.
            effective_wait = wait or owned
            if effective_wait:
                return await service.ingest_and_wait(paths, **kwargs)
            return await service.start_ingest(paths, **kwargs)
        finally:
            if owned:
                await _close_if_owned(service, owned)


class KnowledgeJobStatusTool(Tool):
    runtime = True
    name = "knowledge_job_status"
    description = "Return persisted status for a knowledge ingestion job"
    params = {
        "job_id": ToolParam(str, "Knowledge ingestion job id"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, job_id: str, workspace: str | None = None) -> Any:
        return asyncio.run(self.execute_async(job_id=job_id, workspace=workspace))

    async def execute_async(self, job_id: str, workspace: str | None = None) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.job_status(job_id)
        finally:
            await _close_if_owned(service, owned)


class KnowledgeSearchTool(Tool):
    runtime = True
    name = "knowledge_search"
    description = "Vector-search ingested knowledge chunks"
    params = {
        "query": ToolParam(str, "Search query"),
        "top_k": ToolParam(int, "Maximum number of chunks to return", required=False),
        "min_score": ToolParam(float, "Minimum vector score", required=False),
        "filters": ToolParam(dict, "Qdrant payload filters", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
        workspace: str | None = None,
    ) -> Any:
        return asyncio.run(
            self.execute_async(query=query, top_k=top_k, min_score=min_score, filters=filters, workspace=workspace)
        )

    async def execute_async(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
        workspace: str | None = None,
    ) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.search(query, top_k=top_k, min_score=min_score, filters=filters)
        finally:
            await _close_if_owned(service, owned)


# L3 — graph_mode values for KnowledgeAnswerTool.
# "off" / "on" return a KnowledgeAnswerResult; "compare" returns a
# KnowledgeAnswerComparison (two results side-by-side, ran concurrently).
GRAPH_MODE_OFF = "off"
GRAPH_MODE_ON = "on"
GRAPH_MODE_COMPARE = "compare"
GRAPH_MODES = (GRAPH_MODE_OFF, GRAPH_MODE_ON, GRAPH_MODE_COMPARE)


class KnowledgeAnswerTool(Tool):
    runtime = True
    name = "knowledge_answer"
    description = "Answer a question against ingested knowledge with cited sources"
    params = {
        "query": ToolParam(str, "Question to answer"),
        "top_k": ToolParam(int, "Maximum chunks to retrieve", required=False),
        "min_score": ToolParam(float, "Minimum vector score", required=False),
        "filters": ToolParam(dict, "Knowledge filters", required=False),
        "rewrite": ToolParam(
            bool,
            "Run the LLM query-rewrite step (normalize + extract entities). "
            "Required for graph_mode='on'/'compare' to have effect.",
            required=False,
        ),
        "graph_mode": ToolParam(
            str,
            "L3 retrieval mode: 'off' (today's flat hybrid+rerank), 'on' "
            "(graph_expand focuses Qdrant on chunks linked to query entities), or "
            "'compare' (runs both concurrently and returns a side-by-side result). "
            "Default 'off'.",
            required=False,
        ),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        query: str,
        top_k: int | None = None,
        min_score: float | None = None,
        filters: dict[str, Any] | None = None,
        rewrite: bool = False,
        graph_mode: str = GRAPH_MODE_OFF,
        workspace: str | None = None,
    ) -> Any:
        return asyncio.run(
            self.execute_async(
                query=query,
                top_k=top_k,
                min_score=min_score,
                filters=filters,
                rewrite=rewrite,
                graph_mode=graph_mode,
                workspace=workspace,
            )
        )

    async def execute_async(
        self,
        query: str,
        top_k: int | None = None,
        min_score: float | None = None,
        filters: dict[str, Any] | None = None,
        rewrite: bool = False,
        graph_mode: str = GRAPH_MODE_OFF,
        workspace: str | None = None,
    ) -> Any:
        # Validate mode at the Tool boundary so CLI/HTTP callers get a clear
        # error instead of silently falling through to 'off'.
        mode = (graph_mode or "").strip().lower()
        if mode not in GRAPH_MODES:
            raise ValueError(
                f"graph_mode must be one of {GRAPH_MODES}, got {graph_mode!r}"
            )

        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            if mode == GRAPH_MODE_COMPARE:
                return await service.compare(
                    query,
                    top_k=top_k,
                    min_score=min_score,
                    filters=filters,
                    workspace_id=workspace,
                    rewrite=rewrite,
                )
            return await service.answer(
                query,
                top_k=top_k,
                min_score=min_score,
                filters=filters,
                workspace_id=workspace,
                rewrite=rewrite,
                use_graph=(mode == GRAPH_MODE_ON),
            )
        finally:
            await _close_if_owned(service, owned)


class KnowledgeListDocumentsTool(Tool):
    runtime = True
    name = "knowledge_list_documents"
    description = "List ingested knowledge documents"
    params = {
        "status": ToolParam(str, "Document status", required=False),
        "owner_kind": ToolParam(str, "Owner kind filter", required=False),
        "owner_id": ToolParam(str, "Owner id filter", required=False),
        "category_id": ToolParam(int, "Category id filter", required=False),
        "subcategory_id": ToolParam(int, "Subcategory id filter", required=False),
        "tag": ToolParam(str, "Tag filter", required=False),
        "source_type": ToolParam(str, "Source type filter", required=False),
        "title": ToolParam(str, "Title substring filter", required=False),
        "limit": ToolParam(int, "Maximum rows", required=False),
        "offset": ToolParam(int, "Rows to skip", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, **kwargs: Any) -> Any:
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(
        self,
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
        workspace: str | None = None,
    ) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.list_documents(
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
        finally:
            await _close_if_owned(service, owned)


class KnowledgeDeleteDocumentTool(Tool):
    runtime = True
    agent_default = False
    name = "knowledge_delete_document"
    description = "Delete a document from the knowledge index without touching the source file"
    params = {
        "document_id": ToolParam(str, "Knowledge document id"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, document_id: str, workspace: str | None = None) -> Any:
        return asyncio.run(self.execute_async(document_id=document_id, workspace=workspace))

    async def execute_async(self, document_id: str, workspace: str | None = None) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.delete_document(document_id)
        finally:
            await _close_if_owned(service, owned)


class KnowledgeReingestDocumentTool(Tool):
    runtime = True
    agent_default = False
    name = "knowledge_reingest_document"
    description = "Re-read and re-index an existing knowledge document"
    params = {
        "document_id": ToolParam(str, "Knowledge document id"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, document_id: str, workspace: str | None = None) -> Any:
        return asyncio.run(self.execute_async(document_id=document_id, workspace=workspace))

    async def execute_async(self, document_id: str, workspace: str | None = None) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.reingest_document(document_id)
        finally:
            await _close_if_owned(service, owned)


class KnowledgeUpdateDocumentMetadataTool(Tool):
    runtime = True
    name = "knowledge_update_document_metadata"
    description = "Update knowledge document owner, category, and tags"
    params = {
        "document_id": ToolParam(str, "Knowledge document id"),
        "owner_kind": ToolParam(str, "Owner kind"),
        "owner_id": ToolParam(str, "Owner id"),
        "category_id": ToolParam(int, "Category id", required=False),
        "subcategory_id": ToolParam(int, "Subcategory id", required=False),
        "tags": ToolParam(list[str], "Tags", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, **kwargs: Any) -> Any:
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(
        self,
        document_id: str,
        owner_kind: str,
        owner_id: str,
        category_id: int | None = None,
        subcategory_id: int | None = None,
        tags: list[str] | str | None = None,
        workspace: str | None = None,
    ) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.update_document_metadata(
                document_id,
                owner_kind=owner_kind,
                owner_id=owner_id,
                category_id=category_id,
                subcategory_id=subcategory_id,
                tags=_tags(tags),
            )
        finally:
            await _close_if_owned(service, owned)


class KnowledgeGetDocumentTool(Tool):
    runtime = True
    name = "knowledge_get_document"
    description = "Get one knowledge document and its vector-store chunks"
    params = {
        "document_id": ToolParam(str, "Knowledge document id"),
        "chunk_limit": ToolParam(int, "Maximum chunks to return", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, document_id: str, chunk_limit: int = 100, workspace: str | None = None) -> Any:
        return asyncio.run(
            self.execute_async(document_id=document_id, chunk_limit=chunk_limit, workspace=workspace)
        )

    async def execute_async(
        self,
        document_id: str,
        chunk_limit: int = 100,
        workspace: str | None = None,
    ) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.get_document(document_id, chunk_limit=chunk_limit)
        finally:
            await _close_if_owned(service, owned)


class _KnowledgeWorkspaceRuntimeTool(Tool):
    """Shared runtime wiring for workspace-scoped knowledge read tools."""

    runtime = True
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, workspace: str | None = None, **kwargs: Any) -> Any:
        return asyncio.run(self.execute_async(workspace=workspace, **kwargs))


class KnowledgeListTagsTool(_KnowledgeWorkspaceRuntimeTool):
    name = "knowledge_list_tags"
    description = "List knowledge tags"

    async def execute_async(self, workspace: str | None = None, **kwargs: Any) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.list_tags()
        finally:
            await _close_if_owned(service, owned)


class KnowledgeListCategoriesTool(_KnowledgeWorkspaceRuntimeTool):
    name = "knowledge_list_categories"
    description = "List knowledge categories"

    async def execute_async(self, workspace: str | None = None, **kwargs: Any) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.list_categories()
        finally:
            await _close_if_owned(service, owned)


class KnowledgeCreateCategoryTool(Tool):
    runtime = True
    name = "knowledge_create_category"
    description = "Create a knowledge category or subcategory"
    params = {
        "name": ToolParam(str, "Category name"),
        "parent_id": ToolParam(int, "Parent category id for subcategories", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(
        self,
        name: str,
        parent_id: int | None = None,
        workspace: str | None = None,
    ) -> Any:
        return asyncio.run(self.execute_async(name=name, parent_id=parent_id, workspace=workspace))

    async def execute_async(
        self,
        name: str,
        parent_id: int | None = None,
        workspace: str | None = None,
    ) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.create_category(name, parent_id=parent_id)
        finally:
            await _close_if_owned(service, owned)


class KnowledgeCreateTagTool(Tool):
    runtime = True
    name = "knowledge_create_tag"
    description = "Create a knowledge tag"
    params = {
        "name": ToolParam(str, "Tag name"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, name: str, workspace: str | None = None) -> Any:
        return asyncio.run(self.execute_async(name=name, workspace=workspace))

    async def execute_async(self, name: str, workspace: str | None = None) -> Any:
        service, owned = _resolve_service(getattr(self, "_runtime", None), workspace)
        try:
            return await service.create_tag(name)
        finally:
            await _close_if_owned(service, owned)
