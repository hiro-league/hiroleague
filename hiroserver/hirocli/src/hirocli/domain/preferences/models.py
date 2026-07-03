"""Workspace preferences — single source of truth for configurable choices.

``preferences.json`` holds LLM default selections (canonical catalog ids), profile-based
tuning, voice/audio, and memory settings. Provider secrets live in the credential
store (``providers.json`` + OS keyring), not here.

Storage: ``<workspace>/preferences.json`` — Pydantic model serialised to JSON.

The per-section models were split into sibling ``models_*`` modules for readability; this module
defines the root ``WorkspacePreferences`` and re-exports every section symbol (see ``__all__``) so
``from ...preferences.models import X`` and the package ``import *`` keep resolving exactly as before.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .defaults import (
    ImageProfile,
    TuningProfile,
    default_image_profiles,
    default_tuning_profiles,
    iter_tuning_profile_refs,
    pref_field,
    seed_default_profiles,
)
from .models_chat import DEFAULT_MAX_HISTORY_MESSAGES, ChatPreferences
from .models_graph import (
    GraphEvalPreferences,
    GraphObservability,
    GraphPreferences,
    GraphViewPreferences,
    KNOWLEDGE_GRAPH_EPISODE_SCOPES,
    KnowledgeGraphBackend,
    KnowledgeGraphEntityOntology,
    KnowledgeGraphRerankerPreferences,
    KnowledgeGraphSearchRecipe,
    KnowledgeGraphSearchScope,
    KnowledgeGraphTemporalDefault,
    RetrievalAgentLimits,
)
from .models_knowledge import (
    DEFAULT_KNOWLEDGE_EMBEDDING_MODEL,
    KnowledgeAnsweringPreferences,
    KnowledgeChunkingMarkdownPreferences,
    KnowledgeChunkingPreferences,
    KnowledgePreferences,
    KnowledgeRerankerPreferences,
    KnowledgeRetrievalPreferences,
    KnowledgeRewritePreferences,
)
from .models_llm import LLMPreferences
from .models_media import (
    MediaPreferences,
    ModalityFlags,
    default_input_modalities,
    default_output_modalities,
)
from .models_memory import (
    MemoryExtractionPreferences,
    MemoryPreferences,
    MemoryRetrievalPreferences,
    MemoryRetrievalRenderPreferences,
    MemorySearchPreferences,
)

__all__ = [
    # LLM
    "LLMPreferences",
    # Media
    "ModalityFlags",
    "MediaPreferences",
    "default_input_modalities",
    "default_output_modalities",
    # Memory
    "MemorySearchPreferences",
    "MemoryExtractionPreferences",
    "MemoryRetrievalPreferences",
    "MemoryRetrievalRenderPreferences",
    "MemoryPreferences",
    # Knowledge
    "DEFAULT_KNOWLEDGE_EMBEDDING_MODEL",
    "KnowledgeChunkingMarkdownPreferences",
    "KnowledgeChunkingPreferences",
    "KnowledgeRerankerPreferences",
    "KnowledgeRetrievalPreferences",
    "KnowledgeAnsweringPreferences",
    "KnowledgeRewritePreferences",
    "KnowledgePreferences",
    # Graph
    "KnowledgeGraphBackend",
    "KnowledgeGraphTemporalDefault",
    "KnowledgeGraphSearchRecipe",
    "KnowledgeGraphSearchScope",
    "KNOWLEDGE_GRAPH_EPISODE_SCOPES",
    "KnowledgeGraphEntityOntology",
    "GraphObservability",
    "KnowledgeGraphRerankerPreferences",
    "RetrievalAgentLimits",
    "GraphViewPreferences",
    "GraphEvalPreferences",
    "GraphPreferences",
    # Chat
    "DEFAULT_MAX_HISTORY_MESSAGES",
    "ChatPreferences",
    # Root
    "WorkspacePreferences",
]


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------


class WorkspacePreferences(BaseModel):
    """Root preferences object persisted as preferences.json."""

    version: int = pref_field(read_only=True, default=3)
    llm: LLMPreferences = Field(default_factory=LLMPreferences)
    media: MediaPreferences = Field(default_factory=MediaPreferences)
    memory: MemoryPreferences = Field(default_factory=MemoryPreferences)
    knowledge: KnowledgePreferences = Field(default_factory=KnowledgePreferences)
    # Shared Graphiti graph engine — used by BOTH knowledge retrieval and agent memory
    # (mem0 → Graphiti, Phase 3b-2). Promoted from ``knowledge.graph`` to top level so it
    # reads as shared, not owned by knowledge. Qdrant knowledge prefs stay under ``knowledge``.
    graph: GraphPreferences = Field(default_factory=GraphPreferences)
    chat: ChatPreferences = Field(default_factory=ChatPreferences)
    tuning_profiles: dict[str, TuningProfile] = pref_field(
        write_whole=True,
        default_factory=default_tuning_profiles,
    )
    image_profiles: dict[str, ImageProfile] = pref_field(
        save_skip=True,
        default_factory=default_image_profiles,
    )

    @model_validator(mode="after")
    def _validate_tuning_profiles(self) -> "WorkspacePreferences":
        seed_default_profiles(self.tuning_profiles, default_tuning_profiles())
        # Every field marked ``tuning_profile_ref`` (via ``pref_field``) must point at an existing
        # profile. References are discovered by the marker (``iter_tuning_profile_refs``), so a new
        # profile-referencing field is validated automatically — no hand-maintained list here.
        for path, profile_id in iter_tuning_profile_refs(self):
            if profile_id not in self.tuning_profiles:
                raise ValueError(f"Unknown tuning profile at {path}: {profile_id!r}")
        return self

    @model_validator(mode="after")
    def _validate_image_profiles(self) -> "WorkspacePreferences":
        seed_default_profiles(self.image_profiles, default_image_profiles())
        if self.llm.default_image_profile not in self.image_profiles:
            raise ValueError(
                f"Unknown llm.default_image_profile: {self.llm.default_image_profile}"
            )
        return self
