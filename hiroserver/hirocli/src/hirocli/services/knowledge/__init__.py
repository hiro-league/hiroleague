"""Knowledge service factory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .live_registry import count_knowledge_points
from .service import KnowledgeService

if TYPE_CHECKING:
    from hirocli.domain.credential_store import CredentialStore
    from hirocli.domain.preferences import WorkspacePreferences


def create_knowledge_service(
    workspace_path: Path,
    *,
    prefs: WorkspacePreferences | None = None,
    prefs_provider: Callable[[], WorkspacePreferences] | None = None,
    credential_store: CredentialStore | None = None,
) -> KnowledgeService:
    """Create the workspace-local knowledge service."""
    from hirocli.domain.preferences import load_preferences

    from .embedder import resolve_knowledge_embedder

    provider = prefs_provider
    if provider is None and prefs is not None:
        snapshot = prefs.model_copy(deep=True)
        provider = lambda: snapshot

    effective_prefs = provider() if provider is not None else load_preferences(workspace_path)
    embedder = resolve_knowledge_embedder(
        workspace_path,
        effective_prefs.knowledge.default_embedding_model_resolved,
        credential_store=credential_store,
    )
    return KnowledgeService(workspace_path, embedder=embedder, prefs_provider=provider)


__all__ = ["KnowledgeService", "count_knowledge_points", "create_knowledge_service"]
