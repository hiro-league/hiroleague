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


DEFAULT_MEMORY_MAX_MESSAGES = 6

DEFAULT_MEMORY_SEARCH_TOP_K = 8
DEFAULT_MEMORY_SEARCH_THRESHOLD = 0.1
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class MemorySearchPreferences(BaseModel):
    """Retrieval-time tuning for ``MemoryService.search``."""

    top_k: int = Field(default=DEFAULT_MEMORY_SEARCH_TOP_K, ge=1, le=100)
    # Mem0 fused score in [0, 1] (semantic + BM25 + entity boost). Rows below
    # this score are dropped pre-rerank; 0.0 disables the gate.
    threshold: float = Field(default=DEFAULT_MEMORY_SEARCH_THRESHOLD, ge=0.0, le=1.0)
    # Per-call default for the rerank pass. Effective only when
    # ``reranker.enabled`` is true; otherwise mem0 has no reranker to call.
    rerank: bool = False


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
    max_messages: int = Field(default=DEFAULT_MEMORY_MAX_MESSAGES, ge=1, le=100)
    search: MemorySearchPreferences = Field(default_factory=MemorySearchPreferences)
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


class KnowledgeChunkingMarkdownPreferences(BaseModel):
    respect_headings: bool = True


class KnowledgeChunkingPreferences(BaseModel):
    chunk_size: int = Field(default=1200, ge=200, le=8000)
    chunk_overlap: int = Field(default=150, ge=0, le=2000)
    markdown: KnowledgeChunkingMarkdownPreferences = Field(default_factory=KnowledgeChunkingMarkdownPreferences)

    @model_validator(mode="after")
    def _overlap_less_than_size(self) -> "KnowledgeChunkingPreferences":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("knowledge.chunking.chunk_overlap must be smaller than chunk_size")
        return self


class KnowledgeRetrievalPreferences(BaseModel):
    top_k: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class KnowledgeAnsweringPreferences(BaseModel):
    model: str | None = None
    cite_sources: bool = True
    language_policy: Literal["match_query", "prefer_english", "prefer_arabic"] = "match_query"


class KnowledgePreferences(BaseModel):
    default_embedding_model: str | None = None
    default_tuning_profile: str = DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID
    chunking: KnowledgeChunkingPreferences = Field(default_factory=KnowledgeChunkingPreferences)
    retrieval: KnowledgeRetrievalPreferences = Field(default_factory=KnowledgeRetrievalPreferences)
    answering: KnowledgeAnsweringPreferences = Field(default_factory=KnowledgeAnsweringPreferences)

    @property
    def default_embedding_model_resolved(self) -> str:
        return self.default_embedding_model or DEFAULT_KNOWLEDGE_EMBEDDING_MODEL


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


def resolve_knowledge_answering_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve the knowledge answering chat model with catalog, credentials, and tuning."""
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
                "resolve_knowledge_answering_llm: workspace path not in registry — %s",
                workspace_path,
            )
            return None
        store = CredentialStore(workspace_path, wid)

    ams = AvailableModelsService(cat, store)
    if not ams.is_model_available(model_id):
        return None

    tuning = _profile_tuning(prefs, prefs.knowledge.default_tuning_profile)
    return ResolvedModel(
        model_id=model_id,
        temperature=tuning.temperature,
        max_tokens=tuning.max_tokens,
        thinking=tuning.thinking,
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
