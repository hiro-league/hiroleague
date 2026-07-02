"""Preferences resolvers — turn stored preferences + credentials into resolved runtime models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..credential_store import CredentialStore

from .defaults import (
    DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID,
    DEFAULT_KNOWLEDGE_GRAPH_DISAMBIGUATION_TUNING_PROFILE_ID,
    DEFAULT_KNOWLEDGE_GRAPH_EXTRACTION_TUNING_PROFILE_ID,
    DEFAULT_KNOWLEDGE_REWRITE_TUNING_PROFILE_ID,
    DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT,
    LLMPurpose,
    ThinkingLevel,
    TuningProfile,
)
from .models import WorkspacePreferences

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedModel:
    """Resolved chat/STT/TTS model from preferences + availability."""

    model_id: str
    temperature: float
    max_tokens: int
    thinking: ThinkingLevel | None = None
    # Local-provider context window (Ollama num_ctx); None = provider default. See ModelTuning.num_ctx.
    num_ctx: int | None = None


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


def _resolved_from_tuning(model_id: str, tuning: TuningProfile) -> ResolvedModel:
    """Build a ``ResolvedModel`` from a model id + tuning profile (the common tail of every resolver)."""
    return ResolvedModel(
        model_id=model_id,
        temperature=tuning.temperature,
        max_tokens=tuning.max_tokens,
        thinking=tuning.thinking,
        num_ctx=tuning.num_ctx,
    )


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


def _resolve_available_model(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    model_id: str | None,
    *,
    expected_kind: str,
    tuning_profile_id: str,
    log_label: str,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Shared tail of the chat/stt/tts resolvers: catalog lookup + kind check + provider-credential
    availability + tuning. The differing part — how ``model_id`` is chosen — stays in each caller."""
    if not model_id:
        return None
    from ..available_models import AvailableModelsService
    from ..model_catalog import get_model_catalog

    cat = get_model_catalog()
    spec = cat.get_model(model_id)
    if spec is None or not spec.supports_kind(expected_kind):
        return None

    store = _resolve_credential_store(
        workspace_path,
        workspace_id=workspace_id,
        credential_store=credential_store,
        log_label=log_label,
    )
    if store is None:
        return None

    ams = AvailableModelsService(cat, store)
    if not ams.is_model_available(model_id):
        return None

    return _resolved_from_tuning(model_id, _profile_tuning(prefs, tuning_profile_id))


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
    model_id: str | None = getattr(prefs.llm, f"default_{purpose}", None)
    return _resolve_available_model(
        prefs,
        workspace_path,
        model_id,
        expected_kind=purpose,
        tuning_profile_id=prefs.llm.default_tuning_profile,
        log_label="resolve_llm",
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


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
    :func:`resolve_llm`.
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
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=None,
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
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=None,
        tuning_profile_id=DEFAULT_KNOWLEDGE_REWRITE_TUNING_PROFILE_ID,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_knowledge_graph_extraction_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """L3 — resolve the model for graph extraction (entities+relations per chunk).

    Same answering-model resolution path; only the tuning profile differs
    (``knowledge_graph_extraction`` — temp=0, generous max_tokens, no reasoning).
    """
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=None,
        tuning_profile_id=DEFAULT_KNOWLEDGE_GRAPH_EXTRACTION_TUNING_PROFILE_ID,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_knowledge_graph_disambiguation_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """L3 — resolve the model for the LLM disambiguation step of the resolver.

    Called only when the deterministic ladder (exact → fuzzy) cannot decide
    confidently. Tiny output budget — see the tuning profile.
    """
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=None,
        tuning_profile_id=DEFAULT_KNOWLEDGE_GRAPH_DISAMBIGUATION_TUNING_PROFILE_ID,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def _resolve_chat_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    explicit_model: str | None,
    tuning_profile_id: str,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve a chat model tier (catalog + provider credentials + tuning) with the shared fallback.

    Single fallback chain for every chat resolver: explicit override (``explicit_model`` — a graph
    ``graph.*_model`` or eval override) → ``knowledge.answering.model`` → ``llm.default_chat``. The
    knowledge answering/rewrite/graph tiers pass ``explicit_model=None`` (they have no per-tier
    override, so they resolve from ``knowledge.answering.model`` down); the graphiti + eval tiers pass
    their own override. Only the tuning profile differs per caller.
    """
    explicit = (explicit_model or "").strip() or None
    answering = (prefs.knowledge.answering.model or "").strip() or None
    model_id = explicit or answering or prefs.llm.default_chat
    return _resolve_available_model(
        prefs,
        workspace_path,
        model_id,
        expected_kind="chat",
        tuning_profile_id=tuning_profile_id,
        log_label="_resolve_chat_llm",
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_graphiti_extraction_model(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Graphiti pivot — the main extraction + edge tier (``ModelSize.medium``)."""
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=prefs.graph.extraction_model,
        tuning_profile_id=prefs.graph.extraction_tuning_profile,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_graphiti_small_model(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Graphiti pivot — the cheap sub-step tier (``ModelSize.small``).

    Falls back to the extraction model id when ``small_model`` is unset, so a single
    configured model still drives both tiers (with their separate tuning profiles).
    """
    explicit = prefs.graph.small_model or prefs.graph.extraction_model
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=explicit,
        tuning_profile_id=prefs.graph.small_tuning_profile,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


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


def resolve_eval_answer_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve the memory-eval ANSWER model — its own model override + tuning profile, separate
    from the judge. Model chain: ``graph.eval.answer_model`` → ``knowledge.answering.model`` →
    ``llm.default_chat`` (mirrors the graphiti tiers)."""
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=prefs.graph.eval.answer_model,
        tuning_profile_id=prefs.graph.eval.answer_tuning_profile,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_eval_judge_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve the eval JUDGE model (both tracks) — its own model override + tuning profile,
    separate from the answer. Same fallback chain as :func:`resolve_eval_answer_llm`."""
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=prefs.graph.eval.judge_model,
        tuning_profile_id=prefs.graph.eval.judge_tuning_profile,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_eval_retrieval_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve the agentic-retrieval model (memory track) — its own model override + tuning
    profile. Model chain: ``graph.eval.retrieval_model`` → ``graph.eval.answer_model`` →
    ``knowledge.answering.model`` → ``llm.default_chat``. The answer-model tier preserves prior
    behavior (the retrieval loop borrowed the answer model before it had a dedicated preference),
    so an unset ``retrieval_model`` resolves to exactly the same model as the answer step."""
    return _resolve_chat_llm(
        prefs,
        workspace_path,
        explicit_model=prefs.graph.eval.retrieval_model or prefs.graph.eval.answer_model,
        tuning_profile_id=prefs.graph.eval.retrieval_tuning_profile,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_memory_retrieval_llm(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve the CHAT agentic memory-retrieval model (Phase 2).

    Chain: ``memory.retrieval.model`` → ``llm.default_chat``. Chat memory deliberately does NOT
    borrow the knowledge-answering tier (unlike the eval retrieval resolver) — a simple, predictable
    fallback the Agent-memory model picker surfaces via its empty-box hint."""
    model_id = (prefs.memory.retrieval.model or "").strip() or prefs.llm.default_chat
    return _resolve_available_model(
        prefs,
        workspace_path,
        model_id,
        expected_kind="chat",
        tuning_profile_id=prefs.memory.retrieval.tuning_profile,
        log_label="memory.retrieval",
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


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
    from ..available_models import AvailableModelsService
    from ..model_catalog import get_model_catalog

    store = _resolve_credential_store(
        workspace_path,
        workspace_id=workspace_id,
        credential_store=credential_store,
        log_label="resolve_character_llm",
    )
    if store is None:
        return resolve_llm(prefs, workspace_path, "chat", workspace_id=workspace_id)

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
        return _resolved_from_tuning(mid, _profile_tuning(prefs, profile_id))
    fallback = resolve_llm(
        prefs,
        workspace_path,
        "chat",
        workspace_id=workspace_id,
        credential_store=credential_store,
    )
    if fallback is None:
        return None
    return _resolved_from_tuning(fallback.model_id, _profile_tuning(prefs, profile_id))


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
    from ..available_models import AvailableModelsService
    from ..model_catalog import get_model_catalog

    store = _resolve_credential_store(
        workspace_path,
        workspace_id=workspace_id,
        credential_store=credential_store,
        log_label="resolve_character_voice",
    )
    if store is None:
        return None

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
