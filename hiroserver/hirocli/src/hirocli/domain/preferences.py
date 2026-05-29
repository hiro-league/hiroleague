"""Workspace preferences — single source of truth for configurable choices.

``preferences.json`` holds LLM default selections (canonical catalog ids), profile-based
tuning, voice/audio, and memory settings. Provider secrets live in the credential
store (``providers.json`` + OS keyring), not here.

Storage: ``<workspace>/preferences.json`` — Pydantic model serialised to JSON.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from hiro_commons.constants.storage import PREFERENCES_FILENAME

from .credential_store import CredentialStore
from .events import DomainEvent, DomainEventType, get_domain_event_bus

logger = logging.getLogger(__name__)


class PreferenceSection(BaseModel):
    """First-level preferences section metadata for admin presentation."""

    key: str
    label: str
    description: str = ""


PREFERENCE_SECTIONS: tuple[PreferenceSection, ...] = (
    PreferenceSection(
        key="llm",
        label="Models",
        description="Workspace model defaults and tuning profile selection.",
    ),
    PreferenceSection(
        key="media",
        label="Media",
        description="Workspace input and output modality policy.",
    ),
    PreferenceSection(
        key="memory",
        label="Agent Memory",
        description="Long-term agent memory settings.",
    ),
    PreferenceSection(
        key="knowledge",
        label="Knowledge",
        description="Workspace-local RAG ingest, retrieval, and answering settings.",
    ),
    PreferenceSection(
        key="chat",
        label="Agent",
        description="How the character answers in chat — general instructions and citation behavior.",
    ),
)


def _notify_preferences_saved(
    workspace_path: Path,
    prefs: "WorkspacePreferences",
    *,
    effective_changes: dict[str, tuple[Any, Any]] | None = None,
) -> None:
    """Publish that ``preferences.json`` was written.

    ``effective_changes`` maps leaf dot-paths to ``(old, new)`` tuples for values
    that actually differed between the previous and new persisted state. Empty
    dict ⇒ a no-op save (still published so subscribers can observe writes).
    """
    get_domain_event_bus().publish(
        DomainEvent(
            type=DomainEventType.PREFERENCES_SAVED,
            workspace_path=workspace_path,
            payload={
                "prefs": prefs,
                "effective_changes": dict(effective_changes or {}),
            },
        )
    )


def compute_effective_changes(
    old: "WorkspacePreferences | None",
    new: "WorkspacePreferences",
) -> dict[str, tuple[Any, Any]]:
    """Deep-diff two preferences objects, return ``{dotted_path: (old, new)}``.

    Walks both ``model_dump(mode="python")`` trees in lockstep. Leaves are any
    non-dict value (scalars, lists, ``None``); dicts of dicts recurse. When a
    subtree exists on only one side, every leaf below it is reported with
    ``None`` on the missing side.

    Used by ``save_preferences`` to publish a precise change set on the domain
    bus so reactors only fire on real value transitions.
    """
    old_data = old.model_dump(mode="python") if old is not None else {}
    new_data = new.model_dump(mode="python")
    changes: dict[str, tuple[Any, Any]] = {}
    _diff_into(changes, "", old_data, new_data)
    return changes


def _diff_into(
    out: dict[str, tuple[Any, Any]],
    prefix: str,
    old: Any,
    new: Any,
) -> None:
    # Recurse whenever either side is a dict so a missing subtree (old=None,
    # new={...} or vice versa) still resolves to leaf-level (path, old, new)
    # tuples — reactors target leaves, never whole subtrees.
    if isinstance(old, dict) or isinstance(new, dict):
        old_dict = old if isinstance(old, dict) else {}
        new_dict = new if isinstance(new, dict) else {}
        keys = set(old_dict.keys()) | set(new_dict.keys())
        for key in keys:
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            _diff_into(out, child_prefix, old_dict.get(key), new_dict.get(key))
        return
    if old != new:
        out[prefix] = (old, new)

# ---------------------------------------------------------------------------
# LLM selection (canonical catalog ids: ``openai:gpt-5.4``)
# ---------------------------------------------------------------------------

LLMPurpose = Literal["chat", "stt", "tts"]
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high"]


class ModelTuning(BaseModel):
    """Provider-neutral runtime model tuning."""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    thinking: ThinkingLevel | None = None


class TuningProfile(ModelTuning):
    """Named tuning preset shared by chat, memory, and knowledge answering."""

    label: str = Field(default="", min_length=1)
    locked: bool = False


DEFAULT_CHAT_TUNING_PROFILE_ID = "balanced_chat"
DEFAULT_MEMORY_TUNING_PROFILE_ID = "memory_extraction"
DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID = "knowledge_answering"
DEFAULT_KNOWLEDGE_REWRITE_TUNING_PROFILE_ID = "knowledge_rewrite"


def default_tuning_profiles() -> dict[str, TuningProfile]:
    return {
        DEFAULT_CHAT_TUNING_PROFILE_ID: TuningProfile(
            label="Balanced chat",
            locked=True,
            temperature=0.7,
            max_tokens=2048,
            thinking=None,
        ),
        DEFAULT_MEMORY_TUNING_PROFILE_ID: TuningProfile(
            label="Memory extraction",
            locked=True,
            temperature=0,
            max_tokens=8192,
            thinking="low",
        ),
        DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID: TuningProfile(
            label="Knowledge answering",
            locked=True,
            temperature=0.2,
            max_tokens=1600,
            thinking=None,
        ),
        DEFAULT_KNOWLEDGE_REWRITE_TUNING_PROFILE_ID: TuningProfile(
            label="Knowledge query rewrite",
            locked=True,
            # Deterministic normalization + keyword extraction. Reasoning is disabled on
            # purpose: a reasoning model would spend the token budget thinking and never emit
            # the structured JSON. max_tokens only needs to cover the small JSON envelope.
            temperature=0.0,
            max_tokens=1024,
            thinking="off",
        ),
    }


class LLMPreferences(BaseModel):
    """Which catalog models to use when the workspace has credentials for them."""

    default_chat: str | None = None
    default_stt: str | None = None
    default_tts: str | None = None
    default_tuning_profile: str = DEFAULT_CHAT_TUNING_PROFILE_ID


# ---------------------------------------------------------------------------
# Media policy / capabilities
# ---------------------------------------------------------------------------


class ModalityFlags(BaseModel):
    voice: bool = False
    image: bool = False
    video: bool = False
    file: bool = False


def default_input_modalities() -> ModalityFlags:
    return ModalityFlags(voice=True)


def default_output_modalities() -> ModalityFlags:
    return ModalityFlags()


class MediaPreferences(BaseModel):
    input: ModalityFlags = Field(default_factory=default_input_modalities)
    output: ModalityFlags = Field(default_factory=default_output_modalities)


# ---------------------------------------------------------------------------
# Short-term memory
# ---------------------------------------------------------------------------


# Conversation-history window kept per turn (short-term context for trim_history). Lives under
# ``chat`` (it feeds the chat answer + memory/knowledge retrieval), not under ``memory``.
DEFAULT_MAX_HISTORY_MESSAGES = 6

DEFAULT_MEMORY_SEARCH_TOP_K = 8
DEFAULT_MEMORY_SEARCH_THRESHOLD = 0.1
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class MemorySearchPreferences(BaseModel):
    """Retrieval-time tuning for ``MemoryService.search``."""

    # When false, ``memory_search`` is skipped — no long-term memory is injected before the reply
    # (independent of extraction). No-op unless ``memory.enabled`` (models configured).
    enabled: bool = True
    top_k: int = Field(default=DEFAULT_MEMORY_SEARCH_TOP_K, ge=1, le=100)
    # Mem0 fused score in [0, 1] (semantic + BM25 + entity boost). Rows below
    # this score are dropped pre-rerank; 0.0 disables the gate.
    threshold: float = Field(default=DEFAULT_MEMORY_SEARCH_THRESHOLD, ge=0.0, le=1.0)
    # Per-call default for the rerank pass. Effective only when
    # ``reranker.enabled`` is true; otherwise mem0 has no reranker to call.
    rerank: bool = False


class MemoryExtractionPreferences(BaseModel):
    """Whether the agent stores new long-term memories after a reply (memory_out)."""

    # When false, ``_store_turn_memory`` is skipped — memory becomes read-only (it stops growing)
    # while search may still inject existing memories. No-op unless ``memory.enabled``.
    enabled: bool = True


class MemoryRerankerPreferences(BaseModel):
    """Local cross-encoder reranker (mem0 ``sentence_transformer`` provider).

    Disabled by default — enabling requires ``sentence-transformers`` and pulls
    the cross-encoder weights on first use.
    """

    enabled: bool = False
    model: str = Field(default=DEFAULT_RERANKER_MODEL, min_length=1)
    # ``None`` lets sentence-transformers pick (CUDA if available, else CPU).
    device: str | None = None
    batch_size: int = Field(default=32, ge=1, le=512)


class MemoryPreferences(BaseModel):
    """Agent memory settings."""

    enabled: bool = False
    default_llm: str | None = None
    default_embedding_model: str | None = None
    default_tuning_profile: str = DEFAULT_MEMORY_TUNING_PROFILE_ID
    search: MemorySearchPreferences = Field(default_factory=MemorySearchPreferences)
    extraction: MemoryExtractionPreferences = Field(default_factory=MemoryExtractionPreferences)
    reranker: MemoryRerankerPreferences = Field(default_factory=MemoryRerankerPreferences)

    @model_validator(mode="after")
    def _disable_without_models(self) -> "MemoryPreferences":
        if not self.default_llm or not self.default_embedding_model:
            self.enabled = False
        return self


# ---------------------------------------------------------------------------
# Workspace-local knowledge
# ---------------------------------------------------------------------------

DEFAULT_KNOWLEDGE_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Default sparse model for hybrid retrieval. Duplicated from services.knowledge.constants so
# the domain layer does not import the services layer (same pattern as the embedding default).
DEFAULT_KNOWLEDGE_SPARSE_MODEL = "Qdrant/bm25"

# System prompt for the optional query-rewrite step. Editable in preferences; the rewrite node
# falls back to this constant when the stored prompt is blank. Scope is normalization +
# literal-keyword extraction; the conversation-history clause is a no-op for admin Ask (which
# passes no history) and active in chat (where history is supplied for reference resolution).
DEFAULT_KNOWLEDGE_REWRITE_PROMPT = (
    "Rewrite the user's question into one clean, standalone search query. "
    "Fix typos and normalize informal or dialectal phrasing into clear formal language, "
    "but do NOT change the meaning or add information that is not in the question. "
    "If a conversation is provided, resolve references (pronouns, 'the second one', "
    "'his brother') against it so the query stands alone without the conversation. "
    "Copy proper nouns, names, dates, and identifiers VERBATIM into `keywords` — never "
    "translate or 'correct' a name. "
    "Set `knowledge_needed` to false when the message is just a greeting, farewell, thanks, "
    "acknowledgement, or small talk and clearly does not ask for stored information; otherwise "
    "true. Do not invent facts or answer the question."
)


class KnowledgeChunkingMarkdownPreferences(BaseModel):
    respect_headings: bool = True


class KnowledgeChunkingPreferences(BaseModel):
    chunk_size: int = Field(default=1200, ge=200, le=8000)
    chunk_overlap: int = Field(default=150, ge=0, le=2000)
    # Prefix each chunk's *embedded* text (dense + BM25) with its document title and heading
    # breadcrumb so every chunk carries structural context — including heading-less continuation
    # pieces. Ingest-time only (the stored payload text is unchanged); flipping it needs a re-ingest.
    embed_structural_context: bool = True
    markdown: KnowledgeChunkingMarkdownPreferences = Field(default_factory=KnowledgeChunkingMarkdownPreferences)

    @model_validator(mode="after")
    def _overlap_less_than_size(self) -> "KnowledgeChunkingPreferences":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("knowledge.chunking.chunk_overlap must be smaller than chunk_size")
        return self


class KnowledgeRetrievalPreferences(BaseModel):
    top_k: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    # Hybrid retrieval: fuse the dense vector with a BM25 sparse vector via Qdrant RRF.
    # Sparse vectors are always stored at ingest, so this is a pure query-time toggle
    # (flipping it needs no re-ingest). When enabled, ``min_score`` applies as the cosine
    # threshold on the dense branch; the BM25 branch is rank-fused (its scores are not 0-1).
    hybrid: bool = True
    sparse_model: str = Field(default=DEFAULT_KNOWLEDGE_SPARSE_MODEL, min_length=1)
    # Candidates pulled per branch before fusion; should be >= top_k so RRF has overlap.
    prefetch_limit: int = Field(default=40, ge=1, le=500)


class KnowledgeAnsweringPreferences(BaseModel):
    model: str | None = None
    cite_sources: bool = True
    language_policy: Literal["match_query", "prefer_english", "prefer_arabic"] = "match_query"


class KnowledgeRewritePreferences(BaseModel):
    # Optional LLM query rewrite for the Ask tab: normalize + extract literal keywords before
    # retrieval. Reuses the resolved answering model. ``default_on`` seeds the Ask-tab toggle.
    prompt: str = DEFAULT_KNOWLEDGE_REWRITE_PROMPT
    default_on: bool = False


class KnowledgePreferences(BaseModel):
    default_embedding_model: str | None = None
    default_tuning_profile: str = DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID
    chunking: KnowledgeChunkingPreferences = Field(default_factory=KnowledgeChunkingPreferences)
    retrieval: KnowledgeRetrievalPreferences = Field(default_factory=KnowledgeRetrievalPreferences)
    answering: KnowledgeAnsweringPreferences = Field(default_factory=KnowledgeAnsweringPreferences)
    rewrite: KnowledgeRewritePreferences = Field(default_factory=KnowledgeRewritePreferences)

    @property
    def default_embedding_model_resolved(self) -> str:
        return self.default_embedding_model or DEFAULT_KNOWLEDGE_EMBEDDING_MODEL


# General chat-answering instructions injected (in the current user turn) ahead of the question.
# Authored as Markdown in the Admin → Preferences → Agent editor; sent to the model as text.
# Not knowledge-specific — these are how the character should answer, regardless of retrieval.
DEFAULT_CHAT_INSTRUCTIONS = (
    "## Instructions\n"
    "- This is a conversation between you (the character) and the user.\n"
    "- Use the **Knowledge retrieved** (from the workspace knowledge base) and "
    "**Memories retrieved** below as optional background.\n"
    "- You choose what is relevant — you do not need to use all, or any, of it.\n"
    "- source rank and score suggest the search relevancy of the knowledge item to the "
    "user message/context\n"
    "- Answer **Last User Message** in your own style."
)


class ChatPreferences(BaseModel):
    """Chat-answering behavior (the chat model answers; not the Ask knowledge answerer)."""

    # General answering instructions (Markdown), injected into the current user turn. Editable in
    # the Admin → Preferences → Agent tab. Broader than knowledge — may carry any answering guidance.
    instructions: str = DEFAULT_CHAT_INSTRUCTIONS
    # Conversation-history window kept per turn by trim_history (short-term context). Feeds the chat
    # answer + memory/knowledge retrieval — a chat-answering concern, not a long-term memory one.
    max_messages: int = Field(default=DEFAULT_MAX_HISTORY_MESSAGES, ge=1, le=100)
    # When on, chat instructs the model to cite knowledge inline as [n] AND surfaces the source list
    # to the client (citation bridge on graph.reply.completed). Moved here from knowledge.chat.
    cite_sources: bool = False
    # Placeholder until a real per-character/per-chat language setting exists; chat retrieval does
    # not constrain answer language today (the persona decides). Kept so it can be threaded later.
    preferred_answering_language: str = "en"


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------


class WorkspacePreferences(BaseModel):
    """Root preferences object persisted as preferences.json."""

    version: int = 3
    llm: LLMPreferences = Field(default_factory=LLMPreferences)
    media: MediaPreferences = Field(default_factory=MediaPreferences)
    memory: MemoryPreferences = Field(default_factory=MemoryPreferences)
    knowledge: KnowledgePreferences = Field(default_factory=KnowledgePreferences)
    chat: ChatPreferences = Field(default_factory=ChatPreferences)
    tuning_profiles: dict[str, TuningProfile] = Field(default_factory=default_tuning_profiles)

    @model_validator(mode="after")
    def _validate_tuning_profiles(self) -> "WorkspacePreferences":
        defaults = default_tuning_profiles()
        for profile_id, default_profile in defaults.items():
            current = self.tuning_profiles.get(profile_id)
            if current is None:
                self.tuning_profiles[profile_id] = default_profile
            else:
                current.locked = True
                if not current.label.strip():
                    current.label = default_profile.label
        if self.llm.default_tuning_profile not in self.tuning_profiles:
            raise ValueError(
                f"Unknown llm.default_tuning_profile: {self.llm.default_tuning_profile}"
            )
        if self.memory.default_tuning_profile not in self.tuning_profiles:
            raise ValueError(
                f"Unknown memory.default_tuning_profile: {self.memory.default_tuning_profile}"
            )
        if self.knowledge.default_tuning_profile not in self.tuning_profiles:
            raise ValueError(
                f"Unknown knowledge.default_tuning_profile: {self.knowledge.default_tuning_profile}"
            )
        return self


# ---------------------------------------------------------------------------
# I/O — the only code that touches the file
# ---------------------------------------------------------------------------


def preferences_file(workspace_path: Path) -> Path:
    return workspace_path / PREFERENCES_FILENAME


def load_preferences(workspace_path: Path) -> WorkspacePreferences:
    f = preferences_file(workspace_path)
    if f.exists():
        return WorkspacePreferences.model_validate_json(f.read_text(encoding="utf-8"))
    # Missing file: use structural defaults and persist so the workspace always has a real prefs file.
    prefs = WorkspacePreferences()
    save_preferences(workspace_path, prefs)
    logger.info(
        "⚠️ Persisted preferences — workspace · defaults (preferences.json was missing)",
        extra={
            "content_hint": "structural defaults written to disk",
            "workspace_path": str(workspace_path.resolve()),
        },
    )
    return prefs


def save_preferences(
    workspace_path: Path,
    prefs: WorkspacePreferences,
    *,
    previous: WorkspacePreferences | None = None,
) -> None:
    """Persist ``prefs`` and publish ``preferences.saved`` with a precise diff.

    ``previous`` is the in-memory state before this write; callers that already
    hold it (e.g. ``WorkspacePreferencesRuntime.update_many``) should pass it
    to skip an extra disk read. When omitted, the existing file is parsed (if
    present) so the published ``effective_changes`` reflects real value
    transitions, not just "the file was rewritten".
    """
    workspace_path.mkdir(parents=True, exist_ok=True)

    if previous is None:
        # Reading the file directly avoids ``load_preferences``' "write defaults
        # if missing" side effect, which would recurse through save_preferences.
        f = preferences_file(workspace_path)
        if f.exists():
            try:
                previous = WorkspacePreferences.model_validate_json(
                    f.read_text(encoding="utf-8")
                )
            except Exception:
                previous = None

    effective_changes = compute_effective_changes(previous, prefs)
    _validate_pre_save_transition(workspace_path, effective_changes)

    preferences_file(workspace_path).write_text(
        prefs.model_dump_json(indent=2), encoding="utf-8",
    )
    _notify_preferences_saved(
        workspace_path, prefs, effective_changes=effective_changes,
    )


def _validate_pre_save_transition(
    workspace_path: Path,
    effective_changes: dict[str, tuple[Any, Any]],
) -> None:
    transition = effective_changes.get("knowledge.default_embedding_model")
    if transition is None:
        return
    old_value, new_value = transition
    if old_value == new_value:
        return
    from hirocli.services.knowledge import count_knowledge_points

    if count_knowledge_points(workspace_path) > 0:
        raise ValueError(
            "knowledge.default_embedding_model cannot be changed while the knowledge collection has points. "
            "Delete all knowledge documents first."
        )


# ---------------------------------------------------------------------------
# Resolution — which canonical model id + tuning for a purpose?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedModel:
    """Resolved chat/STT/TTS model from preferences + availability."""

    model_id: str
    temperature: float
    max_tokens: int
    thinking: ThinkingLevel | None = None


@dataclass(frozen=True)
class ResolvedVoiceForSynthesis:
    """Voice selection for ``TTSService.synthesize`` (short catalog model name)."""

    model: str
    voice: str = ""
    instructions: str = ""


def _profile_tuning(prefs: WorkspacePreferences, profile_id: str) -> TuningProfile:
    profile = prefs.tuning_profiles.get(profile_id)
    if profile is None:
        raise ValueError(f"Unknown tuning profile: {profile_id}")
    return profile


def resolve_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    purpose: LLMPurpose = "chat",
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Return the default model for ``purpose`` if set, in catalog, and available.

    Availability requires the model's provider to be configured in the credential store.
    When ``credential_store`` is provided (e.g. AgentManager), it is reused to avoid
    repeated keyring/doc loads.
    """
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    attr = f"default_{purpose}"
    model_id: str | None = getattr(prefs.llm, attr, None)
    if not model_id:
        return None

    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None:
        return None
    expected_kind = {"chat": "chat", "stt": "stt", "tts": "tts"}[purpose]
    if not spec.supports_kind(expected_kind):
        return None

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            logger.debug("resolve_llm: workspace path not in registry — %s", workspace_path)
            return None
        store = CredentialStore(workspace_path, wid)

    ams = AvailableModelsService(cat, store)
    if not ams.is_model_available(model_id):
        return None

    tuning = _profile_tuning(prefs, prefs.llm.default_tuning_profile)
    return ResolvedModel(
        model_id=model_id,
        temperature=tuning.temperature,
        max_tokens=tuning.max_tokens,
        thinking=tuning.thinking,
    )


