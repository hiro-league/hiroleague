"""Workspace preferences — single source of truth for configurable choices.

``preferences.json`` holds LLM default selections (canonical catalog ids), profile-based
tuning, voice/audio, and memory settings. Provider secrets live in the credential
store (``providers.json`` + OS keyring), not here.

Storage: ``<workspace>/preferences.json`` — Pydantic model serialised to JSON.
"""

from __future__ import annotations

import json
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


class LLMPreferences(BaseModel):
    """Which catalog models to use when the workspace has credentials for them."""

    default_chat: str | None = None
    default_stt: str | None = None
    default_tts: str | None = None
    default_image_gen: str | None = None
    default_tuning_profile: str = DEFAULT_CHAT_TUNING_PROFILE_ID
    default_image_profile: str = DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID


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


class MemorySearchPreferences(BaseModel):
    """Retrieval-time tuning for ``MemoryService.search``."""

    # When false, ``memory_search`` is skipped — no long-term memory is injected before the reply
    # (independent of extraction). No-op unless ``memory.enabled``.
    enabled: bool = True
    top_k: int = Field(default=DEFAULT_MEMORY_SEARCH_TOP_K, ge=1, le=100)


class MemoryExtractionPreferences(BaseModel):
    """Whether the agent stores new long-term memories after a reply (memory_out)."""

    # When false, ``_store_turn_memory`` is skipped — memory becomes read-only (it stops growing)
    # while search may still inject existing memories. No-op unless ``memory.enabled``.
    enabled: bool = True


class MemoryPreferences(BaseModel):
    """Agent memory settings — a thin feature layer over the shared Graphiti graph engine.

    Gated purely by ``enabled``; the engine (extraction model, embedder, search) comes from
    the top-level ``graph`` preferences, and ``create_memory_service`` degrades to ``None``
    when that engine can't be built. The mem0-legacy model / embedder / reranker fields are
    gone (mem0 → Graphiti, Phase 5)."""

    enabled: bool = False
    default_tuning_profile: str = DEFAULT_MEMORY_TUNING_PROFILE_ID
    # A1 fix: the human's name, used as the Graphiti *speaker label* when ingesting the user's
    # turns. Graphiti extracts the speaker (the token before the ":") as the anchor entity, so a
    # real name produces a clean `Misho` Person hub instead of a generic `User` node, and every
    # fact the user states attaches to it. Empty ⇒ falls back to "User" (prior behavior).
    # IMPORTANT: keep this STABLE. Graphiti never auto-renames nodes, so changing it mid-history
    # forks a SECOND hub and fragments the user's memory — set it once, early.
    user_name: str = Field(default="", max_length=120)
    search: MemorySearchPreferences = Field(default_factory=MemorySearchPreferences)
    extraction: MemoryExtractionPreferences = Field(default_factory=MemoryExtractionPreferences)


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
    "Rewrite the user's question into one clean, standalone search query.\n\n"
    "Fix typos and normalize informal or dialectal phrasing into clear formal language, "
    "but do NOT change the meaning or add information that is not in the question.\n\n"
    "If a conversation is provided, resolve references (pronouns, 'the second one', "
    "'his brother') against it so the query stands alone without the conversation.\n\n"
    "Copy proper nouns, names, dates, and identifiers VERBATIM into `keywords` — never "
    "translate or 'correct' a name.\n\n"
    "Set `knowledge_needed` to false when the message is just a greeting, farewell, thanks, "
    "acknowledgement, or small talk and clearly does not ask for stored information; otherwise "
    "true. Do not invent facts or answer the question.\n\n"
    # The output shape is spelled out in the prompt (not left to the schema alone) because some
    # providers — e.g. DeepSeek thinking mode — fall back to JSON-mode structured output, which
    # never sees the pydantic field descriptions; the model knows the fields only from this text.
    "Respond with a JSON object containing exactly these fields:\n"
    "- `standalone_query` (string): the rewritten standalone search query.\n"
    "- `keywords` (array of strings): proper nouns, names, dates, and identifiers copied verbatim.\n"
    "- `knowledge_needed` (boolean): false only for greetings/thanks/small talk, otherwise true.\n"
    "- `entities` (array of strings): named entities the question asks about (people, places, "
    "organizations) and qualified relational mentions like 'my sister' or 'mom'; empty when the "
    "question references no specific entity (e.g. 'what is photosynthesis?')."
)


