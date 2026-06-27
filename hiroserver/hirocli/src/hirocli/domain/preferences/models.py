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
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from hiro_commons.constants.storage import PREFERENCES_FILENAME

from ..credential_store import CredentialStore
from ..events import DomainEvent, DomainEventType, get_domain_event_bus
from ..prompts import load_prompt

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

    # step: float inputs in the admin UI read granularity from schema metadata (no hardcoded step).
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, json_schema_extra={"step": 0.1})
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

    default_chat: str | None = Field(default=None, json_schema_extra={"model_kind": "chat"})
    default_stt: str | None = Field(default=None, json_schema_extra={"model_kind": "stt"})
    default_tts: str | None = Field(default=None, json_schema_extra={"model_kind": "tts"})
    default_image_gen: str | None = Field(
        default=None,
        json_schema_extra={"model_kind": "chat", "preferencesSaveSkip": True},
    )
    default_tuning_profile: str = DEFAULT_CHAT_TUNING_PROFILE_ID
    default_image_profile: str = Field(
        default=DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID,
        json_schema_extra={"preferencesSaveSkip": True},
    )


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


class KnowledgeChunkingMarkdownPreferences(BaseModel):
    respect_headings: bool = Field(
        default=True,
        description="Split chunks at markdown headings when ingesting documents.",
    )


class KnowledgeChunkingPreferences(BaseModel):
    chunk_size: int = Field(
        default=1200,
        ge=200,
        le=8000,
        description="Target size per chunk at document ingest (characters).",
    )
    chunk_overlap: int = Field(
        default=150,
        ge=0,
        le=2000,
        description="Overlap between consecutive chunks. Must stay smaller than chunk size.",
    )
    embed_structural_context: bool = Field(
        default=True,
        description=(
            "Prefix each chunk's embedded text with its document title and heading path so every chunk "
            "— including continuation pieces — carries its section context. Applies to new ingests; "
            "changing this requires re-ingesting existing documents."
        ),
    )
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
    model_id: str | None = Field(default=None, json_schema_extra={"model_kind": "rerank"})
    top_n: int = Field(default=8, ge=1, le=100, description="Final returned results if using rerank (top N).")
    device: str | None = None
    batch_size: int = Field(default=32, ge=1, le=512)


class KnowledgeRetrievalPreferences(BaseModel):
    top_k: int = Field(default=20, ge=1, le=100, description="Fused results from hybrid search or direct results from dense only search (after applying minimum score).")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, json_schema_extra={"step": 0.05}, description="Applies only to dense (Vector search) branch.")
    # Hybrid retrieval: fuse the dense vector with a BM25 sparse vector via Qdrant RRF.
    # Sparse vectors are always stored at ingest, so this is a pure query-time toggle
    # (flipping it needs no re-ingest). When enabled, ``min_score`` applies as the cosine
    # threshold on the dense branch; the BM25 branch is rank-fused (its scores are not 0-1).
    hybrid: bool = True
    sparse_model: str = Field(default=DEFAULT_KNOWLEDGE_SPARSE_MODEL, min_length=1)
    # Candidates pulled per branch before fusion; should be >= top_k so RRF has overlap.
    prefetch_limit: int = Field(default=40, ge=1, le=500, description="Results to return for dense (Vector) or sparse (BM25) separately, before RRF fusion (Hybrid Only).")
    reranker: KnowledgeRerankerPreferences = Field(default_factory=KnowledgeRerankerPreferences)