def resolve_memory_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Return the configured memory extraction chat model with memory defaults."""
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    model_id = prefs.memory.default_llm
    if not model_id:
        return None

    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None or not spec.supports_kind("chat"):
        return None

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            logger.debug("resolve_memory_llm: workspace path not in registry — %s", workspace_path)
            return None
        store = CredentialStore(workspace_path, wid)

    ams = AvailableModelsService(cat, store)
    if not ams.is_model_available(model_id):
        return None

    tuning = _profile_tuning(prefs, prefs.memory.default_tuning_profile)
    return ResolvedModel(
        model_id=model_id,
        temperature=tuning.temperature,
        max_tokens=tuning.max_tokens,
        thinking=tuning.thinking,
    )


def knowledge_answering_model_source(prefs: WorkspacePreferences) -> str | None:
    """Preference path that supplies the answering model id (D16 tooltip)."""
    if prefs.knowledge.answering.model:
        return "knowledge.answering.model"
    if prefs.llm.default_chat:
        return "llm.default_chat"
    return None


def _resolve_knowledge_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    tuning_profile_id: str,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve the knowledge chat model (catalog + credentials) with a given tuning profile.

    The model id is shared across knowledge LLM steps (explicit ``knowledge.answering.model``
    else ``llm.default_chat``); only the tuning profile differs (answering vs rewrite).
    """
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    explicit = (prefs.knowledge.answering.model or "").strip() or None
    model_id = explicit or prefs.llm.default_chat
    if not model_id:
        return None

    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None or not spec.supports_kind("chat"):
        return None

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            logger.debug(
                "_resolve_knowledge_llm: workspace path not in registry — %s",
                workspace_path,
            )
            return None
        store = CredentialStore(workspace_path, wid)

    ams = AvailableModelsService(cat, store)
    if not ams.is_model_available(model_id):
        return None

    tuning = _profile_tuning(prefs, tuning_profile_id)
    return ResolvedModel(
        model_id=model_id,
        temperature=tuning.temperature,
        max_tokens=tuning.max_tokens,
        thinking=tuning.thinking,
    )


