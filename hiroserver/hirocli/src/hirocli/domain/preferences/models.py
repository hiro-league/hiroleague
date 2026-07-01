"""Workspace preferences — single source of truth for configurable choices.

``preferences.json`` holds LLM default selections (canonical catalog ids), profile-based
tuning, voice/audio, and memory settings. Provider secrets live in the credential
store (``providers.json`` + OS keyring), not here.

Storage: ``<workspace>/preferences.json`` — Pydantic model serialised to JSON.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .defaults import (
    DEFAULT_ANSWER_PROMPT_ID,
    DEFAULT_CHAT_INSTRUCTIONS,
    DEFAULT_CHAT_TUNING_PROFILE_ID,
    DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID,
    DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID,
    DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID,
    DEFAULT_KNOWLEDGE_ANSWERING_PROMPT,
    DEFAULT_KNOWLEDGE_REWRITE_PROMPT,
    DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
    DEFAULT_MEMORY_EVAL_ANSWER_PROMPT,
    DEFAULT_MEMORY_EVAL_JUDGE_PROMPT,
    DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT,
    DEFAULT_MEMORY_TUNING_PROFILE_ID,
    DEFAULT_RETRIEVAL_AGENT_PROMPT_ID,
    AnswerPromptProfile,
    ImageProfile,
    TuningProfile,
    default_answer_prompts,
    default_image_profiles,
    default_retrieval_agent_prompts,
    default_tuning_profiles,
    iter_tuning_profile_refs,
    pref_field,
    reseed_locked_profiles,
    seed_default_profiles,
)

logger = logging.getLogger(__name__)


class LLMPreferences(BaseModel):
    """Which catalog models to use when the workspace has credentials for them."""

    default_chat: str | None = pref_field(
        model_kind="chat", default=None, title="Default chat model"
    )
    default_stt: str | None = pref_field(
        model_kind="stt", default=None, title="Default speech-to-text model"
    )
    default_tts: str | None = pref_field(
        model_kind="tts", default=None, title="Default text-to-speech model"
    )
    # Workspace-wide default cross-encoder reranker. Both the knowledge retrieval reranker
    # (knowledge.retrieval.reranker.model_id) and the graph fact-search reranker
    # (graph.reranker.model_id) fall back to this when their own model is empty — one place
    # to manage the reranker for both legs. Null = no default (each leg reranks only if it
    # sets its own model).
    default_reranker: str | None = pref_field(
        model_kind="rerank",
        default=None,
        title="Default reranker model",
        description=(
            "Default cross-encoder reranker. The knowledge and graph rerankers both fall "
            "back to this when their own model is empty. Empty = no default. Cloud models "
            "need a provider key; local models must be downloaded first."
        ),
    )
    # Workspace-wide default embedder. The knowledge embedder (knowledge.default_embedding_model)
    # and the graph embedder (graph.embedder_model) both fall back to this when their own model is
    # empty. NOT forced to any model: null = no default, and indexing is blocked until an embedder
    # is chosen (embedding is mandatory + dimension-bound, so there is no silent fallback). Never
    # locked — it only seeds consumers that have not indexed yet.
    default_embedder: str | None = pref_field(
        model_kind="embedding",
        default=None,
        title="Default embedder model",
        description=(
            "Default embedder. The knowledge and graph embedders both fall back to this when "
            "their own model is empty. Empty = no default (indexing is blocked until one is "
            "chosen). Cloud models need a provider key; local models must be downloaded first."
        ),
    )
    default_image_gen: str | None = pref_field(
        model_kind="chat",
        save_skip=True,
        default=None,
    )
    default_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_CHAT_TUNING_PROFILE_ID,
        title="Default chat model profile",
    )
    default_image_profile: str = pref_field(
        save_skip=True,
        default=DEFAULT_IMAGE_PLAYGROUND_PROFILE_ID,
    )


# ---------------------------------------------------------------------------
# Media policy / capabilities
# ---------------------------------------------------------------------------


class ModalityFlags(BaseModel):
    voice: bool = Field(default=False, title="Voice")
    image: bool = Field(default=False, title="Image")
    video: bool = Field(default=False, title="Video")
    file: bool = Field(default=False, title="File")


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
    enabled: bool = Field(default=True, title="Recall memories before each reply")
    top_k: int = Field(
        default=DEFAULT_MEMORY_SEARCH_TOP_K, ge=1, le=100, title="Memories to recall (top K)"
    )


class MemoryExtractionPreferences(BaseModel):
    """Whether the agent stores new long-term memories after a reply (memory_out)."""

    # When false, ``_store_turn_memory`` is skipped — memory becomes read-only (it stops growing)
    # while search may still inject existing memories. No-op unless ``memory.enabled``.
    enabled: bool = Field(default=True, title="Remember new facts after each reply")


class MemoryPreferences(BaseModel):
    """Agent memory settings — a thin feature layer over the shared Graphiti graph engine.

    Gated purely by ``enabled``; the engine (extraction model, embedder, search) comes from
    the top-level ``graph`` preferences, and ``create_memory_service`` degrades to ``None``
    when that engine can't be built. The mem0-legacy model / embedder / reranker fields are
    gone (mem0 → Graphiti, Phase 5)."""

    enabled: bool = Field(default=False, title="Enable agent memory")
    default_tuning_profile: str = pref_field(
        tuning_profile_ref=True, default=DEFAULT_MEMORY_TUNING_PROFILE_ID
    )
    # A1 fix: the human's name, used as the Graphiti *speaker label* when ingesting the user's
    # turns. Graphiti extracts the speaker (the token before the ":") as the anchor entity, so a
    # real name produces a clean `Misho` Person hub instead of a generic `User` node, and every
    # fact the user states attaches to it. Empty ⇒ falls back to "User" (prior behavior).
    # IMPORTANT: keep this STABLE. Graphiti never auto-renames nodes, so changing it mid-history
    # forks a SECOND hub and fragments the user's memory — set it once, early.
    user_name: str = Field(default="", max_length=120, title="Your name")
    search: MemorySearchPreferences = Field(default_factory=MemorySearchPreferences)
    extraction: MemoryExtractionPreferences = Field(default_factory=MemoryExtractionPreferences)


# ---------------------------------------------------------------------------
# Workspace-local knowledge
# ---------------------------------------------------------------------------

DEFAULT_KNOWLEDGE_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class KnowledgeChunkingMarkdownPreferences(BaseModel):
    respect_headings: bool = Field(
        default=True,
        title="Respect markdown headings",
        description="Split chunks at markdown headings when ingesting documents.",
    )


class KnowledgeChunkingPreferences(BaseModel):
    chunk_size: int = Field(
        default=1200,
        ge=200,
        le=8000,
        title="Chunk size",
        description="Target size per chunk at document ingest (characters).",
    )
    chunk_overlap: int = Field(
        default=150,
        ge=0,
        le=2000,
        title="Chunk overlap",
        description="Overlap between consecutive chunks. Must stay smaller than chunk size.",
    )
    embed_structural_context: bool = pref_field(
        # Demo seed for the admin "show advanced" toggle: a low-level ingest knob most users
        # never touch. Remove/adjust `advanced` here (and on any other field) to taste.
        advanced=True,
        default=True,
        title="Embed structural context",
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
    torch lane only and are ignored by cloud models. ``model_id`` null = fall back to the
    workspace default reranker (``llm.default_reranker``); if that is empty too, no reranker
    (retrieval order used as-is) even when ``enabled`` is true.
    """

    enabled: bool = Field(default=False, title="Enable reranking")
    model_id: str | None = pref_field(
        model_kind="rerank",
        default=None,
        title="Reranker model",
        description=(
            "Cross-encoder used to reorder retrieved candidates. Empty = fall back to the "
            "default reranker (General → Models). Local models must be downloaded first."
        ),
    )
    top_n: int = Field(default=8, ge=1, le=100, title="Rerank results (top N)", description="Final returned results if using rerank (top N).")
    device: str | None = None
    batch_size: int = Field(default=32, ge=1, le=512)


