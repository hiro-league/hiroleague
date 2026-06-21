"""Build-time configuration for ``KnowledgeAgentGraph``.

Mirrors ``runtime.agent_graph.config.ChatGraphConfig``: an immutable bundle of everything
``KnowledgeAgentGraph.build`` needs to wire one retrieval/answer graph. Per-build values
live here; long-lived services (workspace path, ledger sink, checkpointer) live on
``AgentServices`` and are passed to the builder's ``__init__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hirocli.domain.preferences import WorkspacePreferences


@dataclass(frozen=True)
class KnowledgeGraphConfig:
    """Per-build inputs for ``KnowledgeAgentGraph``.

    ``service`` is the retrieval engine (KnowledgeService or a test fake) that provides
    embedding/vector-search calls; ``prefs`` snapshots workspace preferences for this
    build; ``workspace_id`` namespaces Graphiti groups when present.
    """

    service: Any
    prefs: "WorkspacePreferences"
    workspace_id: str | None = None