class KnowledgeAnsweringPreferences(BaseModel):
    model: str | None = Field(default=None, json_schema_extra={"model_kind": "chat"})
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
#   "edges_and_episodes"    → + EpisodicNode bodies but NOT entity nodes — raw-turn BM25 recall
#                             without entity summaries. Added to test whether entity summaries are
#                             redundant with episodes (kind-dependence ablation: esum-only ≈ 0).
#   "edges_nodes_episodes"  → + EpisodicNode bodies (last-resort BM25 recall over raw turn text)
KnowledgeGraphSearchScope = Literal[
    "edges", "edges_and_nodes", "edges_and_episodes", "edges_nodes_episodes"
]
# Scopes whose search mounts the episodes (BM25) leg — single source of truth for the
# MMR×episodes incompatibility gate (graphiti's EpisodeReranker has no MMR).
KNOWLEDGE_GRAPH_EPISODE_SCOPES: tuple[KnowledgeGraphSearchScope, ...] = (
    "edges_and_episodes",
    "edges_nodes_episodes",
)
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
    model_id: str | None = Field(
        default=None,
        json_schema_extra={"model_kind": "rerank"},
        description=(
            "Cross-encoder used to rerank fact candidates. Empty = reuse the knowledge "
            "Reranker model (one model to manage). Local models must be downloaded first."
        ),
    )
    # Drop facts whose post-rerank relevance is below this (maps to Graphiti
    # ``SearchConfig.reranker_min_score``). 0.0 = keep all. Cross-encoder only —
    # RRF/MMR scores are rank-fusion artifacts, so this is ignored for those recipes.
    min_relevance: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        json_schema_extra={"step": 0.05},
        description="Drop facts whose cross-encoder relevance is below this (0–1). 0 = keep all. Ignored by RRF/MMR.",
    )
    # Local torch lane only (sentence-transformers); ignored by cloud + ONNX models.
    device: str | None = Field(
        default=None,
        description=(
            "Torch device for local sentence-transformers rerankers (e.g. cpu, cuda). "
            "Blank = auto. Ignored by cloud + ONNX models."
        ),
    )


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