class KnowledgeRetrievalPreferences(BaseModel):
    top_k: int = Field(default=20, ge=1, le=100, title="Search/fused results (top K)", description="Fused results from hybrid search or direct results from dense only search (after applying minimum score).")
    min_score: float = pref_field(step=0.05, default=0.0, ge=0.0, le=1.0, title="Minimum score (Dense only)", description="Applies only to dense (Vector search) branch.")
    # Hybrid retrieval: fuse the dense vector with a BM25 sparse vector via Qdrant RRF.
    # Sparse vectors are always stored at ingest, so this is a pure query-time toggle
    # (flipping it needs no re-ingest). When enabled, ``min_score`` applies as the cosine
    # threshold on the dense branch; the BM25 branch is rank-fused (its scores are not 0-1).
    hybrid: bool = Field(default=True, title="Hybrid retrieval (dense + BM25, RRF fusion)")
    # The BM25 sparse model is a fixed constant (services.knowledge.constants.DEFAULT_SPARSE_MODEL),
    # not a preference: the Qdrant collection is hardwired to BM25's IDF scoring and switching would
    # need a full re-ingest, so it was removed from the editable preference surface.
    # Candidates pulled per branch before fusion; should be >= top_k so RRF has overlap.
    prefetch_limit: int = Field(default=40, ge=1, le=500, title="Candidates per branch", description="Results to return for dense (Vector) or sparse (BM25) separately, before RRF fusion (Hybrid Only).")
    reranker: KnowledgeRerankerPreferences = Field(default_factory=KnowledgeRerankerPreferences)


