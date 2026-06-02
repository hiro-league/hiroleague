"""Graphiti-backed temporal knowledge graph over the workspace knowledge corpus.

The pivot from the L3 Ladybug slice (see docs/knowledge-graphiti-pivot-design.md).
Graphiti owns the ingest + retrieval pipeline; this package holds the thin seams
the rest of the system talks to:

* :class:`GraphitiMemoryService` — bootstrap + ingest + (Phase 3) search, the single
  boundary behind which ``graphiti_core`` + Kuzu live (nothing else imports them).
* :class:`GraphitiEpisodeInput` / :func:`ingest_episodes` — chunk→episode ingest.
* The LLM / embedder adapters that route Graphiti through Hiro's model_factory.

The boundary is deliberately rip-out-able. NOTE: ``ladybug`` and ``kuzu`` cannot
coexist in one process (native lib clash), so the legacy Ladybug vertical was
removed wholesale — never re-introduce a ``ladybug`` import here.
"""

from __future__ import annotations

from .graphiti_adapters import (
    GraphitiEmbedderClient,
    GraphitiLLMClient,
    GraphitiLLMUsage,
    GraphitiModelSpec,
)
from .graphiti_ingest import (
    ALLOWED_SOURCE_ROLES,
    GraphitiEpisodeInput,
    GraphitiIngestStats,
    ingest_episodes,
)
from .graphiti_search import GraphitiExpansion, search_chunk_ids
from .graphiti_service import GraphitiMemoryService, graphiti_db_path

__all__ = [
    "ALLOWED_SOURCE_ROLES",
    "GraphitiEmbedderClient",
    "GraphitiEpisodeInput",
    "GraphitiExpansion",
    "GraphitiIngestStats",
    "GraphitiLLMClient",
    "GraphitiLLMUsage",
    "GraphitiMemoryService",
    "GraphitiModelSpec",
    "graphiti_db_path",
    "ingest_episodes",
    "search_chunk_ids",
]
