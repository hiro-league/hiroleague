"""Preferences resolvers — turn stored preferences + credentials into resolved runtime models.

Phase 7b step 5: each of Hiro's own jobs points at ONE AI profile (``jobs.JOB_PRESETS``), so every job
model comes from :func:`resolve_job_model`:

- the job's field names a profile → the first profile in its fallback chain whose model is available
  (a catalog chat model whose provider has credentials, or a model on a configured local server);
  plan-tool models (claude_code:* / codex:*) can't be LangChain chat models and are skipped;
- the field is null → the job it falls back to (chat-like jobs → chat; graph small → graph extraction;
  eval retrieval → eval answer; rewrite → knowledge) gives the model, with THIS job's preset tuning
  (as before, when only the model fell back and each job kept its own tuning);
- chat and reading pictures fall back to nothing (no model → off).

A profile maps to a :class:`ResolvedModel` as ``services/ai_ask`` builds it: temperature None → 0.7,
max_tokens None → 8192, num_ctx only for local models. Its limits never stop a job (count only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..credential_store import CredentialStore

from .defaults import (
    DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID,
    DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT,
    ThinkingLevel,
)
from .jobs import job_preset, job_profile_ref
from .models import WorkspacePreferences
from .models_ai import AI_PLAN_PROVIDERS, AiProfile, ai_fallback_chain

if TYPE_CHECKING:
    from .models_voice import VoiceProfile

logger = logging.getLogger(__name__)

# What a profile's unset tuning means when built for a job (as ChatModelProvider._build in ai_ask).
PROFILE_DEFAULT_TEMPERATURE = 0.7
PROFILE_DEFAULT_MAX_TOKENS = 8192


@dataclass(frozen=True)
class ResolvedModel:
    """A resolved chat model + its tuning (from an AI profile, or a job preset when borrowed)."""

    model_id: str
    temperature: float
    max_tokens: int
    thinking: ThinkingLevel | None = None
    # Local-provider context window (Ollama num_ctx); None = provider default. See ModelTuning.num_ctx.
    num_ctx: int | None = None
    # Phase 7b step 5: the AI profile the model came from ("" = none), for usage and the admin.
    profile_id: str = ""
    profile_name: str = ""
    # The profile's extra instructions (applied by the chat; other jobs keep their own prompts).
    instructions: str = ""


@dataclass(frozen=True)
class ResolvedVoice:
    """The voice profile Hiro speaks a reply with (character's first usable, else voice.hiro_profile)."""

    profile_id: str
    profile: "VoiceProfile"
    source: str  # "character" | "hiro"


def _resolve_credential_store(
    workspace_path: Path,
    *,
    workspace_id: str | None,
    credential_store: CredentialStore | None,
    log_label: str,
) -> CredentialStore | None:
    """Reuse the caller's store when given; else look up the workspace id and open one.

    Returns ``None`` when the path isn't in the registry (no id) — callers treat that as
    "availability can't be checked" (return None, or fall back)."""
    if credential_store is not None:
        return credential_store
    from ..workspace import workspace_id_for_path

    wid = workspace_id or workspace_id_for_path(workspace_path)
    if wid is None:
        logger.debug("%s: workspace path not in registry — %s", log_label, workspace_path)
        return None
    return CredentialStore(workspace_path, wid)


def _is_local_provider(provider_id: str) -> bool:
    from ..model_catalog import get_model_catalog

    prov = get_model_catalog().get_provider(provider_id)
    return prov is not None and prov.hosting == "local"


def profile_model_available(model_id: str, store: CredentialStore) -> bool:
    """Whether a job can build ``model_id`` now: a catalog chat model whose provider has credentials,
    or a model on a local server whose address is set. Plan tools never (not LangChain models)."""
    from ..model_catalog import get_model_catalog

    provider_id = model_id.partition(":")[0]
    if provider_id in AI_PLAN_PROVIDERS:
        return False
    cat = get_model_catalog()
    prov = cat.get_provider(provider_id)
    if prov is None:
        return False
    if prov.hosting == "local":
        # Any model the server reports (catalog row or not); the call itself tells if it's gone.
        return store.is_configured(provider_id)
    spec = cat.get_model(model_id)
    if spec is None or not spec.supports_kind("chat"):
        return False
    return store.is_configured(provider_id)


def resolved_from_profile(profile_id: str, profile: AiProfile) -> ResolvedModel:
    """Map an AI profile to a ``ResolvedModel`` (module notes for the defaults)."""
    local = _is_local_provider(profile.model.partition(":")[0])
    return ResolvedModel(
        model_id=profile.model,
        temperature=profile.temperature if profile.temperature is not None else PROFILE_DEFAULT_TEMPERATURE,
        max_tokens=profile.max_tokens or PROFILE_DEFAULT_MAX_TOKENS,
        thinking=profile.thinking,
        num_ctx=profile.num_ctx if local else None,
        profile_id=profile_id,
        profile_name=profile.label,
        instructions=profile.instructions,
    )


def resolve_profile_model(
    prefs: WorkspacePreferences, profile_id: str, store: CredentialStore
) -> ResolvedModel | None:
    """The first profile in ``profile_id``'s fallback chain whose model is available, else None."""
    profiles = prefs.ai.profiles
    for pid in ai_fallback_chain(profiles, profile_id):
        profile = profiles[pid]
        if profile.is_plan:
            logger.debug("AI profile skipped for a job — plan tool model", extra={"profile": pid})
            continue
        if profile_model_available(profile.model, store):
            return resolved_from_profile(pid, profile)
    return None


def _resolve_job(
    prefs: WorkspacePreferences, job: str, store: CredentialStore, seen: tuple[str, ...] = ()
) -> ResolvedModel | None:
    preset = job_preset(job)
    profile_id = job_profile_ref(prefs, job)
    if profile_id is not None:
        # A set field that resolves to nothing stays off (no silent borrow from another job).
        return resolve_profile_model(prefs, profile_id, store)
    parent = preset.falls_back_to
    if parent is None or parent in seen:
        return None
    borrowed = _resolve_job(prefs, parent, store, (*seen, job))
    if borrowed is None:
        return None
    # The other job's model (and its local context window), with this job's own preset tuning.
    return ResolvedModel(
        model_id=borrowed.model_id,
        temperature=preset.temperature,
        max_tokens=preset.max_tokens,
        thinking=preset.thinking,
        num_ctx=borrowed.num_ctx,
        profile_id=borrowed.profile_id,
        profile_name=borrowed.profile_name,
    )


def resolve_job_model(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    job: str,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """The model + tuning one of Hiro's jobs runs with now, or None (module notes)."""
    if job_model_source(prefs, job) is None:  # ValueError for an unknown job
        return None  # nothing set along the job's chain: no store lookup needed
    store = _resolve_credential_store(
        workspace_path,
        workspace_id=workspace_id,
        credential_store=credential_store,
        log_label=f"resolve_job_model[{job}]",
    )
    if store is None:
        return None
    return _resolve_job(prefs, job, store)


def job_model_source(prefs: WorkspacePreferences, job: str) -> str | None:
    """The preference path whose AI profile supplies the job's model (the admin's "from" hint):
    the job's own field, else the field of the job it borrows from; None when nothing is set."""
    seen: set[str] = set()
    current: str | None = job
    while current is not None and current not in seen:
        seen.add(current)
        if job_profile_ref(prefs, current) is not None:
            return job_preset(current).path
        current = job_preset(current).falls_back_to
    return None


class _JobResolver:
    """A per-job ``resolve_*`` callable (the names the callers already use) over resolve_job_model."""

    def __init__(self, job: str) -> None:
        self.job = job
        self.__doc__ = f"``resolve_job_model(..., {job!r})``."

    def __call__(
        self,
        prefs: WorkspacePreferences,
        workspace_path: Path,
        *,
        workspace_id: str | None = None,
        credential_store: CredentialStore | None = None,
    ) -> ResolvedModel | None:
        return resolve_job_model(
            prefs, workspace_path, self.job, workspace_id=workspace_id, credential_store=credential_store
        )


# Per-job names kept so the callers (and their test patches) don't churn; all go through
# resolve_job_model. The two unused knowledge-graph (L3) resolvers were dropped with their presets.
resolve_memory_retrieval_llm = _JobResolver("memory")
resolve_knowledge_answering_llm = _JobResolver("knowledge")
resolve_knowledge_rewrite_llm = _JobResolver("rewrite")
resolve_graphiti_extraction_model = _JobResolver("graph_extraction")
resolve_graphiti_small_model = _JobResolver("graph_small")
resolve_eval_answer_llm = _JobResolver("eval_answer")
resolve_eval_judge_llm = _JobResolver("eval_judge")
resolve_eval_retrieval_llm = _JobResolver("eval_retrieval")


def resolve_stt_model(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> str | None:
    """``llm.default_stt`` when it is a catalog speech-to-text model whose provider has credentials.

    (Was ``resolve_llm(..., "stt")``; chat and TTS no longer resolve from ``llm.*`` model fields.)
    """
    from ..available_models import AvailableModelsService
    from ..model_catalog import get_model_catalog

    model_id = (prefs.llm.default_stt or "").strip()
    if not model_id:
        return None
    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None or not spec.supports_kind("stt"):
        return None
    store = _resolve_credential_store(
        workspace_path, workspace_id=workspace_id, credential_store=credential_store, log_label="resolve_stt_model"
    )
    if store is None:
        return None
    return model_id if AvailableModelsService(cat, store).is_model_available(model_id) else None


@dataclass(frozen=True)
class ResolvedImageGen:
    """Resolved image-generation call parameters: profile values + per-call overrides."""

    model_id: str
    profile_id: str
    steps: int
    size: str | None
    style_prefix: str
    style_suffix: str
    seed: int | None


def resolve_image_gen(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    profile_id: str | None = None,
    model_override: str | None = None,
    steps_override: int | None = None,
    seed_override: int | None = None,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedImageGen | None:
    """Resolve the image-gen model + params for a call.

    Resolution order (design doc): call overrides > named image profile >
    ``llm.default_image_gen`` > catalog/credential availability. Returns None when no
    image_gen model is selected or its provider has no credentials — same contract as
    :func:`resolve_job_model`.
    """
    from ..available_models import AvailableModelsService
    from ..model_catalog import get_model_catalog

    pid = (profile_id or "").strip() or prefs.llm.default_image_profile
    profile = prefs.image_profiles.get(pid)
    if profile is None:
        raise ValueError(f"Unknown image profile: {pid}")

    model_id = (model_override or "").strip() or profile.model or prefs.llm.default_image_gen
    if not model_id:
        return None

    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None or not spec.supports_kind("image_gen"):
        return None

    store = _resolve_credential_store(
        workspace_path,
        workspace_id=workspace_id,
        credential_store=credential_store,
        log_label="resolve_image_gen",
    )
    if store is None:
        return None

    ams = AvailableModelsService(cat, store)
    if not ams.is_model_available(model_id):
        return None

    return ResolvedImageGen(
        model_id=model_id,
        profile_id=pid,
        steps=steps_override if steps_override is not None else profile.steps,
        size=profile.size,
        style_prefix=profile.style_prefix,
        style_suffix=profile.style_suffix,
        seed=seed_override if seed_override is not None else profile.seed,
    )


def compose_image_prompt(resolved: ResolvedImageGen, prompt: str) -> str:
    """Wrap the caller's prompt with the profile's style scaffolding."""
    parts = [resolved.style_prefix.strip(), prompt.strip(), resolved.style_suffix.strip()]
    return ", ".join(p for p in parts if p)


def resolve_retrieval_agent_prompt(prefs: WorkspacePreferences) -> tuple[str, str]:
    """Return ``(profile_id, prompt_text)`` for the agentic retrieval loop (eval active profile)."""
    return prefs.graph.eval.resolve_retrieval_agent_prompt()


def resolve_chat_retrieval_agent_prompt(prefs: WorkspacePreferences) -> tuple[str, str]:
    """Return ``(profile_id, prompt_text)`` for the CHAT retrieval loop.

    Cross-namespace: the profile LIBRARY is shared (``graph.eval.retrieval_agent_prompts``) but chat's
    selection lives under ``memory.retrieval.active_prompt_id`` (its own dropdown). Blank falls back to
    the locked ``chat`` profile, then the built-in chat prompt constant."""
    active = (prefs.memory.retrieval.active_prompt_id or "").strip() or DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID
    return prefs.graph.eval.resolve_prompt_from_library(active, DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT)


def _first_configured_id(*candidates: str | None) -> str | None:
    """First non-blank id in the chain (each stripped), else ``None`` — the shared "override then
    workspace default" fallback for the pure model-id preference reads below."""
    for candidate in candidates:
        stripped = (candidate or "").strip()
        if stripped:
            return stripped
    return None


def resolve_knowledge_embedder_model(prefs: WorkspacePreferences) -> str | None:
    """Knowledge embedder id — the knowledge override (``knowledge.default_embedding_model``)
    when set, else the workspace default (``llm.default_embedder``).

    ``None`` = no embedder configured anywhere. Embedding is mandatory and dimension-bound, so
    there is no silent fallback: callers must gate ingest/query on ``None`` rather than forcing a
    model. Pure preference read — availability/download is checked by ``resolve_knowledge_embedder``
    at use time."""
    return _first_configured_id(
        prefs.knowledge.default_embedding_model, prefs.llm.default_embedder
    )


def resolve_graphiti_embedder_model(prefs: WorkspacePreferences) -> str | None:
    """Graphiti embedder id for node/fact embeddings — the graph override
    (``graph.embedder_model``) when set, else the workspace default (``llm.default_embedder``).

    ``None`` = no embedder configured; the graph build/ingest must gate on this rather than
    forcing a model (decision: no silent default). Pure preference read."""
    return _first_configured_id(prefs.graph.embedder_model, prefs.llm.default_embedder)


def resolve_knowledge_reranker_model(prefs: WorkspacePreferences) -> str | None:
    """Knowledge retrieval reranker model id.

    The knowledge-specific override (``knowledge.retrieval.reranker.model_id``) when set,
    else the workspace default reranker (``llm.default_reranker``). ``None`` = no reranker
    (retrieval order kept). Pure preference read — availability/download is checked by
    ``resolve_reranker`` at use time."""
    return _first_configured_id(
        prefs.knowledge.retrieval.reranker.model_id, prefs.llm.default_reranker
    )


def resolve_graph_reranker_model(prefs: WorkspacePreferences) -> str | None:
    """Graph fact-search reranker model id.

    The graph-specific override (``graph.reranker.model_id``) when set, else the workspace
    default reranker (``llm.default_reranker``). ``None`` = degrade the ``cross_encoder``
    search recipe to RRF. Pure preference read — availability is checked by
    ``resolve_reranker`` at use time."""
    return _first_configured_id(prefs.graph.reranker.model_id, prefs.llm.default_reranker)


def resolve_character_llm(
    profile_ids: list[str],
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """The character's first usable AI profile (each with its fallback chain), else Hiro's chat job.

    Phase 7b step 5: a character holds an ordered list of AI profile ids (``Character.ai_profiles``)
    instead of model ids + a tuning profile. An id that no longer exists is skipped with a warning.
    """
    store = _resolve_credential_store(
        workspace_path,
        workspace_id=workspace_id,
        credential_store=credential_store,
        log_label="resolve_character_llm",
    )
    if store is None:
        return None
    for pid in dict.fromkeys(p for p in profile_ids if p):
        if pid not in prefs.ai.profiles:
            logger.warning("⚠️ Character AI profile missing — skipped", extra={"profile": pid})
            continue
        resolved = resolve_profile_model(prefs, pid, store)
        if resolved is not None:
            return resolved
    return _resolve_job(prefs, "chat", store)


def voice_profile_usable(profile: "VoiceProfile", store: CredentialStore | None) -> bool:
    """Whether the voice profile's provider has a key set (the engine reads it from the same store)."""
    return store is not None and store.is_configured(profile.provider)


def resolve_character_voice(
    profile_ids: list[str],
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedVoice | None:
    """The voice a reply is spoken with: the character's first voice profile whose provider has a key,
    else ``voice.hiro_profile`` (when its provider has one), else None (no voice reply)."""
    store = _resolve_credential_store(
        workspace_path,
        workspace_id=workspace_id,
        credential_store=credential_store,
        log_label="resolve_character_voice",
    )
    profiles = prefs.voice.profiles
    for pid in dict.fromkeys(p for p in profile_ids if p):
        profile = profiles.get(pid)
        if profile is None:
            logger.warning("⚠️ Character voice profile missing — skipped", extra={"profile": pid})
            continue
        if voice_profile_usable(profile, store):
            return ResolvedVoice(profile_id=pid, profile=profile, source="character")
    hiro = prefs.voice.hiro_profile
    if hiro and hiro in profiles and voice_profile_usable(profiles[hiro], store):
        return ResolvedVoice(profile_id=hiro, profile=profiles[hiro], source="hiro")
    return None


def unknown_character_profiles(
    prefs: WorkspacePreferences, ai_profiles: list[str], voice_profiles: list[str]
) -> list[str]:
    """Plain-words lines for profile ids a character names that don't exist (save-time check)."""
    lines = [f'AI profile "{pid}" doesn\'t exist.' for pid in ai_profiles if pid not in prefs.ai.profiles]
    lines += [f'Voice profile "{pid}" doesn\'t exist.' for pid in voice_profiles if pid not in prefs.voice.profiles]
    return lines


__all__ = [
    "PROFILE_DEFAULT_MAX_TOKENS",
    "PROFILE_DEFAULT_TEMPERATURE",
    "ResolvedImageGen",
    "ResolvedModel",
    "ResolvedVoice",
    "compose_image_prompt",
    "job_model_source",
    "profile_model_available",
    "resolve_character_llm",
    "resolve_character_voice",
    "resolve_chat_retrieval_agent_prompt",
    "resolve_eval_answer_llm",
    "resolve_eval_judge_llm",
    "resolve_eval_retrieval_llm",
    "resolve_graph_reranker_model",
    "resolve_graphiti_embedder_model",
    "resolve_graphiti_extraction_model",
    "resolve_graphiti_small_model",
    "resolve_image_gen",
    "resolve_job_model",
    "resolve_knowledge_answering_llm",
    "resolve_knowledge_embedder_model",
    "resolve_knowledge_reranker_model",
    "resolve_knowledge_rewrite_llm",
    "resolve_memory_retrieval_llm",
    "resolve_profile_model",
    "resolve_retrieval_agent_prompt",
    "resolve_stt_model",
    "resolved_from_profile",
    "unknown_character_profiles",
    "voice_profile_usable",
]
