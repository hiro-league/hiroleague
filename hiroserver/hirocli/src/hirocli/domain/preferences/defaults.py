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
    tuning_profile_ref: bool = False,
    **field_kwargs: Any,
) -> Any:
    """``Field(...)`` for a preference with the admin-UI ``json_schema_extra`` metadata named.

    ``tuning_profile_ref=True`` marks a string field whose value is a ``tuning_profiles`` id. The
    root validator finds these by the marker and checks the referenced profile exists (see
    ``iter_tuning_profile_refs``), so a new profile-referencing field is validated automatically —
    schema-driven, like the admin PATCH walk, with no hand-maintained list to update. The marker is
    deliberately NOT copied into the flat admin field map (absent from
    ``preferences_schema._META_KEYS``); it is backend validation metadata only.
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
    if tuning_profile_ref:
        extra["tuning_profile_ref"] = True
    return Field(json_schema_extra=extra, **field_kwargs)


def iter_tuning_profile_refs(model: BaseModel, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(dotted_path, profile_id)`` for every field flagged ``tuning_profile_ref`` via
    ``pref_field``, recursing into nested preference models. Dict fields (``tuning_profiles`` /
    ``image_profiles``) are not traversed — only the scalar reference fields carry the marker."""
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(value, BaseModel):
            yield from iter_tuning_profile_refs(value, path)
            continue
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get("tuning_profile_ref"):
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
# LLM selection (canonical catalog ids: ``openai:gpt-5.4``)
# ---------------------------------------------------------------------------

LLMPurpose = Literal["chat", "stt", "tts"]
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


class TuningProfile(ModelTuning):
    """Named tuning preset shared by chat, memory, and knowledge answering."""

    label: str = Field(default="", min_length=1)
    locked: bool = False


DEFAULT_CHAT_TUNING_PROFILE_ID = "balanced_chat"
DEFAULT_MEMORY_TUNING_PROFILE_ID = "memory_extraction"
DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID = "knowledge_answering"
DEFAULT_KNOWLEDGE_REWRITE_TUNING_PROFILE_ID = "knowledge_rewrite"
# L3 prototype — single structured-output call per chunk that emits typed entities
# and relations. Deterministic by design (temp=0) so the same chunk produces the
# same graph mutations; reasoning off because we want JSON, not chain-of-thought.
DEFAULT_KNOWLEDGE_GRAPH_EXTRACTION_TUNING_PROFILE_ID = "knowledge_graph_extraction"
DEFAULT_KNOWLEDGE_GRAPH_DISAMBIGUATION_TUNING_PROFILE_ID = "knowledge_graph_disambiguation"
# Graphiti pivot — Graphiti uses two model tiers (ModelSize.medium / small). The
# "extraction" tier is the structured-output extraction + edge model (Graphiti
# fails on weak models per its README); the "small" tier handles cheaper sub-steps
# (node dedupe, summaries, timestamp extraction). See
# docs/knowledge-graphiti-pivot-design.md §5.1 / §10.
DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID = "graphiti_extraction"
DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID = "graphiti_small"


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
        DEFAULT_KNOWLEDGE_GRAPH_EXTRACTION_TUNING_PROFILE_ID: TuningProfile(
            label="Knowledge graph extraction (L3)",
            locked=True,
            # Single structured-output call per chunk → typed entities + relations.
            # Deterministic (temp=0) so re-ingest of the same chunk produces the same
            # graph state. Reasoning off (we want JSON, not CoT). max_tokens generous
            # because a 1200-token chunk can yield many small entity/relation rows.
            temperature=0.0,
            max_tokens=4096,
            thinking="off",
        ),
        DEFAULT_KNOWLEDGE_GRAPH_DISAMBIGUATION_TUNING_PROFILE_ID: TuningProfile(
            label="Knowledge graph entity disambiguation (L3)",
            locked=True,
            # Tiny structured-output decision: "does this mention match candidate X?"
            # Bounded output keeps cost negligible per ambiguous mention.
            temperature=0.0,
            max_tokens=512,
            thinking="off",
        ),
        DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID: TuningProfile(
            label="Graphiti extraction",
            locked=True,
            # Graphiti's main extraction + edge model (ModelSize.medium). MUST be a
            # structured-output-capable model — the README warns weak models cause
            # schema/ingestion failures. Deterministic; reasoning off (we want JSON);
            # generous budget for multi-entity episodes.
            temperature=0.0,
            max_tokens=4096,
            thinking="off",
        ),
        DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID: TuningProfile(
            label="Graphiti small (sub-steps)",
            locked=True,
            # ModelSize.small: node dedupe, summaries, timestamp extraction. Cheaper
            # than the main tier but bigger than a yes/no (summaries need room).
            temperature=0.0,
            max_tokens=2048,
            thinking="off",
        ),
    }