class RetrievalAgentLimits(BaseModel):
    """Caps and clamp bounds for the agentic memory-retrieval loop (eval + chat parity)."""

    # Number of LLM turns the agent gets across the whole loop, INCLUDING the final-answer turn
    # (every invocation costs tokens). On the last allowed turn the model is invoked without tools
    # so it must answer. (P9 rename: was ``max_searches``; the counter advances per turn, not per
    # dispatched search call.)
    max_agent_turns: int = Field(default=4, ge=1, le=10, description="How many LLM turns the agent gets across the whole loop (includes the final-answer turn). Each search turn may emit up to max parallel searches sub-queries in one tool call.")
    # Sub-queries per single ``search_memory`` call (the decomposition fan-out). Enforced by the
    # tool against the configured value; one global value for eval and chat.
    max_parallel_searches: int = Field(default=3, ge=1, le=5, description="Sub-queries per search_memory call — global for eval and chat.")
    limit_default: int = Field(default=20, ge=1, le=100, description="Starting num_results per search_memory call.")
    limit_min: int = Field(default=10, ge=1, le=100, description="Soft floor when the tool clamps limit.")
    limit_max: int = Field(default=40, ge=1, le=100, description="Soft ceiling when the tool clamps limit.")
    hops_max: int = Field(default=3, ge=1, le=3, description="Upper bound the tool accepts per search (1–3).")

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
    large_type_threshold: int = Field(default=200, ge=10, le=10000, description="In the Graph tab's per-type node filter, a type with more instances than this shows a 'many instances' performance heads-up in its dropdown. The dropdown still lists and searches every instance — this only flags very large types. Display-only.")


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
    answer_prompts: dict[str, AnswerPromptProfile] = Field(
        default_factory=default_answer_prompts,
        json_schema_extra={"writeWhole": True},
    )
    judge_prompt: str = DEFAULT_MEMORY_EVAL_JUDGE_PROMPT
    # Answer + judge each get their OWN model + tuning profile (split from the single shared
    # answering model the eval used before). ``*_model`` of ``None`` falls back through
    # ``knowledge.answering.model`` → ``llm.default_chat`` (the prior behavior), so an unset
    # workspace is unchanged. The defaults reuse the ``knowledge_answering`` tuning profile —
    # set them apart to tune the answer step and the judge independently. The memory-eval answer
    # step uses ``answer_*``; the LLM judge (both tracks) uses ``judge_*``.
    answer_model: str | None = Field(
        default=None,
        json_schema_extra={"model_kind": "chat"},
        description=(
            "Model the memory-eval answer step uses to answer from recalled context. Null "
            "falls back to the knowledge answering model, then default chat. (Knowledge-track "
            "answers always use the production answering pipeline, not this.)"
        ),
    )
    answer_tuning_profile: str = Field(
        default=DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
        description="Tuning profile (temperature / max-tokens / thinking) for the eval answer model.",
    )
    judge_model: str | None = Field(
        default=None,
        json_schema_extra={"model_kind": "chat"},
        description=(
            "Model the LLM judge uses to grade answers against the ideal (both tracks). Null "
            "falls back to the knowledge answering model, then default chat."
        ),
    )
    judge_tuning_profile: str = Field(
        default=DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
        description="Tuning profile for the judge model. Lower temperature = more repeatable grading.",
    )
    # The agentic retrieval loop (memory track) gets its OWN model + tuning profile. ``None`` falls
    # back to the eval ANSWER model (the loop borrowed it before it had its own preference): the
    # resolver chains retrieval_model → answer_model → knowledge.answering.model → llm.default_chat,
    # so an unset workspace is unchanged. Lets the retrieval/tool-calling step use a different model
    # (e.g. a cheaper or higher-reasoning one) than the final answer step.
    retrieval_model: str | None = Field(
        default=None,
        json_schema_extra={"model_kind": "chat"},
        description=(
            "Model the agentic retrieval loop uses to plan searches and call the search_memory "
            "tool (memory track). Null falls back to the eval answer model, then the knowledge "
            "answering model → default chat."
        ),
    )
    retrieval_tuning_profile: str = Field(
        default=DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
        description="Tuning profile (temperature / max-tokens / thinking) for the retrieval-agent model.",
    )
    # Recalled-context render toggles (eval only): which temporal annotations each recalled FACT
    # line carries, and whether episodes keep their [date] prefix. ``show_event_time`` (valid_at,
    # labeled "event_time") also governs the episode [date]; ``show_expired_at`` (invalid_at) and
    # ``show_superseded`` annotate supersession. Defaults = a single timestamp per fact (Zep-style):
    # event_time on, the rest off. Applied identically to the answer, judge, and evidence-check
    # renders of a question (see eval_judge.RecallRenderOptions).
    show_event_time: bool = True
    show_expired_at: bool = False
    show_superseded: bool = False
    # Answer-context render caps (eval answerer + judge + evidence-check). The recall leg can surface
    # a large, noisy element set (100s of facts/entities/episodes) that buries the answer-relevant
    # ones; these bound what reaches the prompt. Each kind is score-ranked desc, the top
    # ``max_elements_per_kind`` kept, and every element sanitized to ONE line capped at the per-kind
    # char limit. One global set — applies identically to the answer, judge, and evidence renders.
    max_elements_per_kind: int = Field(default=30, ge=1, le=200, description="Top-N facts / entities / messages (by retrieval score) kept for the answer + judge prompts, so the answer-relevant ones aren't buried under a long dump.")
    max_fact_chars: int = Field(default=240, ge=40, le=2000, description="Each recalled fact → one sanitized line capped here.")
    max_episode_chars: int = Field(default=300, ge=40, le=2000, description="Per-episode/message text cap (one sanitized line).")
    max_summary_chars: int = Field(default=400, ge=40, le=4000, description="Per-entity summary cap (one sanitized line) — entity summaries are the longest/noisiest.")
    # Agentic retrieval loop caps/clamps (agentic-memory-retrieval-design §5.2). One global
    # value for eval and chat — do not split per surface.
    retrieval_agent: RetrievalAgentLimits = Field(default_factory=RetrievalAgentLimits)
    # Named library of retrieval-agent system prompts (mirrors answer_prompts).
    retrieval_agent_prompts: dict[str, AnswerPromptProfile] = Field(
        default_factory=default_retrieval_agent_prompts,
        json_schema_extra={"writeWhole": True},
    )
    active_retrieval_agent_prompt_id: str = Field(default=DEFAULT_RETRIEVAL_AGENT_PROMPT_ID, description="Which retrieval-agent system prompt the loop uses.")

    @model_validator(mode="after")
    def _reseed_locked_prompt_profiles(self) -> "GraphEvalPreferences":
        """Locked default prompt profiles are code-owned: re-seed them from the constants on every
        load so edits to the built-in defaults reach EXISTING workspaces (not just fresh ones),
        while user-created profiles are preserved. Without this, the persisted ``default`` profile in
        preferences.json drifts from the code constant after a default-text edit — the engine + admin
        UI would keep serving the stale text until a manual re-seed (the stale-locked-default defect)."""
        self.answer_prompts = reseed_locked_profiles(self.answer_prompts, default_answer_prompts())
        self.retrieval_agent_prompts = reseed_locked_profiles(
            self.retrieval_agent_prompts, default_retrieval_agent_prompts()
        )
        return self

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

    backend: KnowledgeGraphBackend = Field(default="off", description="Master switch for knowledge retrieval. Off = today's flat Qdrant retrieval (graph untouched). Graphiti = answer from the graph's facts.")
    # Model ids — ``None`` falls back through knowledge.answering.model → llm.default_chat.
    extraction_model: str | None = Field(
        default=None,
        json_schema_extra={"model_kind": "chat"},
        description=(
            "The heavy LLM Graphiti uses to read each chunk/turn and pull out entities + facts. "
            "Must be structured-output-capable. Null falls back to the answering model, then "
            "default chat."
        ),
    )
    extraction_tuning_profile: str = Field(
        default=DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID,
        description=(
            "Tuning profile (temperature / max-tokens / thinking) for the extraction model. "
            "Ships deterministic so extraction stays repeatable across runs."
        ),
    )
    small_model: str | None = Field(
        default=None,
        json_schema_extra={"model_kind": "chat"},
        description=(
            "Cheaper model for Graphiti's sub-steps — node dedupe, entity summaries, timestamps. "
            "Null falls back to the extraction model."
        ),
    )
    small_tuning_profile: str = Field(
        default=DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID,
        description="Tuning profile for the cheaper sub-step model (dedupe / summaries / timestamps).",
    )
    # ``None`` → shares the knowledge dense embedder (decision G8).
    embedder_model: str | None = Field(
        default=None,
        json_schema_extra={"model_kind": "embedding"},
        description=(
            "Embeds entity names + facts into the graph. Null shares the knowledge embedding "
            "model. Shared across memory + knowledge graph data — changing it re-indexes "
            "everything."
        ),
    )
    # Default temporal lens at retrieval: current facts only vs include historical.
    temporal_default: KnowledgeGraphTemporalDefault = Field(
        default="current",
        description=(
            "Default time lens at retrieval. Current = only facts valid now (superseded facts "
            "hidden). Include historical = also surface invalidated facts. Overridable per query."
        ),
    )
    # Retrieval expansion radius (hops) when gathering related facts/chunks.
    k_hop: int = Field(
        default=1,
        ge=1,
        le=3,
        description=(
            "Relationship hops out from matched entities when gathering related facts. 1 = "
            "direct neighbors only (precise); higher reaches further at more noise/cost."
        ),
    )
    # Graphiti search rerank recipe for the fact-search leg.
    search_recipe: KnowledgeGraphSearchRecipe = Field(
        default="rrf",
        description=(
            "How candidates are ranked/fused WITHIN each leg (orthogonal to Search scope below). "
            "RRF = fast reciprocal-rank fusion (default). MMR = favors diversity. Cross-encoder "
            "= highest quality, slowest/most costly. MMR is not compatible with the episodes leg "
            "(BM25-only) — disabled when scope includes episodes."
        ),
    )
    # Which graph elements the fact-search reads from (decision: extends D3). Default keeps
    # today's behavior; lift to ``edges_and_nodes`` to recall attribute memories that live on
    # ``EntityNode.summary`` (e.g. "Misho turned 50…"). ``edges_nodes_episodes`` also matches
    # raw conversation text via BM25 — useful as a last-resort recall when structured layers
    # miss; precision suffers. See :meth:`_validate_search_scope_recipe` for the MMR×episodes
    # incompatibility (graphiti-core's ``EpisodeReranker`` has no MMR).
    search_scope: KnowledgeGraphSearchScope = Field(
        default="edges",
        description=(
            "Which graph elements memory recall and knowledge retrieval READ from (orthogonal "
            "to Search recipe above). Edges = facts between entities (relations). Nodes = "
            "per-entity summaries (attribute-style memories, e.g. age, role, mood). Episodes = "
            "the raw conversation text of each saved turn — BM25 keyword match only (paraphrases "
            "may miss), useful as last-resort recall. \"Edges + Episodes\" keeps the raw turns "
            "but drops entity summaries (to test whether entity summaries are redundant with "
            "episodes)."
        ),
    )
    # Extraction ontology at ingest. "open" (default) extracts freely (broadest recall — captures
    # activities/interests/media/preferences); "typed" pins the 5-type vocabulary (precise, but
    # drops facts that don't fit). Changing this needs a re-ingest to rebuild the graph.
    entity_ontology: KnowledgeGraphEntityOntology = Field(
        default="open",
        description=(
            "Which entity types extraction may use. Open = no predefined types; the model "
            "extracts freely (everything becomes a generic Entity) — broadest recall, captures "
            "activities, interests, media, and preferences. Typed = pin the 5-type vocabulary "
            "(Person / Place / Organization / Event / Object) — more precise, but drops "
            "first-person facts that don't fit those types. Changing this rebuilds the graph at "
            "the next ingest, so a re-ingest is required to take effect."
        ),
    )
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
        description=(
            "Optional domain-generic guidance injected verbatim into Graphiti's entity + fact "
            "extraction prompts. Use it to steer what gets captured — e.g. capture first-person "
            "preferences, goals, habits and activities as facts even when only the speaker is "
            "named, treating the activity / topic / object as the second entity. Keep it generic "
            "(no dataset-specific rules). Blank = none. Applied at ingest, so a re-ingest is "
            "required to take effect."
        ),
    )
    # Cosine *candidate* floor for the fact-search leg (maps to Graphiti
    # ``EdgeSearchConfig.sim_min_score``). A fact only becomes a search candidate if its
    # embedding similarity to the query clears this. Graphiti hardcodes 0.6 — too strict
    # for our embedder: paraphrase-distant facts (asking "wife" when the stored fact says
    # "married to") fall below it, the cosine leg returns nothing, and the graph search
    # comes back empty. Keep low for RECALL (the reranker.min_relevance below is where
    # precision belongs); raise toward 0.6 to tighten candidates. Applies to all recipes
    # (rrf/mmr/cross_encoder), since each uses cosine_similarity as a search method.
    sim_min_score: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        json_schema_extra={"step": 0.05},
        description=(
            "Minimum cosine similarity (0–1) for a fact to even become a search candidate. Keep "
            "low (≈0.3) for recall — too high and paraphrased questions (e.g. asking 'wife' when "
            "the stored fact says 'married to') return no facts at all. Graphiti's own default "
            "is a strict 0.6. Precision belongs in the reranker's Min relevance below, not here."
        ),
    )
    # Hard ceiling (seconds) on any single Kuzu query — applied to the shared writer pool AND
    # the snapshot read connections. Bounds the pathological case where a CHECKPOINT (triggered
    # by an FTS rebuild) waits minutes for a concurrent read transaction to leave — observed to
    # starve the event loop for ~2.5 min (native wait) and freeze the whole admin UI. With this
    # bound the stall dies in ~query_timeout_s and the non-fatal FTS retry absorbs the failure.
    # Sized above legit operations (per-episode writes are sub-second; a full FTS rebuild is
    # seconds at current scale) but far below Kuzu's internal wait. 0 = unlimited.
    query_timeout_s: int = Field(
        default=60,
        ge=0,
        le=600,
        description=(
            "Hard ceiling on any single graph (Kuzu) query — writes, index rebuilds, and "
            "Graph-tab reads. Protects the server from a stuck index-rebuild checkpoint that can "
            "otherwise freeze the whole admin UI for minutes; a bounded failure is retried and "
            "logged instead. Keep above your slowest legitimate operation (index rebuilds take "
            "seconds). 0 = unlimited."
        ),
    )
    # Graph observability tier (docs §12.2): ``off`` = no graphiti ledger/tracer/sinks;
    # ``ledger`` = one priced roll-up row per episode/search (cost folds — prod default);
    # ``trace`` = + deep per-stage JSONL sidecars. Replaces the former ``ledger_detail``
    # (compact/rich) AND the HIRO_GRAPH_TRACE_RETRIEVAL/INGEST env vars (one dial now).
    observability: GraphObservability = Field(
        default="ledger",
        description=(
            "How much the graph engine records to Graph Runs (ingest + retrieval). Off = nothing "
            "— no ledger rows, tracer, or usage sinks (spares CPU; graph cost is NOT tracked). "
            "Ledger = one priced roll-up row per episode (ingest) and per search (rerank), so "
            "token cost still folds into the run total — the production default. Trace = Ledger "
            "plus a deep per-stage sidecar (the ⌗ retrieval/ingest trace dialogs) for debugging. "
            "Replaces the old Rich/Compact detail and the trace env vars."
        ),
    )
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
        # Any episodes-inclusive scope (edges_and_episodes, edges_nodes_episodes) mounts the
        # BM25-only episodes leg, which has no MMR reranker — reject the combo for all of them.
        if self.search_scope in KNOWLEDGE_GRAPH_EPISODE_SCOPES and self.search_recipe == "mmr":
            raise ValueError(
                "graph.search_recipe='mmr' is not supported when search_scope includes "
                "episodes (graphiti's episode leg is BM25-only and EpisodeReranker has no "
                "MMR). Choose 'rrf' or 'cross_encoder', or drop episodes from search_scope."
            )
        return self