class KnowledgeAnsweringPreferences(BaseModel):
    model: str | None = pref_field(
        model_kind="chat", default=None, title="Knowledge answering model"
    )
    # Base answer-generation system prompt. Editable; blank falls back to the relaxed default
    # (partial answers allowed, no bare "I don't know" when any part is supported). The citation
    # and language clauses are appended at runtime from the fields below.
    prompt: str = Field(default=DEFAULT_KNOWLEDGE_ANSWERING_PROMPT, title="Answering prompt")
    cite_sources: bool = Field(default=True, title="Cite sources")
    language_policy: Literal["match_query", "prefer_english", "prefer_arabic"] = Field(
        default="match_query", title="Language policy"
    )


class KnowledgeRewritePreferences(BaseModel):
    # Optional LLM query rewrite for the Ask tab: normalize + extract literal keywords before
    # retrieval. Reuses the resolved answering model. ``default_on`` seeds the Ask-tab toggle.
    prompt: str = Field(default=DEFAULT_KNOWLEDGE_REWRITE_PROMPT, title="Query Rewrite Prompt")
    default_on: bool = Field(default=False, title="Enable Query Rewrite on Ask Tab")


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
    (no silent fetch). ``model_id`` null = fall back to the workspace default reranker
    (``llm.default_reranker``) — one model to manage for both legs.
    """

    # null → fall back to the workspace default reranker model id (llm.default_reranker).
    model_id: str | None = pref_field(
        model_kind="rerank",
        default=None,
        title="Reranker model",
        description=(
            "Cross-encoder used to rerank fact candidates. Empty = fall back to the default "
            "reranker (General → Models). Local models must be downloaded first."
        ),
    )
    # Drop facts whose post-rerank relevance is below this (maps to Graphiti
    # ``SearchConfig.reranker_min_score``). 0.0 = keep all. Cross-encoder only —
    # RRF/MMR scores are rank-fusion artifacts, so this is ignored for those recipes.
    min_relevance: float = pref_field(
        step=0.05,
        default=0.0,
        ge=0.0,
        le=1.0,
        title="Min relevance",
        description="Drop facts whose cross-encoder relevance is below this (0–1). 0 = keep all. Ignored by RRF/MMR.",
    )
    # Local torch lane only (sentence-transformers); ignored by cloud + ONNX models.
    device: str | None = pref_field(
        advanced=True,
        default=None,
        title="Device (local only)",
        description=(
            "Torch device for local sentence-transformers rerankers (e.g. cpu, cuda). "
            "Blank = auto. Ignored by cloud + ONNX models."
        ),
    )


class RetrievalAgentLimits(BaseModel):
    """Caps and clamp bounds for the agentic memory-retrieval loop (eval + chat parity)."""

    # Number of LLM turns the agent gets across the whole loop, INCLUDING the final-answer turn
    # (every invocation costs tokens). On the last allowed turn the model is invoked without tools
    # so it must answer. (P9 rename: was ``max_searches``; the counter advances per turn, not per
    # dispatched search call.)
    max_agent_turns: int = Field(default=4, ge=1, le=10, title="Max agent turns", description="How many LLM turns the agent gets across the whole loop (includes the final-answer turn). Each search turn may emit up to max parallel searches sub-queries in one tool call.")
    # Sub-queries per single ``search_memory`` call (the decomposition fan-out). Enforced by the
    # tool against the configured value; one global value for eval and chat.
    max_parallel_searches: int = Field(default=3, ge=1, le=5, title="Max parallel searches", description="Sub-queries per search_memory call — global for eval and chat.")
    limit_default: int = Field(default=20, ge=1, le=100, title="Limit default", description="Starting num_results per search_memory call.")
    limit_min: int = Field(default=10, ge=1, le=100, title="Limit min", description="Soft floor when the tool clamps limit.")
    limit_max: int = Field(default=40, ge=1, le=100, title="Limit max", description="Soft ceiling when the tool clamps limit.")
    hops_max: int = Field(default=3, ge=1, le=3, title="Hops max", description="Upper bound the tool accepts per search (1–3).")

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
    large_type_threshold: int = pref_field(advanced=True, default=200, ge=10, le=10000, title="Large node-type warning threshold", description="In the Graph tab's per-type node filter, a type with more instances than this shows a 'many instances' performance heads-up in its dropdown. The dropdown still lists and searches every instance — this only flags very large types. Display-only.")


class GraphEvalPreferences(BaseModel):
    """Eval-only answering knobs, surfaced under the shared Graphiti engine settings.

    ``answer_prompts`` is a named LIBRARY of answering INSTRUCTION blocks for the memory-eval
    recall leg (``eval_judge.answer_from_context`` places the active one in the user message ahead
    of the question and the recalled elements; the system prompt there is a hardcoded two-line
    role). The active profile is the persisted ``active_answer_prompt_id`` (mirrors the retrieval
    agent's ``active_retrieval_agent_prompt_id``) — see ``resolve_active_answer_prompt``.
    The knowledge-eval legs intentionally have no answer-prompt library:
    they run the real ``KnowledgeAgentGraph`` and so are graded against the PRODUCTION
    ``knowledge.answering.prompt`` (forking it would make the knowledge eval stop measuring real
    behavior). The admin UI surfaces that production prompt alongside this one for convenience.

    ``judge_prompt`` is the grading system prompt for the LLM judge (``eval_judge.judge_answer``),
    shared by both tracks. Editable/visible for reference; blank falls back to the relaxed default.
    """

    # Named library of mem-eval answer-prompt recipes (replaces the former single
    # ``memory_answer_prompt`` scalar — no-backward-compat, no migration). The answer step uses the
    # ``active_answer_prompt_id`` profile (a persisted preference, mirroring the retrieval agent —
    # the former per-run eval-panel picker is gone); ``resolve_answer_prompt`` maps id → instruction
    # text with a default fallback. The ``default`` profile is locked and carries the built-in text.
    answer_prompts: dict[str, AnswerPromptProfile] = pref_field(
        write_whole=True,
        default_factory=default_answer_prompts,
        title="Mem Eval Answer Prompts",
    )
    active_answer_prompt_id: str = Field(default=DEFAULT_ANSWER_PROMPT_ID, title="Active prompt profile", description="Which mem-eval answer prompt the answer step uses.")
    judge_prompt: str = Field(default=DEFAULT_MEMORY_EVAL_JUDGE_PROMPT, title="Eval judge prompt")
    # Answer + judge each get their OWN model + tuning profile (split from the single shared
    # answering model the eval used before). ``*_model`` of ``None`` falls back through
    # ``knowledge.answering.model`` → ``llm.default_chat`` (the prior behavior), so an unset
    # workspace is unchanged. The defaults reuse the ``knowledge_answering`` tuning profile —
    # set them apart to tune the answer step and the judge independently. The memory-eval answer
    # step uses ``answer_*``; the LLM judge (both tracks) uses ``judge_*``.
    answer_model: str | None = pref_field(
        model_kind="chat",
        default=None,
        title="Eval answer model",
        description=(
            "Model the memory-eval answer step uses to answer from recalled context. Null "
            "falls back to the knowledge answering model, then default chat. (Knowledge-track "
            "answers always use the production answering pipeline, not this.)"
        ),
    )
    answer_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
        title="Eval answer profile",
        description="Tuning profile (temperature / max-tokens / thinking) for the eval answer model.",
    )
    judge_model: str | None = pref_field(
        model_kind="chat",
        default=None,
        title="Eval judge model",
        description=(
            "Model the LLM judge uses to grade answers against the ideal (both tracks). Null "
            "falls back to the knowledge answering model, then default chat."
        ),
    )
    judge_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
        title="Eval judge profile",
        description="Tuning profile for the judge model. Lower temperature = more repeatable grading.",
    )
    # The agentic retrieval loop (memory track) gets its OWN model + tuning profile. ``None`` falls
    # back to the eval ANSWER model (the loop borrowed it before it had its own preference): the
    # resolver chains retrieval_model → answer_model → knowledge.answering.model → llm.default_chat,
    # so an unset workspace is unchanged. Lets the retrieval/tool-calling step use a different model
    # (e.g. a cheaper or higher-reasoning one) than the final answer step.
    retrieval_model: str | None = pref_field(
        model_kind="chat",
        default=None,
        title="Retrieval agent model",
        description=(
            "Model the agentic retrieval loop uses to plan searches and call the search_memory "
            "tool (memory track). Null falls back to the eval answer model, then the knowledge "
            "answering model → default chat."
        ),
    )
    retrieval_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
        title="Retrieval agent profile",
        description="Tuning profile (temperature / max-tokens / thinking) for the retrieval-agent model.",
    )
    # Recalled-context render toggles (eval only): which temporal annotations each recalled FACT
    # line carries, and whether episodes keep their [date] prefix. ``show_event_time`` (valid_at,
    # labeled "event_time") also governs the episode [date]; ``show_expired_at`` (invalid_at) and
    # ``show_superseded`` annotate supersession. Defaults = a single timestamp per fact (Zep-style):
    # event_time on, the rest off. Applied identically to the answer, judge, and evidence-check
    # renders of a question (see eval_judge.RecallRenderOptions).
    show_event_time: bool = Field(default=True, title="Show event_time (valid date)")
    show_expired_at: bool = Field(default=False, title="Show expired_at (invalid date)")
    show_superseded: bool = Field(default=False, title="Show SUPERSEDED flag")
    # Answer-context render caps (eval answerer + judge + evidence-check). The recall leg can surface
    # a large, noisy element set (100s of facts/entities/episodes) that buries the answer-relevant
    # ones; these bound what reaches the prompt. Each kind is score-ranked desc, the top
    # ``max_elements_per_kind`` kept, and every element sanitized to ONE line capped at the per-kind
    # char limit. One global set — applies identically to the answer, judge, and evidence renders.
    max_elements_per_kind: int = pref_field(advanced=True, default=30, ge=1, le=200, title="Max elements / kind", description="Top-N facts / entities / messages (by retrieval score) kept for the answer + judge prompts, so the answer-relevant ones aren't buried under a long dump.")
    max_fact_chars: int = pref_field(advanced=True, default=240, ge=40, le=2000, title="Max fact chars", description="Each recalled fact → one sanitized line capped here.")
    max_episode_chars: int = pref_field(advanced=True, default=300, ge=40, le=2000, title="Max message chars", description="Per-episode/message text cap (one sanitized line).")
    max_summary_chars: int = pref_field(advanced=True, default=400, ge=40, le=4000, title="Max entity summary chars", description="Per-entity summary cap (one sanitized line) — entity summaries are the longest/noisiest.")
    # Agentic retrieval loop caps/clamps (agentic-memory-retrieval-design §5.2). One global
    # value for eval and chat — do not split per surface.
    retrieval_agent: RetrievalAgentLimits = Field(default_factory=RetrievalAgentLimits)
    # Named library of retrieval-agent system prompts (mirrors answer_prompts).
    retrieval_agent_prompts: dict[str, AnswerPromptProfile] = pref_field(
        write_whole=True,
        default_factory=default_retrieval_agent_prompts,
        title="Retrieval Agent Prompt",
    )
    active_retrieval_agent_prompt_id: str = Field(default=DEFAULT_RETRIEVAL_AGENT_PROMPT_ID, title="Active prompt profile", description="Which retrieval-agent system prompt the loop uses.")

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
        built-in constant when even that is missing or its text is blank. The runner reaches this
        via ``resolve_active_answer_prompt`` (the active id) for the instruction block + label."""
        pid = (profile_id or "").strip()
        profile = self.answer_prompts.get(pid) or self.answer_prompts.get(DEFAULT_ANSWER_PROMPT_ID)
        if profile is None:
            return (DEFAULT_ANSWER_PROMPT_ID, DEFAULT_MEMORY_EVAL_ANSWER_PROMPT)
        text = (profile.prompt or "").strip() or DEFAULT_MEMORY_EVAL_ANSWER_PROMPT
        return (profile.label or pid or DEFAULT_ANSWER_PROMPT_ID, text)

    def resolve_active_answer_prompt(self) -> tuple[str, str, str]:
        """Resolve the active mem-eval answer prompt → ``(id, label, instruction_text)``.

        Mirrors ``resolve_retrieval_agent_prompt`` (the answer step now uses the persisted
        ``active_answer_prompt_id`` instead of a per-run eval-panel pick). Blank/unknown id falls
        back to the locked ``default`` profile, then to the built-in constant."""
        active = (self.active_answer_prompt_id or "").strip() or DEFAULT_ANSWER_PROMPT_ID
        label, text = self.resolve_answer_prompt(active)
        return (active, label, text)

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

    backend: KnowledgeGraphBackend = Field(default="off", title="Graph backend", description="Master switch for knowledge retrieval. Off = today's flat Qdrant retrieval (graph untouched). Graphiti = answer from the graph's facts.")
    # Model ids — ``None`` falls back through knowledge.answering.model → llm.default_chat.
    extraction_model: str | None = pref_field(
        model_kind="chat",
        default=None,
        title="Extraction model",
        description=(
            "The heavy LLM Graphiti uses to read each chunk/turn and pull out entities + facts. "
            "Must be structured-output-capable. Null falls back to the answering model, then "
            "default chat."
        ),
    )
    extraction_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID,
        title="Extraction profile",
        description=(
            "Tuning profile (temperature / max-tokens / thinking) for the extraction model. "
            "Ships deterministic so extraction stays repeatable across runs."
        ),
    )
    small_model: str | None = pref_field(
        model_kind="chat",
        default=None,
        title="Smaller extraction model",
        description=(
            "Cheaper model for Graphiti's sub-steps — node dedupe, entity summaries, timestamps. "
            "Null falls back to the extraction model."
        ),
    )
    small_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID,
        title="Smaller extraction profile",
        description="Tuning profile for the cheaper sub-step model (dedupe / summaries / timestamps).",
    )
    # ``None`` → shares the knowledge dense embedder (decision G8).
    embedder_model: str | None = pref_field(
        model_kind="embedding",
        default=None,
        title="Embedder model",
        description=(
            "Embeds entity names + facts into the graph. Null shares the knowledge embedding "
            "model. Shared across memory + knowledge graph data — changing it re-indexes "
            "everything."
        ),
    )
    # Default temporal lens at retrieval: current facts only vs include historical.
    temporal_default: KnowledgeGraphTemporalDefault = Field(
        default="current",
        title="Temporal lens (default)",
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
        title="Expansion hops (k)",
        description=(
            "Relationship hops out from matched entities when gathering related facts. 1 = "
            "direct neighbors only (precise); higher reaches further at more noise/cost."
        ),
    )
    # Graphiti search rerank recipe for the fact-search leg.
    search_recipe: KnowledgeGraphSearchRecipe = Field(
        default="rrf",
        title="Search recipe",
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
        title="Search scope",
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
    entity_ontology: KnowledgeGraphEntityOntology = pref_field(
        advanced=True,
        default="open",
        title="Extraction ontology",
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
    custom_extraction_instructions: str = pref_field(
        advanced=True,
        default=(
            "Capture first-person preferences, goals, habits and activities as facts "
            "even when only the speaker is named; treat the activity/topic/object as "
            "the second entity."
        ),
        max_length=2000,
        title="Extraction instructions",
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
    sim_min_score: float = pref_field(
        step=0.05,
        default=0.3,
        ge=0.0,
        le=1.0,
        title="Candidate similarity floor",
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
    query_timeout_s: int = pref_field(
        advanced=True,
        default=60,
        ge=0,
        le=600,
        title="Query timeout (seconds)",
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
        title="Graph observability",
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
    # Knowledge embedder OVERRIDE. Empty = inherit the workspace default (llm.default_embedder),
    # resolved by ``resolve_knowledge_embedder_model``. Locked (UI badge + pre-save write-guard)
    # once the knowledge collection has points — embedders are dimension-bound, so changing this
    # after indexing would orphan the stored vectors. Field name kept (historical) to preserve the
    # existing lock + value for already-indexed workspaces without a migration.
    default_embedding_model: str | None = pref_field(
        model_kind="embedding",
        default=None,
        title="Knowledge embedder",
        description="Knowledge embedder. Empty inherits the workspace default (General → Models).",
    )
    default_tuning_profile: str = pref_field(
        tuning_profile_ref=True,
        default=DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
        title="Knowledge answering model profile",
    )
    chunking: KnowledgeChunkingPreferences = Field(default_factory=KnowledgeChunkingPreferences)
    retrieval: KnowledgeRetrievalPreferences = Field(default_factory=KnowledgeRetrievalPreferences)
    answering: KnowledgeAnsweringPreferences = Field(default_factory=KnowledgeAnsweringPreferences)
    rewrite: KnowledgeRewritePreferences = Field(default_factory=KnowledgeRewritePreferences)


class ChatPreferences(BaseModel):
    """Chat-answering behavior (the chat model answers; not the Ask knowledge answerer)."""

    # General answering instructions (Markdown), injected into the current user turn. Editable in
    # the Admin → Preferences → Agent tab. Broader than knowledge — may carry any answering guidance.
    instructions: str = Field(default=DEFAULT_CHAT_INSTRUCTIONS, title="Chat instructions")
    # Conversation-history window kept per turn by trim_history (short-term context). Feeds the chat
    # answer + memory/knowledge retrieval — a chat-answering concern, not a long-term memory one.
    max_messages: int = Field(default=DEFAULT_MAX_HISTORY_MESSAGES, ge=1, le=100, title="Max retained messages", description="Conversation history window kept per turn (short-term context for the reply + memory/knowledge retrieval).")
    # When on, chat instructs the model to cite knowledge inline as [n] AND surfaces the source list
    # to the client (citation bridge on graph.reply.completed). Moved here from knowledge.chat.
    cite_sources: bool = Field(default=False, title="Cite knowledge sources in chat replies")
    # Global tools kill-switch for the chat agent. When off, no tools are bound to the chat model on
    # any turn (the chat page's per-message "disable tools" toggle can additionally opt out a single
    # turn). Gated at runtime in call_model; default on.
    tools_enabled: bool = Field(default=True, title="Enable agent tools in chat")
    # Placeholder until a real per-character/per-chat language setting exists; chat retrieval does
    # not constrain answer language today (the persona decides). Kept so it can be threaded later.
    preferred_answering_language: str = "en"


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

