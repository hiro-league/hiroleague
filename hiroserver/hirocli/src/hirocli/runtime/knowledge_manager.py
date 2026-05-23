"""KnowledgeManager — workspace knowledge runtime component.

Owns the ``KnowledgeService`` instance, the embedder reload preference
reactor, and the component lifecycle inside the server event loop.

Embedding-model lock enforcement lives in ``save_preferences`` (pre-write);
this manager only hot-reloads the embedder after an allowed change.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from hiro_commons.log import Logger

if TYPE_CHECKING:
    from hirocli.domain.credential_store import CredentialStore
    from hirocli.runtime.server_context import ServerContext
    from hirocli.services.knowledge import KnowledgeService

log = Logger.get("KNOWLEDGE.MGR")


class KnowledgeManager:
    """Active server component for workspace-local RAG ingest and retrieval."""

    def __init__(
        self,
        ctx: ServerContext,
        *,
        credential_store: CredentialStore | None = None,
    ) -> None:
        from hirocli.services.knowledge import create_knowledge_service
        from hirocli.services.knowledge.live_registry import maybe_recover_abandoned_work

        self._ctx = ctx
        self._closed = False
        self._service: KnowledgeService | None = None
        maybe_recover_abandoned_work(ctx.workspace_path)
        service = create_knowledge_service(
            ctx.workspace_path,
            prefs_provider=lambda: ctx.preferences.current,
            credential_store=credential_store,
        )
        self._service = service
        ctx.knowledge_manager = self

    @property
    def service(self) -> KnowledgeService:
        if self._service is None:
            raise RuntimeError("KnowledgeManager is closed")
        return self._service

    async def serve(self) -> None:
        """Register preference reactors and wait until shutdown."""
        self._register_preference_reactors()
        log.info("✅ KnowledgeManager started — workspace · ingest/search ready")
        try:
            await self._ctx.stop_event.wait()
        finally:
            await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        service = self._service
        self._service = None
        if self._ctx.knowledge_manager is self:
            self._ctx.knowledge_manager = None
        if service is not None:
            await service.close()

    def _register_preference_reactors(self) -> None:
        self._ctx.preference_reactor.on_change(
            "knowledge.default_embedding_model",
            self._embedding_reload_reactor,
            key="knowledge.embedding-reload",
            debounce_ms=0,
        )

    async def _embedding_reload_reactor(
        self,
        changed_workspace_path: Path,
        changes: dict[str, tuple[object, object]],
    ) -> None:
        transition = changes.get("knowledge.default_embedding_model")
        if transition is None or transition[0] == transition[1]:
            return
        if self._closed:
            return
        from hirocli.domain.credential_store import CredentialStore
        from hirocli.domain.workspace import workspace_id_for_path
        from hirocli.services.knowledge.embedder import resolve_knowledge_embedder

        prefs = self._ctx.preferences.current
        wid = workspace_id_for_path(changed_workspace_path)
        reload_cred_store = (
            CredentialStore(changed_workspace_path, wid) if wid is not None else None
        )
        new_embedder = await asyncio.to_thread(
            resolve_knowledge_embedder,
            changed_workspace_path,
            prefs.knowledge.default_embedding_model_resolved,
            credential_store=reload_cred_store,
        )
        await asyncio.to_thread(self.service.reload_embedder, new_embedder)
        log.info(
            "✅ Knowledge embedder reloaded — preferences",
            old=transition[0],
            new=transition[1],
            model=getattr(new_embedder, "model_name", None),
            dimension=new_embedder.dimension,
        )
