"""Memory service factory."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hiro_commons.log import Logger

from hirocli.domain.memory import MemoryService

if TYPE_CHECKING:
    from hirocli.domain.credential_store import CredentialStore
    from hirocli.domain.preferences import WorkspacePreferences

log = Logger.get("SVC.MEMORY")


def create_memory_service(
    workspace_path: Path,
    prefs: "WorkspacePreferences",
    *,
    credential_store: "CredentialStore | None" = None,
) -> MemoryService | None:
    """Build the long-term memory service when enabled."""
    memory_prefs = getattr(prefs, "memory", None)
    if not getattr(memory_prefs, "enabled", False):
        log.info("Memory service disabled by preferences")
        return None
    llm_model = str(getattr(memory_prefs, "default_llm", "") or "").strip()
    embedding_model = str(getattr(memory_prefs, "default_embedding_model", "") or "").strip()
    if not llm_model or not embedding_model:
        log.error(
            "Memory service disabled - set memory.default_llm and memory.default_embedding_model",
        )
        return None

    from .service import Mem0MemoryService

    try:
        from hirocli.domain.preferences import resolve_memory_llm

        llm = resolve_memory_llm(
            prefs,
            workspace_path,
            credential_store=credential_store,
        )
        if llm is None:
            log.error("Memory service disabled - memory LLM is unavailable")
            return None
        return Mem0MemoryService(
            workspace_path=workspace_path,
            llm_model=llm.model_id,
            llm_tuning=llm,
            embedding_model=embedding_model,
            credential_store=credential_store,
            search_prefs=getattr(memory_prefs, "search", None),
            reranker_prefs=getattr(memory_prefs, "reranker", None),
        )
    except ImportError as exc:
        log.warning(
            "Memory service unavailable - install mem0ai and qdrant-client",
            error=str(exc),
        )
        return None
    except ValueError as exc:
        log.error("Memory service disabled - invalid memory model preferences", error=str(exc))
        return None