# ---------------------------------------------------------------------------
# Image generation profiles (image-world analog of TuningProfile)
# ---------------------------------------------------------------------------


class ImageProfile(BaseModel):
    """Named image-generation recipe: model + diffusion params + prompt scaffolding.

    The scaffolding fields (``style_prefix`` / ``style_suffix``) wrap the caller's prompt
    so a profile is a reusable *recipe*, not just numbers — the image analog of
    ``tts_instructions``. ``size`` is a hint; fixed-resolution providers (flux-1-schnell:
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


# Answering INSTRUCTIONS for the MEMORY eval's recall leg (eval_judge.answer_from_context).
# Eval-only — there is no production equivalent on this path. Markdown-structured (Objective / Core
# Instructions / Calibrators / Formatting Rules / Validation) and placed in the USER message:
# answer_from_context appends "## User Question" + "## Draft Answer" + "## Supporting Evidence"
# after it (the system prompt is a hardcoded two-line role there, MEMORY_EVAL_ANSWER_SYSTEM_PROMPT).
# Failure-targeted, from the row-by-row LoCoMo conv-43 analysis (docs/locomo-conv43-eval-analysis.md):
# the support gate + negative calibrators N1/N3/N4 close the cross-person / premise-transfer
# failures (P1, 53 rows — the prior "decline only when NOTHING relates" + unconditional commit pair
# logically forced answering with the other person's fact), and the absolute-date rules + N2 close
# the unresolved-relative-date failures (P4). Positive calibrators license derived dates and partial
# commit, guarding against an abstain relapse (the round-1 failure mode). Calibrator examples are
# SYNTHETIC by policy — never lift benchmark rows into the prompt (train-on-test leakage).
# Temporal re-optimization (conv-43 round 3): P4's absolute-date rule had collapsed the temporal
# partials into pass-or-abstain — the model declined recallable dates whenever the exact day was not
# written out (5 over-decline rows with the answer in context; F1 fell to 0.289 while evidence
# recall stayed 0.702). The fix LOOSENS the date-precision gate while KEEPING the entity gate: the
# decline trigger is relevance-only (missing person/thing), relative/derived dates are explicitly
# grounded, and answers may be given at the coarsest supported granularity. Stated as generic
# principles (no benchmark-shaped phrasings) + two synthetic calibrators (P3/P4).
# The decline phrase "No information available." is load-bearing: the abstain detector in
# answer_from_context and LoCoMo's negative-control convention key on the answer's leading text,
# so declines must stay bare (no preamble before the phrase).
DEFAULT_MEMORY_EVAL_ANSWER_PROMPT = load_prompt("memory_eval_answer")


# Grading system prompt for the eval LLM judge (eval_judge.judge_answer). Shared by both eval
# tracks. Markdown-structured like the answer prompt (Objective / Verdicts / Core Instructions /
# Output Fields / Validation); the human message presents Question / Ideal Answer / Negative
# Control / Model Answer, then the recalled elements LAST (the verdict is Answer-vs-Ideal; the
# elements only feed evidence/recall_sufficient/grounded). Deliberate features — (1) leniency
# calibration (paraphrase / partial-credit / date-tolerance) so a substantively-correct answer is
# not failed on wording; (2) the `evidence` quote GATES recall_sufficient (code-side substring
# check in judge_answer kills the ungrounded "recall_sufficient=true" hallucinations seen on
# locomo conv-43); (3) the "## Output Fields" section is LOAD-BEARING for DeepSeek thinking mode:
# with_structured_output_compat falls back to json_mode there, where pydantic field descriptions
# never reach the model — this section is the only schema it sees. Abstain keys on the answer
# prompt's decline phrase "No information available." (plus any other refusal).
DEFAULT_MEMORY_EVAL_JUDGE_PROMPT = load_prompt("memory_eval_judge")


# System prompt for the agentic memory-retrieval loop (agentic-memory-retrieval-design §5.3).
# Resolved from ``graph.eval.retrieval_agent_prompts``; blank profile text falls back here.
DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT = load_prompt("memory_eval_retrieval_agent")


# Chat sibling of the retrieval-agent prompt (memory-eval-vs-chat-parity, Phase 1). Same loop, but
# history-aware (recent turns are fed in) and abstain-allowed (may skip searching when the message
# needs no memory), and its final turn is a GROUNDING NOTE for the persona — not a user-facing reply.
# Hosted in the SAME ``graph.eval.retrieval_agent_prompts`` library (multi-prompt hosts both); the
# formal ``memory.retrieval.*`` split with its own admin-selectable active id is deferred.
DEFAULT_MEMORY_CHAT_RETRIEVAL_AGENT_PROMPT = load_prompt("memory_chat_retrieval_agent")


# Dotted preference path → built-in default text for every editable system prompt. Exposed in the
# admin /preferences payload so the UI can offer "Restore default" on prompt editors: once a prompt
# is saved as "" the pydantic default never re-applies (defaults only fill ABSENT JSON keys), so the
# engine silently falls back at runtime while the admin UI shows blank with no way to recover the
# default text. Keep in sync with the prompt fields on the models below (guarded by a domain test).
# Note: the mem-eval answer prompt is NOT here anymore — it became a named library
# (``graph.eval.answer_prompts``), so its built-in default text is carried by the locked
# ``default`` profile (see ``default_answer_prompts``), which doubles as the UI's "Restore default"
# source. Pruning by flat path no longer applies to it (a dict is always materialized, like
# ``tuning_profiles`` / ``image_profiles``).
PROMPT_DEFAULTS: dict[str, str] = {
    "knowledge.answering.prompt": DEFAULT_KNOWLEDGE_ANSWERING_PROMPT,
    "knowledge.rewrite.prompt": DEFAULT_KNOWLEDGE_REWRITE_PROMPT,
    "graph.eval.judge_prompt": DEFAULT_MEMORY_EVAL_JUDGE_PROMPT,
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


class AnswerPromptProfile(BaseModel):
    """A named mem-eval answer-prompt recipe — the answer analog of ``ImageProfile`` / tuning
    profiles. A run picks which profile's instruction block the memory-eval recall leg uses
    (``eval_judge.answer_from_context`` places it in the user message ahead of the question +
    recalled elements). Memory-track only — the knowledge track answers with the production
    pipeline, so it has no answer-prompt library.

    No structured-output contract applies (unlike the judge): the answer step is plain free-text
    generation. The one soft convention — the decline phrase "No information available." — stays
    EMBEDDED in each profile body (the abstain label detector + the judge key on it); an author
    editing a duplicated profile is responsible for keeping it. Blank ``prompt`` ⇒ the runtime
    falls back to ``DEFAULT_MEMORY_EVAL_ANSWER_PROMPT`` (see ``resolve_answer_prompt``)."""

    label: str = Field(default="", min_length=1)
    locked: bool = False
    prompt: str = ""


# Built-in answer-prompt id, always present (``default_answer_prompts`` + the frontend normalizer
# seed it). It is locked and carries the full default text, so it doubles as the "Restore default"
# source for the admin UI (the answer prompt no longer has a ``PROMPT_DEFAULTS`` entry).
DEFAULT_ANSWER_PROMPT_ID = "default"


def default_answer_prompts() -> dict[str, AnswerPromptProfile]:
    return {
        DEFAULT_ANSWER_PROMPT_ID: AnswerPromptProfile(
            label="Default (grounded)",
            locked=True,
            prompt=DEFAULT_MEMORY_EVAL_ANSWER_PROMPT,
        ),
    }


DEFAULT_RETRIEVAL_AGENT_PROMPT_ID = "default"
# Locked chat-retrieval profile id in the SAME library — chat resolves this fixed id (Phase 1);
# an admin-selectable chat active id is part of the deferred ``memory.retrieval.*`` split.
DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID = "chat"


def default_retrieval_agent_prompts() -> dict[str, AnswerPromptProfile]:
    return {
        DEFAULT_RETRIEVAL_AGENT_PROMPT_ID: AnswerPromptProfile(
            label="Default (eval)",
            locked=True,
            prompt=DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT,
        ),
        DEFAULT_CHAT_RETRIEVAL_AGENT_PROMPT_ID: AnswerPromptProfile(
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
    intact. Shared by the tuning- and image-profile validators (the seeding step, before the
    reference checks)."""
    for profile_id, default_profile in defaults.items():
        existing = current.get(profile_id)
        if existing is None:
            current[profile_id] = default_profile
        else:
            existing.locked = True
            if not existing.label.strip():
                existing.label = default_profile.label
