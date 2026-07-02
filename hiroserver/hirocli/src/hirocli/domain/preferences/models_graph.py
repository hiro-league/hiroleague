"""Shared Graphiti temporal-graph engine settings (``prefs.graph``). Split out of ``models.py``.

Used by BOTH knowledge retrieval and agent memory. The ``Graph*`` literals are named without the
``Knowledge`` prefix where they're new, but the historical ``KnowledgeGraph*`` names are kept.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .defaults import (
    DEFAULT_ANSWER_PROMPT_ID,
    DEFAULT_GRAPHITI_EXTRACTION_TUNING_PROFILE_ID,
    DEFAULT_GRAPHITI_SMALL_TUNING_PROFILE_ID,
    DEFAULT_KNOWLEDGE_TUNING_PROFILE_ID,
    DEFAULT_MEMORY_EVAL_ANSWER_PROMPT,
    DEFAULT_MEMORY_EVAL_JUDGE_PROMPT,
    DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT,
    DEFAULT_RETRIEVAL_AGENT_PROMPT_ID,
    AnswerPromptProfile,
    default_answer_prompts,
    default_retrieval_agent_prompts,
    pref_field,
    reseed_locked_profiles,
)

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

    def resolve_prompt_from_library(self, requested_id: str, fallback_text: str) -> tuple[str, str]:
        """Resolve one retrieval-agent profile id → ``(id, text)`` from the shared library.

        Shared by the eval and chat resolvers (the library lives here; chat's active id lives under
        ``memory.retrieval`` and is passed in by the free ``resolve_chat_retrieval_agent_prompt``):
        a blank/unknown id falls back to the locked ``default`` profile, and blank profile text falls
        back to ``fallback_text``."""
        active = (requested_id or "").strip() or DEFAULT_RETRIEVAL_AGENT_PROMPT_ID
        profile = self.retrieval_agent_prompts.get(active) or self.retrieval_agent_prompts.get(
            DEFAULT_RETRIEVAL_AGENT_PROMPT_ID
        )
        if profile is None:
            return (DEFAULT_RETRIEVAL_AGENT_PROMPT_ID, fallback_text)
        text = (profile.prompt or "").strip() or fallback_text
        return (active, text)

    def resolve_retrieval_agent_prompt(self) -> tuple[str, str]:
        """Resolve the active (eval) retrieval-agent prompt profile → ``(id, text)``.

        Blank profile text falls back to ``DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT``."""
        return self.resolve_prompt_from_library(
            self.active_retrieval_agent_prompt_id, DEFAULT_MEMORY_EVAL_RETRIEVAL_AGENT_PROMPT
        )


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
