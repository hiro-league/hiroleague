"""Preference building blocks — the field-metadata helper, value types, and built-in defaults.

Split out of ``models.py`` so the section schema models read cleanly. This module sits BELOW the
models in the dependency graph (the default factories build the profile classes, which use
``pref_field``), so it must never import from ``.models``. Re-exported by the package ``__init__``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field

from ..prompts import load_prompt


# Admin-UI preference field metadata.
#
# Every preference field can carry metadata in pydantic's ``json_schema_extra`` that the admin UI +
# save layer read (see ``preferences_schema._META_KEYS``): which model kind a model-id field selects,
# whether it's an "advanced" (hidden-by-default) knob, a UI slider ``step``, and the save-policy flags
# (``preferencesSaveSkip`` / ``writeWhole`` / ``readOnly``). ``pref_field`` centralizes those so each
# call site declares intent by NAME (``model_kind=…`` / ``advanced=True`` / ``step=…``) instead of
# hand-writing the dict — a new model-id field can't silently forget its ``model_kind``. Any other
# keyword (default, title, description, ge, le, max_length, default_factory, …) is forwarded straight
# to ``Field``. Output is identical to the inline dict (schema gen copies keys in a fixed order).
ModelKind = Literal["chat", "stt", "tts", "rerank", "embedding"]


def pref_field(
    *,
    model_kind: ModelKind | None = None,
    advanced: bool = False,
    step: float | None = None,
    save_skip: bool = False,
    write_whole: bool = False,
    read_only: bool = False,
    ai_profile_ref: bool = False,
    voice_profile_ref: bool = False,
    embedding_profile_ref: bool = False,
    rerank_profile_ref: bool = False,
    **field_kwargs: Any,
) -> Any:
    """``Field(...)`` for a preference with the admin-UI ``json_schema_extra`` metadata named.

    Phase 7b step 5 (tuning profiles → AI profiles): ``ai_profile_ref=True`` marks a field whose value
    is an ``ai.profiles`` id (one of Hiro's jobs, see ``jobs.JOB_PRESETS``) and ``voice_profile_ref=True``
    one whose value is a ``voice.profiles`` id; ``embedding_profile_ref`` / ``rerank_profile_ref`` one whose
    value is an ``embedding.profiles`` / ``rerank.profiles`` id (Hiro's searching uses). The root validator finds them by the marker
    (``iter_profile_refs``) and checks the profile exists, and the markers ARE copied into the admin
    field map (``preferences_schema._META_KEYS``) so the admin renders a profile picker for them.
    """
    extra: dict[str, Any] = {}
    if model_kind is not None:
        extra["model_kind"] = model_kind
    if advanced:
        extra["advanced"] = True
    if step is not None:
        extra["step"] = step
    if save_skip:
        extra["preferencesSaveSkip"] = True
    if write_whole:
        extra["writeWhole"] = True
    if read_only:
        extra["readOnly"] = True
    if ai_profile_ref:
        extra["ai_profile_ref"] = True
    if voice_profile_ref:
        extra["voice_profile_ref"] = True
    if embedding_profile_ref:
        extra["embedding_profile_ref"] = True
    if rerank_profile_ref:
        extra["rerank_profile_ref"] = True
    return Field(json_schema_extra=extra, **field_kwargs)


ProfileRefMarker = Literal["ai_profile_ref", "voice_profile_ref", "embedding_profile_ref", "rerank_profile_ref"]


def iter_profile_refs(
    model: BaseModel, marker: ProfileRefMarker, prefix: str = ""
) -> Iterator[tuple[str, str | None]]:
    """Yield ``(dotted_path, profile_id)`` for every field flagged ``marker`` via ``pref_field``,
    recursing into nested preference models (dict fields are not traversed)."""
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(value, BaseModel):
            yield from iter_profile_refs(value, marker, path)
            continue
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get(marker):
            yield path, value


class PreferenceSection(BaseModel):
    """First-level preferences section metadata for admin presentation."""

    key: str
    label: str
    description: str = ""


PREFERENCE_SECTIONS: tuple[PreferenceSection, ...] = (
    PreferenceSection(
        key="llm",
        label="Models",
        description="Workspace model defaults and the AI profiles Hiro's own jobs use.",
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
        key="graph",
        label="Graph Engine",
        description="Shared Graphiti temporal-graph engine (models, embedder, search) used by knowledge and agent memory.",
    ),
    PreferenceSection(
        key="chat",
        label="Agent",
        description="How the character answers in chat — general instructions and citation behavior.",
    ),
)


# ---------------------------------------------------------------------------
# LLM selection (canonical catalog ids: ``openai:gpt-6.1-sol``)
# ---------------------------------------------------------------------------

ThinkingLevel = Literal["off", "minimal", "low", "medium", "high"]


class ModelTuning(BaseModel):
    """Provider-neutral runtime model tuning."""

    # step: float inputs in the admin UI read granularity from schema metadata (no hardcoded step).
    temperature: float = pref_field(step=0.1, default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    thinking: ThinkingLevel | None = None
    # Context-window size for local providers (Ollama `num_ctx`). Ollama silently defaults to 2048
    # regardless of the model's real window, so long-context local models truncate unless this is
    # set. Left None = let the provider decide (do NOT auto-max to the catalog window — large
    # values allocate a huge KV cache and OOM local machines). Ignored by cloud providers.
    num_ctx: int | None = Field(default=None, ge=1)


# ---------------------------------------------------------------------------
# Image generation profiles
# ---------------------------------------------------------------------------


class ImageProfile(BaseModel):
    """Named image-generation recipe: model + diffusion params + prompt scaffolding.

    The scaffolding fields (``style_prefix`` / ``style_suffix``) wrap the caller's prompt
    so a profile is a reusable *recipe*, not just numbers — the image analog of a voice
    profile's style. ``size`` is a hint; fixed-resolution providers (flux-1-schnell:
    1024x1024) ignore it. Hard limits (max steps, prompt length) live in the catalog and
    are clamped by the provider implementation.
    """

    label: str = Field(default="", min_length=1)
    locked: bool = False
    # Canonical catalog id (``cloudflare:flux-1-schnell``); None → llm.default_image_gen.
    model: str | None = None
    steps: int = Field(default=4, ge=1, le=8)
    # "WIDTHxHEIGHT" hint — providers may ignore (flux-1-schnell is fixed 1024x1024).
    size: str | None = None
    style_prefix: str = ""
    style_suffix: str = ""
    # None = random seed per call; pin for reproducibility experiments.
    seed: int | None = None


DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID = "image_playground"


def default_image_profiles() -> dict[str, ImageProfile]:
    return {
        DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID: ImageProfile(
            label="Playground",
            locked=True,
            # No scaffolding — the Image Lab default is a transparent pass-through so the
            # user sees exactly what their prompt produces before promoting a recipe.
            steps=4,
        ),
    }


# System prompt for the optional query-rewrite step. Editable in preferences; the rewrite node
# falls back to this constant when the stored prompt is blank. Scope is normalization +
# literal-keyword extraction; the conversation-history clause is a no-op for admin Ask (which
# passes no history) and active in chat (where history is supplied for reference resolution).
# Text lives in prompts/knowledge_rewrite.md (the output shape is spelled out in the prompt — not
# left to the schema alone — because some providers, e.g. DeepSeek thinking mode, fall back to
# JSON-mode structured output that never sees the pydantic field descriptions).
DEFAULT_KNOWLEDGE_REWRITE_PROMPT = load_prompt("knowledge_rewrite")


# System prompt for the answer-generation step. Editable in preferences; the answer node falls
# back to this constant when the stored prompt is blank. Relaxed (vs. the old all-or-nothing
# wording) so multi-part questions degrade gracefully: it keeps the facts-only-from-context guard
# but explicitly allows PARTIAL answers and forbids a bare "I don't know" when any part is
# supported. Safe because the empty-context case is gated upstream by ``no_results`` and never
# reaches this prompt. Citation + language clauses are appended at runtime from the other answering
# prefs, so they are intentionally not part of this text.
DEFAULT_KNOWLEDGE_ANSWERING_PROMPT = load_prompt("knowledge_answering")


# System prompt for the chat's agentic memory-retrieval loop (agentic-memory-retrieval-design §5.3).
# History-aware (recent turns are fed in) and abstain-allowed (may skip searching when the message
# needs no memory); its final turn is a GROUNDING NOTE for the persona, not a user-facing reply. The
# locked ``chat`` profile of ``memory.retrieval.prompts`` carries it; blank profile text falls back here.
DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT = load_prompt("memory_chat_retrieval_agent")


# Dotted preference path → built-in default text for every editable system prompt. Exposed in the
# admin /preferences payload so the UI can offer "Restore default" on prompt editors: once a prompt
# is saved as "" the pydantic default never re-applies (defaults only fill ABSENT JSON keys), so the
# engine silently falls back at runtime while the admin UI shows blank with no way to recover the
# default text. Keep in sync with the prompt fields on the models below (guarded by a domain test).
# A prompt LIBRARY (``memory.retrieval.prompts``) isn't here: its locked built-in profile carries
# the default text and doubles as the UI's "Restore default" source.
PROMPT_DEFAULTS: dict[str, str] = {
    "knowledge.answering.prompt": DEFAULT_KNOWLEDGE_ANSWERING_PROMPT,
    "knowledge.rewrite.prompt": DEFAULT_KNOWLEDGE_REWRITE_PROMPT,
}
# ``chat.instructions`` is registered with PROMPT_DEFAULTS after its default constant is defined
# below (DEFAULT_CHAT_INSTRUCTIONS) — see the registration just under that definition.


# General chat-answering instructions injected (in the current user turn) ahead of the question.
# Authored as Markdown in the Admin → Preferences → Agent editor; sent to the model as text.
# Not knowledge-specific — these are how the character should answer, regardless of retrieval.
DEFAULT_CHAT_INSTRUCTIONS = load_prompt("chat_instructions")

# Registered here (not in the PROMPT_DEFAULTS literal above) because the constant is defined only
# now. Exposes the built-in chat instructions to the admin prompt-editor "Restore default" button
# and lets a value equal to the default prune from preferences.json like the other prompt defaults.
PROMPT_DEFAULTS["chat.instructions"] = DEFAULT_CHAT_INSTRUCTIONS


# Chat conversation-memory extraction guidance (``memory.extraction.instructions``). The
# ``{user}`` / ``{character}`` placeholders are filled with the real speaker names at ingest so the
# extractor knows which labelled speaker is the human vs the assistant. Registered in
# PROMPT_DEFAULTS so the admin prompt-editor "Restore default" restores THIS text (not blank) and a
# value equal to the default prunes from preferences.json like the other prompt defaults.
DEFAULT_MEMORY_EXTRACTION_INSTRUCTIONS = (
    'This text is a chat transcript. In it, "{user}" is the human user and "{character}" is the AI '
    "assistant/character; each line is prefixed with its speaker and timestamp. Extract facts ONLY "
    "about {user}, and only as {user} stated or explicitly confirmed them. Treat {character}'s lines "
    "purely as context for resolving what {user} refers to — never record a fact asserted by "
    "{character} that {user} did not state or confirm."
)
PROMPT_DEFAULTS["memory.extraction.instructions"] = DEFAULT_MEMORY_EXTRACTION_INSTRUCTIONS


class PromptProfile(BaseModel):
    """One named prompt in a prompt library (``memory.retrieval.prompts``). A ``locked`` profile is
    code-owned (re-seeded from its constant on every load); the owner adds their own beside it."""

    label: str = Field(default="", min_length=1)
    locked: bool = False
    prompt: str = ""


# The locked chat retrieval-agent profile: ``memory.retrieval.prompts`` always holds it, and an
# unknown or blank ``memory.retrieval.active_prompt_id`` falls back to it.
DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID = "chat"


def default_chat_retrieval_prompts() -> dict[str, PromptProfile]:
    return {
        DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID: PromptProfile(
            label="Chat (history-aware, abstain-allowed)",
            locked=True,
            prompt=DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT,
        ),
    }


_ProfileT = TypeVar("_ProfileT", bound=BaseModel)


def reseed_locked_profiles(
    current: dict[str, _ProfileT], defaults: dict[str, _ProfileT]
) -> dict[str, _ProfileT]:
    """Re-seed code-owned (``locked``) profiles from ``defaults`` so edits to the BUILT-IN defaults
    reach EXISTING workspaces, not only fresh ones.

    Locked profiles can't be edited in the UI, so their content is owned by code — but the library
    dict is persisted in ``preferences.json`` and the field's ``default_factory`` only fills ABSENT
    keys, so a stored copy silently drifts from the constant after a code edit (the stale-default
    defect). This overwrites every locked default id with its live content while leaving
    user-created (non-locked) profiles untouched. Idempotent — a no-op when the persisted text
    already equals code, so it costs nothing on an up-to-date workspace."""
    merged = dict(current)
    for pid, profile in defaults.items():
        if getattr(profile, "locked", False):
            merged[pid] = profile
    return merged


def seed_default_profiles(current: dict[str, _ProfileT], defaults: dict[str, _ProfileT]) -> None:
    """Ensure every default profile is present and ``locked`` in ``current``, in-place.

    A missing default is added outright; an existing one is re-marked locked (it's code-owned) and
    gets the default label only when its own is blank — user-tuned values on a stored copy are left
    intact. Used by the image-profile validator (the seeding step, before the reference check)."""
    for profile_id, default_profile in defaults.items():
        existing = current.get(profile_id)
        if existing is None:
            current[profile_id] = default_profile
        else:
            existing.locked = True
            if not existing.label.strip():
                existing.label = default_profile.label