def resolve_knowledge_answering_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve the knowledge answering chat model with catalog, credentials, and tuning."""
    return _resolve_knowledge_llm(
        prefs,
        workspace_path,
        tuning_profile_id=prefs.knowledge.default_tuning_profile,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_knowledge_rewrite_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve the model for the query-rewrite step: same model, ``knowledge_rewrite`` tuning."""
    return _resolve_knowledge_llm(
        prefs,
        workspace_path,
        tuning_profile_id=DEFAULT_KNOWLEDGE_REWRITE_TUNING_PROFILE_ID,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_character_llm(
    ordered_model_ids: list[str],
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    tuning_profile: str | None = None,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Pick the first **available** chat model from a character's ``llm_models`` list.

    Falls back to ``resolve_llm(..., "chat")`` when the list is empty or no id is usable.
    Availability matches ``resolve_llm`` (catalog + credential store).
    """
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            logger.debug("resolve_character_llm: workspace path not in registry — %s", workspace_path)
            return resolve_llm(prefs, workspace_path, "chat", workspace_id=workspace_id)
        store = CredentialStore(workspace_path, wid)

    cat = get_model_catalog()
    ams = AvailableModelsService(cat, store)
    requested_profile_id = (tuning_profile or "").strip()
    if requested_profile_id and requested_profile_id not in prefs.tuning_profiles:
        logger.warning(
            "Character tuning profile missing; falling back to workspace chat profile",
            extra={
                "tuning_profile": requested_profile_id,
                "fallback": prefs.llm.default_tuning_profile,
            },
        )
    profile_id = (
        requested_profile_id
        if requested_profile_id in prefs.tuning_profiles
        else prefs.llm.default_tuning_profile
    )
    seen: set[str] = set()
    for mid in ordered_model_ids:
        if not mid or mid in seen:
            continue
        seen.add(mid)
        spec = cat.get_model(mid)
        if spec is None or spec.model_kind != "chat":
            continue
        if not ams.is_model_available(mid):
            continue
        tuning = _profile_tuning(prefs, profile_id)
        return ResolvedModel(
            model_id=mid,
            temperature=tuning.temperature,
            max_tokens=tuning.max_tokens,
            thinking=tuning.thinking,
        )
    fallback = resolve_llm(
        prefs,
        workspace_path,
        "chat",
        workspace_id=workspace_id,
        credential_store=credential_store,
    )
    if fallback is None:
        return None
    tuning = _profile_tuning(prefs, profile_id)
    return ResolvedModel(
        model_id=fallback.model_id,
        temperature=tuning.temperature,
        max_tokens=tuning.max_tokens,
        thinking=tuning.thinking,
    )


def resolve_character_voice(
    ordered_voice_model_ids: list[str],
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
    tts_instructions: str = "",
    tts_voice_by_provider: dict[str, str] | None = None,
) -> ResolvedVoiceForSynthesis | None:
    """Pick the first **available** TTS model from ``voice_models``; else workspace ``default_tts``.

    Returns catalog short model id plus optional voice preset / instructions for ``TTSService``.
    Character-level ``tts_voice_by_provider`` maps catalog ``provider_id`` to one preset id per provider;
    ``tts_instructions`` is a single optional global style hint for synthesis.
    """
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            return None
        store = CredentialStore(workspace_path, wid)

    cat = get_model_catalog()
    ams = AvailableModelsService(cat, store)

    voice_map = dict(tts_voice_by_provider or {})
    instructions = (tts_instructions or "").strip()

    def _voice_for_provider(provider_id: str) -> str:
        raw = voice_map.get(provider_id, "")
        return str(raw).strip()

    seen: set[str] = set()
    for mid in ordered_voice_model_ids:
        if not mid or mid in seen:
            continue
        seen.add(mid)
        spec = cat.get_model(mid)
        if spec is None or not spec.supports_kind("tts"):
            continue
        if not ams.is_model_available(mid):
            continue
        short = mid.split(":", 1)[1]
        pid = spec.provider_id or ""
        voice_preset = _voice_for_provider(pid)
        return ResolvedVoiceForSynthesis(model=short, voice=voice_preset, instructions=instructions)

    tts_entry = resolve_llm(
        prefs,
        workspace_path,
        "tts",
        workspace_id=workspace_id,
        credential_store=credential_store,
    )
    if tts_entry is None:
        return None
    spec = cat.get_model(tts_entry.model_id)
    if spec is None or not spec.supports_kind("tts"):
        return None
    short = tts_entry.model_id.split(":", 1)[1]
    pid = spec.provider_id or ""
    voice_preset = _voice_for_provider(pid)
    return ResolvedVoiceForSynthesis(model=short, voice=voice_preset, instructions=instructions)