# System prompt for the answer-generation step. Editable in preferences; the answer node falls
# back to this constant when the stored prompt is blank. Relaxed (vs. the old all-or-nothing
# wording) so multi-part questions degrade gracefully: it keeps the facts-only-from-context guard
# but explicitly allows PARTIAL answers and forbids a bare "I don't know" when any part is
# supported. Safe because the empty-context case is gated upstream by ``no_results`` and never
# reaches this prompt. Citation + language clauses are appended at runtime from the other answering
# prefs, so they are intentionally not part of this text.
DEFAULT_KNOWLEDGE_ANSWERING_PROMPT = (
    "Use the provided knowledge context as your only source of facts; "
    "do not invent or assume anything that is not supported by it.\n\n"
    "Answer every part of the question that the context supports. Partial answers are expected "
    "and welcome — never withhold a supported part just because another part is unsupported.\n\n"
    "If a part of the question is not covered by the context, give the parts you can and briefly "
    "note what is missing. Do not reply with only 'I don't know' when any part of the question is "
    "supported by the context."
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


class KnowledgeRerankerPreferences(BaseModel):
    """Cross-encoder reranker over retrieved candidates (precision step).

    Prefs-only, default off. ``model_id`` is a catalog ``provider:model`` (cloud: Voyage /
    Cohere) OR a local-registry id (FlashRank / FastEmbed / sentence-transformers). It is
    resolved by ``resolve_reranker`` to a LangChain ``BaseDocumentCompressor`` — the same way
    ``default_embedding_model`` is resolved by the embedder. Rerankers are dimensionless, so a
    swap is a hot config change (no re-ingest). ``device`` / ``batch_size`` apply to the local
    torch lane only and are ignored by cloud models. ``model_id`` null = no reranker (retrieval
    order used as-is) even when ``enabled`` is true.
    """

    enabled: bool = False
    model_id: str | None = None
    top_n: int = Field(default=8, ge=1, le=100)
    device: str | None = None
    batch_size: int = Field(default=32, ge=1, le=512)


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
    reranker: KnowledgeRerankerPreferences = Field(default_factory=KnowledgeRerankerPreferences)


class KnowledgeAnsweringPreferences(BaseModel):
    model: str | None = None
    # Base answer-generation system prompt. Editable; blank falls back to the relaxed default
    # (partial answers allowed, no bare "I don't know" when any part is supported). The citation
    # and language clauses are appended at runtime from the fields below.
    prompt: str = DEFAULT_KNOWLEDGE_ANSWERING_PROMPT
    cite_sources: bool = True
    language_policy: Literal["match_query", "prefer_english", "prefer_arabic"] = "match_query"


class KnowledgeRewritePreferences(BaseModel):
    # Optional LLM query rewrite for the Ask tab: normalize + extract literal keywords before
    # retrieval. Reuses the resolved answering model. ``default_on`` seeds the Ask-tab toggle.
    prompt: str = DEFAULT_KNOWLEDGE_REWRITE_PROMPT
    default_on: bool = False


KnowledgeGraphBackend = Literal["off", "graphiti"]
KnowledgeGraphTemporalDefault = Literal["current", "all"]
KnowledgeGraphSearchRecipe = Literal["rrf", "mmr", "cross_encoder"]
# Which graphiti search legs participate in fact recall (decision: extends D3 → attribute
# memory + raw-turn fallback). Orthogonal to ``search_recipe`` (which ranks WITHIN each leg).
#   "edges"                 → EntityEdge facts only (today's behavior; precise, no attribute recall)
#   "edges_and_nodes"       → + EntityNode.summary  (closes the "Misho turned 50" gap)
#   "edges_nodes_episodes"  → + EpisodicNode bodies (last-resort BM25 recall over raw turn text)
KnowledgeGraphSearchScope = Literal["edges", "edges_and_nodes", "edges_nodes_episodes"]
# Entity-extraction ontology at INGEST (built into the graph, so a change needs a re-ingest):
#   "open"  → pass no entity_types to Graphiti; it extracts freely (everything → base ``Entity``).
#             Broadest recall — captures activities/interests/media/preferences the typed list omits
#             (e.g. "surfing", "fantasy genre", a book title). Matches the Zep/Graphiti LoCoMo setup.
#   "typed" → pin the 5-type personal-KG vocabulary (Person/Place/Organization/Event/Object); precise
#             but drops first-person activity/preference facts that don't fit those types.
KnowledgeGraphEntityOntology = Literal["open", "typed"]
# Graph observability tier for graph ingest + retrieval (docs §12.2). Single dial, supersets:
#   "off"    → no graphiti ledger rows / tracer / usage sinks (spare CPU; graphiti cost NOT folded).
#   "ledger" → ONE priced roll-up row per episode (ingest) + per search (rerank); cost folds. PROD.
#   "trace"  → ledger + the deep per-stage JSONL sidecars (retrieval re-host + ingest stages).
# Named ``Graph*`` (not ``KnowledgeGraph*``): the graph layer serves BOTH knowledge facts and
# conversation memory (``prefs.graph`` is shared, top-level).
GraphObservability = Literal["off", "ledger", "trace"]


class KnowledgeGraphRerankerPreferences(BaseModel):
    """Cross-encoder reranker for the graph fact-search leg.

    Only takes effect when ``GraphPreferences.search_recipe == 'cross_encoder'``
    (the admin UI greys this whole group out otherwise). Every field is resolved by the
    SAME ``resolve_reranker`` the flat Qdrant path uses, so cloud (Cohere/Voyage) and
    local (FlashRank/FastEmbed/sentence-transformers) models are both available — and a
    local model that was never downloaded fails fast, degrading the fact search to RRF
    (no silent fetch). ``model_id`` null = reuse the knowledge reranker model
    (``knowledge.retrieval.reranker.model_id``) — one model to manage (the G8 play).
    """

    # null → fall back to the shared knowledge reranker model id.
    model_id: str | None = None
    # Drop facts whose post-rerank relevance is below this (maps to Graphiti
    # ``SearchConfig.reranker_min_score``). 0.0 = keep all. Cross-encoder only —
    # RRF/MMR scores are rank-fusion artifacts, so this is ignored for those recipes.
    min_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    # Local torch lane only (sentence-transformers); ignored by cloud + ONNX models.
    device: str | None = None


# Answering INSTRUCTIONS for the MEMORY eval's recall leg (eval_judge.answer_from_context).
# Eval-only — there is no production equivalent on this path. Markdown-structured (Objective / Core
# Instructions / Calibrators / Formatting Rules / Validation) and placed in the USER message:
# answer_from_context appends "## User Question" + "## Recalled Memory Elements" after it (the
# system prompt is a hardcoded two-line role there, MEMORY_EVAL_ANSWER_SYSTEM_PROMPT).
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
DEFAULT_MEMORY_EVAL_ANSWER_PROMPT = """\
## Objective
Answer the User Question using the Recalled Memory Elements below — context from past
conversations. Keep facts grounded in that memory, but draw on general world knowledge to reason
or recommend when memory alone doesn't reach the answer.

## The three dates (any may be missing)
- **stated** — when it was said; shown as a leading [DATE]. The ONLY date you resolve relative
  time phrases against.
- **as of** — when the fact became TRUE. Already absolute.
- **until** — when the fact stopped being true. Already absolute.

## Element formats
- Relevant Facts — "[stated] fact text [RELATION · as of: D · until: D]" (only the dates that
  exist are shown).
- Relevant Entities — "NAME (TYPE): SUMMARY". The summary fuses many details and the answer is
  often there.
- Relevant Messages — "[stated] TEXT".

## Core rule
- Resolve a relative phrase ("five years ago", "next month") ONLY against the **stated** [DATE];
  report the absolute value, never the phrase.
- **as of** / **until** are already resolved — when asked when a fact began or ended, report them
  directly; never re-apply a relative phrase to them.
- Read every provided element — facts, and any entities or messages present. The answer is often
  spread across several, including chains through another person, place, or thing; combine them.
- An element supports an answer about a person only if it shows THAT person doing, having, or
  experiencing the thing asked — and the specific thing asked, not a related one.
- When similar events occur at different dates, the question's timeframe picks the right one — not
  the order elements appear in. Prefer the LATEST **as of** when facts directly conflict.
- For list or count questions, scan ALL elements — facts, entity summaries, and messages — and
  include every DISTINCT match before answering. A partial list is a wrong answer.
- If a **## Computed Results** section is present, it is the system's deterministic computation
  (a count, a duration, conflict tallies) over the recalled elements — report THAT exact value
  instead of recounting or doing the date math yourself. The elements remain for wording and
  attribution (e.g. naming the items behind a count).
- If any element passes the support checks, commit: give the supported part(s) directly, even when
  other parts are unsupported.
- Give the most precise time the dates support (day if pinned, else month/year). A missing,
  relative, or low-precision date is NEVER itself a reason to decline.

## Positive Calibrators
P1 — computed dates are grounded

q: When did Maya start pottery?

r: [2024-06-20] Maya has been doing pottery for five years.

a: 2019.

behavior: no **as of**, so resolve "five years" against the stated date (2024 − 5); a computed
date is grounded, not invented.

P2 — commit to the supported part

q: Where and when did Alex get his dog?

r: [2024-04-15] Alex adopted his dog from a shelter.

a: From a shelter.

behavior: "where" is supported; an unsupported "when" is no reason to decline everything.

P3 — answer at the supported granularity

q: When did Maya live abroad?

r: Maya was on an exchange program in Lisbon. [as of: 2022-09-01 · until: 2023-06-30]

a: September 2022 to June 2023.

behavior: report the as of → until window directly — coarser-but-correct beats over-precision or
a decline.

## Negative Calibrators
N1 — already-resolved date, not re-subtracted

q: What year did John start surfing?

r: [2023-07-16] John started surfing five years ago. [STARTED · as of: 2018-07-16]

✗ 2013   ✓ 2018

behavior: **as of** is the resolved event date — report it; do NOT re-apply "five years ago" to it.

N2 — relative time echoed verbatim

q: When is Maya moving to Berlin?

r: [2024-03-12] Maya plans to move to Berlin next month.

✗ Next month   ✓ April 2024

behavior: resolve relative wording against the stated date; never echo it.

N3 — cross-person transfer

q: Which company did Alex join?

r: [2024-05-02] Sara joined Acme Corp as a designer.

✗ Acme Corp   ✗ Sara joined Acme Corp   ✓ No information available.

behavior: the only joining fact is Sara's — reusing it for Alex, or dropping the name to hide the
mismatch, are both wrong.

N4 — related fact bent to the question

q: What band did Alex start?

r: [2024-02-10] Alex joined a weekly jazz jam group.

✗ A jazz jam group   ✓ No information available.

behavior: joining a jam group is not starting a band; a related fact is not reshaped to fit the
question.

N5 — asking is not doing

q: How did Sara's marathon go?

r: [2024-05-12] Sara: That's awesome! How was your marathon?

✗ It went well…   ✓ No information available.

behavior: Sara only asked; a question or reaction is never the person's own experience.

## Formatting
- Answer directly; no preamble. For a single-fact question, be terse (a short phrase or value).
  For list / count / "which / what … (all)" questions, completeness outranks brevity — list every
  matching element; do not stop at the first few.
- Dates: absolute only — exact day if pinned, else month + year; "the week of {date}" for week
  questions.
- Name the person the answer is about.
- Decline (reply exactly: No information available.) only when neither the memory nor related
  world knowledge can answer.

## Validation
Before finalizing, verify:
- every claim traces to an element about the right person and the right thing;
- no relative time wording remains in the answer;
- list/count answers include every matching element found."""


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
DEFAULT_MEMORY_EVAL_JUDGE_PROMPT = """\
## Objective
Grade a model's Answer to a question about past conversations against the Ideal Answer, and
report the result as a single JSON object (see Output Fields). Grade ONLY against the Ideal
Answer — never your own knowledge.

## Verdicts
- pass: the Answer conveys the same fact(s) as the Ideal. Judge meaning, not wording —
  paraphrases, extra detail, and answers MORE specific than the Ideal all pass.
- partial: at least one correct item of a multi-part Ideal, or the right fact at lower precision
  than the Ideal.
- fail: contradicts the Ideal or answers something else.
- abstain: the Answer declines — "No information available." or any other refusal to answer.

## Core Instructions
- Dates: matching the Ideal's month and year passes; a correctly resolved relative date ("next
  month" stated in an August conversation = September) passes; within ~2 weeks passes.
- Negative Control = YES means declining is the correct outcome: an abstaining Answer is the
  right result, and a confident Answer is fail.
- The Recalled Memory Elements are what the answerer saw. They must NEVER change the verdict —
  use them only to fill evidence, recall_sufficient, and grounded.

## Output Fields
Reply with one JSON object containing exactly these fields, in this order:
- "evidence" (string): the exact line(s) copied VERBATIM from the Recalled Memory Elements that
  contain the information needed to answer; "" if no such line exists.
- "recall_sufficient" (boolean): true only if evidence quotes a real line that supplies the
  answer; false otherwise.
- "grounded" (boolean): whether the Answer is supported by the Recalled Memory Elements.
- "reason" (string): one short sentence justifying the verdict.
- "verdict" (string): one of "pass", "partial", "fail", "abstain".

## Validation
- evidence is checked by exact substring match against the shown elements — an inexact or
  invented quote counts as no evidence and forces recall_sufficient to false.
- If no Recalled Memory Elements section was shown, set evidence "" and recall_sufficient true.
- The verdict depends only on Answer vs Ideal."""


# System prompt for the agentic memory-retrieval loop (agentic-memory-retrieval-design §5.3).
# Resolved from ``graph.eval.retrieval_agent_prompts``; blank profile text falls back here.
DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT = """\
## Objective
You retrieve facts from past conversations to answer the user's question. You cannot read the
memory directly — call `search_memory`. Each call carries a `queries` list of 1..{MAX_PARALLEL_SEARCHES}
sub-queries — that's how you DECOMPOSE a multi-part question into sub-questions that run together.
You may call `search_memory` on several turns (one call per turn), observing each return before
deciding to search again or to answer. You have {MAX_AGENT_TURNS} agent turns total — that
INCLUDES your final-answer turn, so plan accordingly. If the memory genuinely lacks the detail,
say so — do not guess.

## Element formats
Results arrive as a mix of three element kinds, each shaped differently — use them accordingly:
  - edge (fact) → a dated relational claim. JSON fields: `relation` (e.g. PLANS_TO_WATCH), `stated`
                  (when it was said) and `as_of` (when it became true) — shown whenever the fact has
                  them — plus `until` (when it stopped being true) only when `show_expiry` is on.
                  The ONLY kind that carries validity, so latest / ever-never / change-over-time live here.
  - entity      → a standing who/what profile (`name` + `entity_type` + `summary`); NO dates —
                  context, not a timeline; cannot be ordered by time.
  - episode     → a verbatim conversation turn with ONE `stated` timestamp; no invalidation.

## Method
  1. Rephrase the question as a STORED FACT, not as the user asked it — drop "can you",
     "how many", "walk me through". The index sees facts, not requests.
  2. **DECOMPOSE if the question is plural.** If it asks about several distinct things
     (multiple subjects, several time windows, "X and Y and Z", a comparison, a list across
     unrelated topics), split it into independent sub-questions and put them as multiple entries
     in the `queries` list of ONE `search_memory` call (up to {MAX_PARALLEL_SEARCHES} entries).
     Each sub-question gets its own `query` + knobs + `goal`. If the question is singular, a
     single-entry list is fine.
  3. Decide the AXIS each (sub-)question lives on: current value/state · change over time ·
     ever/never · count · ordering · synthesis · something else you name yourself.
  4. Choose the four knobs to match that axis (see "Knobs" below) — independently per
     sub-question; they can differ.
  5. Read what came back. Topically-related facts that don't supply a piece the answer
     needs are a "wrong axis" miss — rephrase toward the missing piece, don't just widen.
     If a piece is thin on the right axis, raise `limit` (or `hops`). If a search adds
     nothing new (`new=0`), the phrasing is exhausted — change the axis, don't repeat it.
     Stop only when you can construct the answer (see "Stopping").

## Knobs (compact reference)
  query        → a stored-fact phrasing of what's needed.
  temporal     → "current" for the state that holds now; "all" when the question is about
                 change over time, or whether something ever/never happened.
  limit        → start at the default; raise (up to {MAX_LIMIT}) only when a piece is on the
                 right axis but thin AND rephrasing didn't help.
  hops         → 1 direct; 2 if the answer links one entity to another; 3 for two links.
  show_expiry  → true to ALSO see `until` (when a fact stopped being true) on edges — for timeline /
                 change questions. `stated` and `as_of` are shown without it. Only meaningful
                 with `temporal="all"`.

## Reduce ops (optional, declared on your FINAL turn)
If the answer needs a precise count, an ordering, the latest value, a duration between two
facts, or both sides of an "ever/never", request the matching reduce instead of computing it
yourself — the system runs it deterministically.
  distinct_count · order_by_time · latest · date_diff · keep_conflicting
Omit `reduce` (or `op: none`) to answer straight from the deduped accumulator.

## Positive Calibrators (synthetic; NOT drawn from any benchmark)
P1 — current value
  q: What's the user's monthly book budget?
  knobs: temporal=current, limit=20, hops=1, show_expiry=false. No reduce.
  behavior: one search, take the valid-now edge; answer.

P2 — change over time
  q: How has the book budget changed?
  knobs: temporal=all, show_expiry=true, hops=1. reduce.op=order_by_time.
  behavior: surface current + retired edges with their `as_of` / `until` dates; let the reduce order them.

P3 — ever/never
  q: Have they ever mentioned disliking a genre?
  behavior: ONE `search_memory` call with TWO entries in `queries` — one affirming phrasing,
  one negating phrasing. Then reduce.op=keep_conflicting to present both polarities.

P4 — decomposition of a plural question
  q: What's the user's current job, their main hobby, and their last trip?
  behavior: ONE `search_memory` call with THREE entries in `queries` — one per sub-question,
  each with its own query/goal (job: temporal=current; hobby: temporal=current; trip:
  temporal=all, reduce later with `latest`). Read all three sub-results together; answer in one go.

## Negative Calibrators (don't burn the search budget badly)
N1 — `new=0` (or a fuller-but-still-wrong-axis return) + same query + higher limit is NOT
     progress. When a search adds nothing you can use, the phrasing is wrong; rephrase first,
     then widen.
N2 — hops=3 only when the answer chains TWO entities. Otherwise it just slows the search and
     adds distractors.
N3 — show_expiry=true under temporal=current is wasted — every returned edge is valid-now and
     has no `until`.
N4 — never answer from the question alone. If your turns run out and nothing supports the
     answer, abstain.
N5 — do NOT decompose a singular question into N near-duplicate entries in `queries` to "cover
     more ground." Sub-queries are for genuinely independent sub-questions; three rephrasings of
     the same question just burns the budget and clogs the accumulator with topical distractors.
N6 — do NOT put more than {MAX_PARALLEL_SEARCHES} entries in `queries`; the call is rejected and
     you waste a turn on the error round-trip.

## Stopping & abstaining
Before you stop, name what the question needs to be answerable — the evidence and HOW it
combines into the answer: a single value; a set you must enumerate and count; two dated facts
to compare or subtract; both sides of a claim to confirm or deny; or several facts that
together imply it. Stop only when the accumulator supplies every piece your own requirement
names — not merely when related facts came back. If your turns run out and a required piece is
still missing, abstain in the final turn — do not pad with guesses.

## Validation (pre-final-turn self-check)
- Did I rephrase the question into a stored-fact form before the first search?
- If the question is plural, did I DECOMPOSE it into multiple entries in the `queries` list of
  one call, instead of an omnibus single query? Conversely, if it's singular, did I avoid
  near-duplicate sub-queries?
- Did I state what the answer requires and confirm the accumulator supplies every piece —
  rather than stopping just because related facts came back?
- For a temporal / ever-never question, did I either set show_expiry=true under temporal=all,
  or include BOTH polarities as two entries in `queries`?
- For a count / ordering / duration, did I declare the matching reduce op instead of
  computing it myself?"""


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


def default_retrieval_agent_prompts() -> dict[str, AnswerPromptProfile]:
    return {
        DEFAULT_RETRIEVAL_AGENT_PROMPT_ID: AnswerPromptProfile(
            label="Default",
            locked=True,
            prompt=DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT,
        ),
    }


class RetrievalAgentLimits(BaseModel):
    """Caps and clamp bounds for the agentic memory-retrieval loop (eval + chat parity)."""

    # Number of LLM turns the agent gets across the whole loop, INCLUDING the final-answer turn
    # (every invocation costs tokens). On the last allowed turn the model is invoked without tools
    # so it must answer. (P9 rename: was ``max_searches``; the counter advances per turn, not per
    # dispatched search call.)
    max_agent_turns: int = Field(default=4, ge=1, le=10)
    # Sub-queries per single ``search_memory`` call (the decomposition fan-out). Enforced by the
    # tool against the configured value; one global value for eval and chat.
    max_parallel_searches: int = Field(default=3, ge=1, le=5)
    limit_default: int = Field(default=20, ge=1, le=100)
    limit_min: int = Field(default=10, ge=1, le=100)
    limit_max: int = Field(default=40, ge=1, le=100)
    hops_max: int = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def _coherent_limits(self) -> "RetrievalAgentLimits":
        if self.limit_min > self.limit_default or self.limit_default > self.limit_max:
            raise ValueError("limit_min ≤ limit_default ≤ limit_max")
        return self


class GraphViewPreferences(BaseModel):
    """Admin graph-VIZ display knobs for the shared Knowledge/Memories Graph tab.

    Pure frontend-display settings: they tune how the force-graph view's per-node-type
    filter dropdowns behave, NOT how facts are extracted, searched, or retrieved. The
    graph engine ignores everything here.
    """

    # A node TYPE whose instance count exceeds this shows a "many instances" perf
    # heads-up inside its per-type filter dropdown (the dropdown still lists + searches
    # every instance — this only flags very large types so the user reaches for search).
    large_type_threshold: int = Field(default=200, ge=10, le=10000)


class GraphEvalPreferences(BaseModel):
    """Eval-only answering knobs, surfaced under the shared Graphiti engine settings.

    ``answer_prompts`` is a named LIBRARY of answering INSTRUCTION blocks for the memory-eval
    recall leg (``eval_judge.answer_from_context`` places the chosen one in the user message ahead
    of the question and the recalled elements; the system prompt there is a hardcoded two-line
    role). A run selects one by id in the eval panel — see ``resolve_answer_prompt``.
    The knowledge-eval legs intentionally have no answer-prompt library:
    they run the real ``KnowledgeAgentGraph`` and so are graded against the PRODUCTION
    ``knowledge.answering.prompt`` (forking it would make the knowledge eval stop measuring real
    behavior). The admin UI surfaces that production prompt alongside this one for convenience.

    ``judge_prompt`` is the grading system prompt for the LLM judge (``eval_judge.judge_answer``),
    shared by both tracks. Editable/visible for reference; blank falls back to the relaxed default.
    """

    # Named library of mem-eval answer-prompt recipes (replaces the former single
    # ``memory_answer_prompt`` scalar — no-backward-compat, no migration). A run picks one by id
    # in the eval panel; ``resolve_answer_prompt`` maps id → instruction text with a default
    # fallback. The ``default`` profile is locked and carries the built-in default text.
    answer_prompts: dict[str, AnswerPromptProfile] = Field(default_factory=default_answer_prompts)
    judge_prompt: str = DEFAULT_MEMORY_EVAL_JUDGE_PROMPT
    # Answer + judge each get their OWN model + tuning profile (split from the single shared
    # answering model the eval used before). ``*_model`` of ``None`` falls back through
    # ``knowledge.answering.model`` → ``llm.default_chat`` (the prior behavior), so an unset
    # workspace is unchanged. The defaults reuse the ``knowledge_answering`` tuning profile —
    # set them apart to tune the answer step and the judge independently. The memory-eval answer
    # step uses ``answer_*``; the LLM judge (both tracks) uses ``judge_*``.
    answer_model: str | None = None
    answer_tuning_profile: str = DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID
    judge_model: str | None = None
    judge_tuning_profile: str = DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID
    # The agentic retrieval loop (memory track) gets its OWN model + tuning profile. ``None`` falls
    # back to the eval ANSWER model (the loop borrowed it before it had its own preference): the
    # resolver chains retrieval_model → answer_model → knowledge.answering.model → llm.default_chat,
    # so an unset workspace is unchanged. Lets the retrieval/tool-calling step use a different model
    # (e.g. a cheaper or higher-reasoning one) than the final answer step.
    retrieval_model: str | None = None
    retrieval_tuning_profile: str = DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID
    # Recalled-context render toggles (eval only): which temporal annotations each recalled FACT
    # line carries, and whether episodes keep their [date] prefix. ``show_event_time`` (valid_at,
    # labeled "event_time") also governs the episode [date]; ``show_expired_at`` (invalid_at) and
    # ``show_superseded`` annotate supersession. Defaults = a single timestamp per fact (Zep-style):
    # event_time on, the rest off. Applied identically to the answer, judge, and evidence-check
    # renders of a question (see eval_judge.RecallRenderOptions).
    show_event_time: bool = True
    show_expired_at: bool = False
    show_superseded: bool = False
    # Agentic retrieval loop caps/clamps (agentic-memory-retrieval-design §5.2). One global
    # value for eval and chat — do not split per surface.
    retrieval_agent: RetrievalAgentLimits = Field(default_factory=RetrievalAgentLimits)
    # Named library of retrieval-agent system prompts (mirrors answer_prompts).
    retrieval_agent_prompts: dict[str, AnswerPromptProfile] = Field(
        default_factory=default_retrieval_agent_prompts
    )
    active_retrieval_agent_prompt_id: str = DEFAULT_RETRIEVAL_AGENT_PROMPT_ID

    def resolve_answer_prompt(self, profile_id: str | None) -> tuple[str, str]:
        """Resolve a mem-eval answer-prompt profile id → ``(label, instruction_text)``.

        Falls back to the locked ``default`` profile when the id is unknown/blank, then to the
        built-in constant when even that is missing or its text is blank. The runner uses this to
        turn the run's ``answer_prompt_id`` into the instruction block + a provenance label."""
        pid = (profile_id or "").strip()
        profile = self.answer_prompts.get(pid) or self.answer_prompts.get(DEFAULT_ANSWER_PROMPT_ID)
        if profile is None:
            return (DEFAULT_ANSWER_PROMPT_ID, DEFAULT_MEMORY_EVAL_ANSWER_PROMPT)
        text = (profile.prompt or "").strip() or DEFAULT_MEMORY_EVAL_ANSWER_PROMPT
        return (profile.label or pid or DEFAULT_ANSWER_PROMPT_ID, text)

    def resolve_retrieval_agent_prompt(self) -> tuple[str, str]:
        """Resolve the active retrieval-agent prompt profile → ``(id, text)``.

        Blank profile text falls back to ``DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT``."""
        active = (self.active_retrieval_agent_prompt_id or "").strip() or DEFAULT_RETRIEVAL_AGENT_PROMPT_ID
        profile = self.retrieval_agent_prompts.get(active) or self.retrieval_agent_prompts.get(
            DEFAULT_RETRIEVAL_AGENT_PROMPT_ID
        )
        if profile is None:
            return (DEFAULT_RETRIEVAL_AGENT_PROMPT_ID, DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT)
        text = (profile.prompt or "").strip() or DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT
        return (active, text)


class GraphPreferences(BaseModel):
    """Graphiti-backed temporal knowledge graph (the pivot from the earlier L3 graph slice).

    ``backend`` is the master switch: ``off`` = flat Qdrant only (today); ``graphiti``
    = answer from graph facts; ``mix`` = fuse graph facts with Qdrant passages (the
    recommended path, decision G4). Every other field is an admin-settable knob — no
    hardcoded params. See docs/knowledge-graphiti-pivot-design.md §9–10.
    """

    backend: KnowledgeGraphBackend = "off"
    # Model ids — ``None`` falls back through knowledge.answering.model → llm.default_chat.
    extraction_model: str | None = None
    extraction_tuning_profile: str = DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID
    small_model: str | None = None
    small_tuning_profile: str = DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID
    # ``None`` → shares the knowledge dense embedder (decision G8).
    embedder_model: str | None = None
    # Default temporal lens at retrieval: current facts only vs include historical.
    temporal_default: KnowledgeGraphTemporalDefault = "current"
    # Retrieval expansion radius (hops) when gathering related facts/chunks.
    k_hop: int = Field(default=1, ge=1, le=3)
    # Graphiti search rerank recipe for the fact-search leg.
    search_recipe: KnowledgeGraphSearchRecipe = "rrf"
    # Which graph elements the fact-search reads from (decision: extends D3). Default keeps
    # today's behavior; lift to ``edges_and_nodes`` to recall attribute memories that live on
    # ``EntityNode.summary`` (e.g. "Misho turned 50…"). ``edges_nodes_episodes`` also matches
    # raw conversation text via BM25 — useful as a last-resort recall when structured layers
    # miss; precision suffers. See :meth:`_validate_search_scope_recipe` for the MMR×episodes
    # incompatibility (graphiti-core's ``EpisodeReranker`` has no MMR).
    search_scope: KnowledgeGraphSearchScope = "edges"
    # Extraction ontology at ingest. "open" (default) extracts freely (broadest recall — captures
    # activities/interests/media/preferences); "typed" pins the 5-type vocabulary (precise, but
    # drops facts that don't fit). Changing this needs a re-ingest to rebuild the graph.
    entity_ontology: KnowledgeGraphEntityOntology = "open"
    # Domain-generic extra instructions injected verbatim into Graphiti's node + edge extraction
    # prompts (graphiti-core's ``custom_extraction_instructions`` slot — a first-class add_episode
    # param, not a prompt hack). Defaults to a nudge for the no-edge class we keep dropping —
    # first-person preferences/goals/activities — phrased generically (true for any personal-memory
    # corpus, not LoCoMo-specific). Clear it to disable. Applied at ingest, so changing it needs a
    # re-ingest to take effect. Bounded so a runaway string can't blow the extraction token budget.
    custom_extraction_instructions: str = Field(
        default=(
            "Capture first-person preferences, goals, habits and activities as facts "
            "even when only the speaker is named; treat the activity/topic/object as "
            "the second entity."
        ),
        max_length=2000,
    )
    # Cosine *candidate* floor for the fact-search leg (maps to Graphiti
    # ``EdgeSearchConfig.sim_min_score``). A fact only becomes a search candidate if its
    # embedding similarity to the query clears this. Graphiti hardcodes 0.6 — too strict
    # for our embedder: paraphrase-distant facts (asking "wife" when the stored fact says
    # "married to") fall below it, the cosine leg returns nothing, and the graph search
    # comes back empty. Keep low for RECALL (the reranker.min_relevance below is where
    # precision belongs); raise toward 0.6 to tighten candidates. Applies to all recipes
    # (rrf/mmr/cross_encoder), since each uses cosine_similarity as a search method.
    sim_min_score: float = Field(default=0.3, ge=0.0, le=1.0)
    # Hard ceiling (seconds) on any single Kuzu query — applied to the shared writer pool AND
    # the snapshot read connections. Bounds the pathological case where a CHECKPOINT (triggered
    # by an FTS rebuild) waits minutes for a concurrent read transaction to leave — observed to
    # starve the event loop for ~2.5 min (native wait) and freeze the whole admin UI. With this
    # bound the stall dies in ~query_timeout_s and the non-fatal FTS retry absorbs the failure.
    # Sized above legit operations (per-episode writes are sub-second; a full FTS rebuild is
    # seconds at current scale) but far below Kuzu's internal wait. 0 = unlimited.
    query_timeout_s: int = Field(default=60, ge=0, le=600)
    # Graph observability tier (docs §12.2): ``off`` = no graphiti ledger/tracer/sinks;
    # ``ledger`` = one priced roll-up row per episode/search (cost folds — prod default);
    # ``trace`` = + deep per-stage JSONL sidecars. Replaces the former ``ledger_detail``
    # (compact/rich) AND the HIRO_GRAPH_TRACE_RETRIEVAL/INGEST env vars (one dial now).
    observability: GraphObservability = "ledger"
    # Cross-encoder reranker for the fact-search leg (only when search_recipe='cross_encoder').
    reranker: KnowledgeGraphRerankerPreferences = Field(
        default_factory=KnowledgeGraphRerankerPreferences
    )
    # Eval-only answering knobs (memory-eval answer prompt). Lives here so the admin UI can show an
    # "Eval" subsection under the shared Graphiti engine settings.
    eval: GraphEvalPreferences = Field(default_factory=GraphEvalPreferences)
    # Admin graph-viz DISPLAY knobs (the shared Knowledge/Memories Graph tab's per-type node
    # filter). Frontend-only — kept here because ``prefs.graph`` is the shared graph namespace.
    view: GraphViewPreferences = Field(default_factory=GraphViewPreferences)

    @property
    def embedder_model_resolved(self) -> str | None:
        return (self.embedder_model or "").strip() or None

    @model_validator(mode="after")
    def _validate_search_scope_recipe(self) -> "GraphPreferences":
        """Reject ``search_recipe='mmr'`` together with an episodes-inclusive scope.

        Rationale (verified in ``graphiti_core.search.search_config``): the episodes leg is
        ``bm25``-only and ``EpisodeReranker`` exposes ``{rrf, cross_encoder}`` — MMR is not a
        valid choice there. We surface this as a validation error (caught by the PATCH route
        and shown in the UI) rather than silently downgrading the episodes leg, so a technical
        user understands why the combo isn't allowed."""
        if self.search_scope == "edges_nodes_episodes" and self.search_recipe == "mmr":
            raise ValueError(
                "graph.search_recipe='mmr' is not supported when search_scope includes "
                "episodes (graphiti's episode leg is BM25-only and EpisodeReranker has no "
                "MMR). Choose 'rrf' or 'cross_encoder', or drop episodes from search_scope."
            )
        return self


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
    # Global tools kill-switch for the chat agent. When off, no tools are bound to the chat model on
    # any turn (the chat page's per-message "disable tools" toggle can additionally opt out a single
    # turn). Gated at runtime in call_model; default on.
    tools_enabled: bool = True
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
    # Shared Graphiti graph engine — used by BOTH knowledge retrieval and agent memory
    # (mem0 → Graphiti, Phase 3b-2). Promoted from ``knowledge.graph`` to top level so it
    # reads as shared, not owned by knowledge. Qdrant knowledge prefs stay under ``knowledge``.
    graph: GraphPreferences = Field(default_factory=GraphPreferences)
    chat: ChatPreferences = Field(default_factory=ChatPreferences)
    tuning_profiles: dict[str, TuningProfile] = Field(default_factory=default_tuning_profiles)
    image_profiles: dict[str, ImageProfile] = Field(default_factory=default_image_profiles)

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
        for graph_profile_id in (
            self.graph.extraction_tuning_profile,
            self.graph.small_tuning_profile,
            self.graph.eval.answer_tuning_profile,
            self.graph.eval.judge_tuning_profile,
            self.graph.eval.retrieval_tuning_profile,
        ):
            if graph_profile_id not in self.tuning_profiles:
                raise ValueError(
                    f"Unknown graph tuning profile: {graph_profile_id}"
                )
        return self

    @model_validator(mode="after")
    def _validate_image_profiles(self) -> "WorkspacePreferences":
        # Mirror of _validate_tuning_profiles: seeded defaults are always present + locked.
        defaults = default_image_profiles()
        for profile_id, default_profile in defaults.items():
            current = self.image_profiles.get(profile_id)
            if current is None:
                self.image_profiles[profile_id] = default_profile
            else:
                current.locked = True
                if not current.label.strip():
                    current.label = default_profile.label
        if self.llm.default_image_profile not in self.image_profiles:
            raise ValueError(
                f"Unknown llm.default_image_profile: {self.llm.default_image_profile}"
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


def _prune_default_prompts(data: dict[str, Any]) -> None:
    """Drop any editable prompt field whose value still equals its built-in default, in-place.

    Keeps a prompt left at (or restored to) default absent from preferences.json so it re-applies
    the code constant on load (a real reset that tracks future default edits). Only the known
    ``PROMPT_DEFAULTS`` paths are considered; a missing parent or non-default value is left alone."""
    for path, default_text in PROMPT_DEFAULTS.items():
        parts = path.split(".")
        node: Any = data
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                break
        else:
            leaf = parts[-1]
            if isinstance(node, dict) and node.get(leaf) == default_text:
                node.pop(leaf, None)


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

    # Prune editable prompt fields still at their built-in default so they stay ABSENT from the
    # file and re-apply the code constant on every load — a true reset that auto-tracks future
    # default edits, instead of "Restore default" persisting a pinned copy (model_dump_json would
    # otherwise materialize every field). Only PROMPT_DEFAULTS paths are touched; all else dumps full.
    data = prefs.model_dump(mode="json")
    _prune_default_prompts(data)
    preferences_file(workspace_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
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
        num_ctx=tuning.num_ctx,
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
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

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

    if credential_store is not None:
        store = credential_store
    else:
        wid = workspace_id or workspace_id_for_path(workspace_path)
        if wid is None:
            logger.debug("resolve_image_gen: workspace path not in registry — %s", workspace_path)
            return None
        store = CredentialStore(workspace_path, wid)

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
        num_ctx=tuning.num_ctx,
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
    return _resolve_knowledge_llm(
        prefs,
        workspace_path,
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
    return _resolve_knowledge_llm(
        prefs,
        workspace_path,
        tuning_profile_id=DEFAULT_KNOWLEDGE_GRAPH_DISAMBIGUATION_TUNING_PROFILE_ID,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def _resolve_graphiti_model(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    explicit_model: str | None,
    tuning_profile_id: str,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Resolve a Graphiti model tier.

    Model id chain: explicit graph override (``knowledge.graph.*_model``) →
    ``knowledge.answering.model`` → ``llm.default_chat``. Availability checks mirror
    :func:`_resolve_knowledge_llm` (catalog + provider credentials). The tuning
    profile is the per-tier graphiti profile.
    """
    from .available_models import AvailableModelsService
    from .model_catalog import get_model_catalog
    from .workspace import workspace_id_for_path

    explicit = (explicit_model or "").strip() or None
    answering = (prefs.knowledge.answering.model or "").strip() or None
    model_id = explicit or answering or prefs.llm.default_chat
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
                "_resolve_graphiti_model: workspace path not in registry — %s", workspace_path
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
        num_ctx=tuning.num_ctx,
    )


def resolve_graphiti_extraction_model(
    prefs: WorkspacePreferences,
    workspace_path: Path,
    *,
    workspace_id: str | None = None,
    credential_store: CredentialStore | None = None,
) -> ResolvedModel | None:
    """Graphiti pivot — the main extraction + edge tier (``ModelSize.medium``)."""
    return _resolve_graphiti_model(
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
    return _resolve_graphiti_model(
        prefs,
        workspace_path,
        explicit_model=explicit,
        tuning_profile_id=prefs.graph.small_tuning_profile,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_retrieval_agent_prompt(prefs: WorkspacePreferences) -> tuple[str, str]:
    """Return ``(profile_id, prompt_text)`` for the agentic retrieval loop."""
    return prefs.graph.eval.resolve_retrieval_agent_prompt()


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
    return _resolve_graphiti_model(
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
    return _resolve_graphiti_model(
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
    return _resolve_graphiti_model(
        prefs,
        workspace_path,
        explicit_model=prefs.graph.eval.retrieval_model or prefs.graph.eval.answer_model,
        tuning_profile_id=prefs.graph.eval.retrieval_tuning_profile,
        workspace_id=workspace_id,
        credential_store=credential_store,
    )


def resolve_graphiti_embedder_model(prefs: WorkspacePreferences) -> str:
    """Graphiti pivot — the embedder model id for node/fact embeddings.

    ``knowledge.graph.embedder_model`` when set, else the shared knowledge dense
    embedder (decision G8). Pure preference read — no availability check (the
    embedder is resolved by ``create_embedding_model`` at bootstrap)."""
    return (
        prefs.graph.embedder_model_resolved
        or prefs.knowledge.default_embedding_model_resolved
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
            num_ctx=tuning.num_ctx,
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
        num_ctx=tuning.num_ctx,
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
