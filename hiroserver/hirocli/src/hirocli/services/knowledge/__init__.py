"""Knowledge service factory."""

from __future__ import annotations

from pathlib import Path

from .service import KnowledgeService


def create_knowledge_service(workspace_path: Path) -> KnowledgeService:
    """Create the workspace-local knowledge service."""

    return KnowledgeService(workspace_path)


__all__ = ["KnowledgeService", "create_knowledge_service"]