class KnowledgePreferences(BaseModel):
    default_embedding_model: str | None = Field(
        default=None,
        description="Null uses the local multilingual FastEmbed default shown above.",
        json_schema_extra={"model_kind": "embedding"},
    )
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
DEFAULT_CHAT_INSTRUCTIONS = load_prompt("chat_instructions")

# Registered here (not in the PROMPT_DEFAULTS literal above) because the constant is defined only
# now. Exposes the built-in chat instructions to the admin prompt-editor "Restore default" button
# and lets a value equal to the default prune from preferences.json like the other prompt defaults.
PROMPT_DEFAULTS["chat.instructions"] = DEFAULT_CHAT_INSTRUCTIONS


class ChatPreferences(BaseModel):
    """Chat-answering behavior (the chat model answers; not the Ask knowledge answerer)."""

    # General answering instructions (Markdown), injected into the current user turn. Editable in
    # the Admin → Preferences → Agent tab. Broader than knowledge — may carry any answering guidance.
    instructions: str = DEFAULT_CHAT_INSTRUCTIONS
    # Conversation-history window kept per turn by trim_history (short-term context). Feeds the chat
    # answer + memory/knowledge retrieval — a chat-answering concern, not a long-term memory one.
    max_messages: int = Field(default=DEFAULT_MAX_HISTORY_MESSAGES, ge=1, le=100, description="Conversation history window kept per turn (short-term context for the reply + memory/knowledge retrieval).")
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

    version: int = Field(default=3, json_schema_extra={"readOnly": True})
    llm: LLMPreferences = Field(default_factory=LLMPreferences)
    media: MediaPreferences = Field(default_factory=MediaPreferences)
    memory: MemoryPreferences = Field(default_factory=MemoryPreferences)
    knowledge: KnowledgePreferences = Field(default_factory=KnowledgePreferences)
    # Shared Graphiti graph engine — used by BOTH knowledge retrieval and agent memory
    # (mem0 → Graphiti, Phase 3b-2). Promoted from ``knowledge.graph`` to top level so it
    # reads as shared, not owned by knowledge. Qdrant knowledge prefs stay under ``knowledge``.
    graph: GraphPreferences = Field(default_factory=GraphPreferences)
    chat: ChatPreferences = Field(default_factory=ChatPreferences)
    tuning_profiles: dict[str, TuningProfile] = Field(
        default_factory=default_tuning_profiles,
        json_schema_extra={"writeWhole": True},
    )
    image_profiles: dict[str, ImageProfile] = Field(
        default_factory=default_image_profiles,
        json_schema_extra={"preferencesSaveSkip": True},
    )

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

