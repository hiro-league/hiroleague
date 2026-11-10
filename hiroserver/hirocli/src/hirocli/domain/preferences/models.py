"""Workspace preferences — single source of truth for configurable choices.

``preferences.json`` holds model default selections (canonical catalog ids), the AI profiles Hiro's
own jobs use (``jobs.JOB_PRESETS``), voice/audio, and memory settings. Provider secrets live in the credential
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
    default_image_profiles,
    iter_profile_refs,
    pref_field,
    seed_default_profiles,
)
from .jobs import JOB_PRESETS, JobPreset
from .models_ai import (
    AI_LOCAL_SERVER_KINDS,
    AI_MAX_FALLBACKS,
    AI_PLAN_PROVIDERS,
    AiPreferences,
    AiProfile,
    LocalServerSettings,
    ai_fallback_chain,
    check_ai_model_id,
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
from .models_voice import (
    VOICE_PROFILE_ID,
    VOICE_PROVIDERS,
    VoicePreferences,
    VoiceProfile,
    check_voice_model_id,
)
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
    # AI asks (Phase 7a)
    "AI_LOCAL_SERVER_KINDS",
    "AI_MAX_FALLBACKS",
    "VOICE_PROFILE_ID",
    "VOICE_PROVIDERS",
    "VoicePreferences",
    "VoiceProfile",
    "check_voice_model_id",
    "AI_PLAN_PROVIDERS",
    "AiPreferences",
    "AiProfile",
    "LocalServerSettings",
    "ai_fallback_chain",
    "check_ai_model_id",
    # Hiro's jobs (Phase 7b step 5)
    "JOB_PRESETS",
    "JobPreset",
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

    # 4 = Phase 7b step 5 (AI profiles for Hiro's jobs); older files are converted once on load
    # (``convert_v4``, called from ``io.load_preferences``).
    version: int = pref_field(read_only=True, default=4)
    llm: LLMPreferences = Field(default_factory=LLMPreferences)
    media: MediaPreferences = Field(default_factory=MediaPreferences)
    memory: MemoryPreferences = Field(default_factory=MemoryPreferences)
    knowledge: KnowledgePreferences = Field(default_factory=KnowledgePreferences)
    # Shared Graphiti graph engine — used by BOTH knowledge retrieval and agent memory
    # (mem0 → Graphiti, Phase 3b-2). Promoted from ``knowledge.graph`` to top level so it
    # reads as shared, not owned by knowledge. Qdrant knowledge prefs stay under ``knowledge``.
    graph: GraphPreferences = Field(default_factory=GraphPreferences)
    chat: ChatPreferences = Field(default_factory=ChatPreferences)
    image_profiles: dict[str, ImageProfile] = pref_field(
        save_skip=True,
        default_factory=default_image_profiles,
    )
    # Phase 7a: AI profiles + which profile each extension use asks. Edited by the Catalog's AI
    # tabs (like image_profiles by the Image Lab), so the Preferences page never sends it.
    ai: AiPreferences = pref_field(
        save_skip=True,
        default_factory=AiPreferences,
    )
    # Phase 7b: voice profiles, which profile each extension speech use speaks with (the Catalog's
    # Profiles tab edits both), and the spoken-clip cache size (Preferences → General → Spoken clips).
    voice: VoicePreferences = Field(default_factory=VoicePreferences)

    @model_validator(mode="after")
    def _validate_job_profiles(self) -> "WorkspacePreferences":
        # Phase 7b step 5 (replaces the tuning-profile reference check): every field marked
        # ``ai_profile_ref`` (Hiro's jobs) must name an existing AI profile whose model can be built
        # as a chat model — a plan tool (claude_code:* / codex:*) can't, so a job may not point
        # straight at one (a fallback chain may hold one; it is skipped at build time). Every
        # ``voice_profile_ref`` field must name an existing voice profile. Found by the marker.
        for path, profile_id in iter_profile_refs(self, "ai_profile_ref"):
            if profile_id is None:
                continue
            profile = self.ai.profiles.get(profile_id)
            if profile is None:
                raise ValueError(f"{path} points at an unknown AI profile {profile_id!r}")
            if profile.is_plan:
                raise ValueError(
                    f"{path} can't use AI profile {profile_id!r}: {profile.model} is a plan tool, and "
                    "Hiro's own jobs need an API or local model"
                )
        for path, profile_id in iter_profile_refs(self, "voice_profile_ref"):
            if profile_id is not None and profile_id not in self.voice.profiles:
                raise ValueError(f"{path} points at an unknown voice profile {profile_id!r}")
        return self

    @model_validator(mode="after")
    def _validate_image_profiles(self) -> "WorkspacePreferences":
        seed_default_profiles(self.image_profiles, default_image_profiles())
        if self.llm.default_image_profile not in self.image_profiles:
            raise ValueError(
                f"Unknown llm.default_image_profile: {self.llm.default_image_profile}"
            )
        return self
