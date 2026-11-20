"""Shared Graphiti temporal-graph engine settings (``prefs.graph``). Split out of ``models.py``.

Used by BOTH knowledge retrieval and agent memory. The ``Graph*`` literals are named without the
``Knowledge`` prefix where they're new, but the historical ``KnowledgeGraph*`` names are kept.
"""

from __future__ import annotations

from typing import Literal

from hiro_memory.settings import KnowledgeGraphTemporalDefault
from pydantic import BaseModel, Field, model_validator

from .defaults import pref_field

KnowledgeGraphBackend = Literal["off", "graphiti"]
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
    (the admin UI greys this whole group out otherwise). ``profile`` names a reranker profile
    (``rerank.profiles``: the model, and where a local one runs), resolved by the SAME
    ``resolve_reranker`` the flat Qdrant path uses — a local model that was never downloaded
    fails fast, degrading the fact search to RRF (no silent fetch). Null = no reranker (RRF).
    """

    profile: str | None = pref_field(
        rerank_profile_ref=True,
        default=None,
        title="Reranker profile",
        description=(
            "The reranker profile that orders fact candidates. Empty = no reranker (the fact "
            "search falls back to RRF). Local models must be downloaded first."
        ),
    )
    # Drop facts whose post-rerank relevance is below this (maps to Graphiti
    # ``SearchConfig.reranker_min_score``). 0.0 = keep all. Cross-encoder only —
    # RRF/MMR scores are rank-fusion artifacts, so this is ignored for those recipes.
    min_relevance: float = pref_field(
        step=0.05,
        default=0.3,
        ge=0.0,
        le=1.0,
        title="Min relevance",
        description="Drop facts whose cross-encoder relevance is below this (0–1). 0 = keep all. Ignored by RRF/MMR.",
    )


class GraphViewPreferences(BaseModel):
    """Admin graph-VIZ display knobs for the shared Knowledge/Memories Graph tab.

    Pure frontend-display settings: they tune how the force-graph view's per-node-type
    filter dropdowns behave, NOT how facts are extracted, searched, or retrieved. The
    graph engine ignores everything here.
    """

    # A node TYPE whose instance count exceeds this shows a "many instances" perf
    # heads-up inside its per-type filter dropdown (the dropdown still lists + searches
    # every instance — this only flags very large types so the user reaches for search).
    large_type_threshold: int = pref_field(
        advanced=True,
        default=200,
        ge=10,
        le=10000,
        title="Large node-type warning threshold",
        description=(
            "In the Graph tab's per-type node filter, a type with more instances than this shows a 'many instances' "
            "performance heads-up in its dropdown. The dropdown still lists and searches every instance — this only "
            "flags very large types. Display-only."
        ),
    )


class GraphPreferences(BaseModel):
    """Graphiti-backed temporal knowledge graph (the pivot from the earlier L3 graph slice).

    ``backend`` is the master switch: ``off`` = flat Qdrant only (today); ``graphiti``
    = answer from graph facts; ``mix`` = fuse graph facts with Qdrant passages (the
    recommended path, decision G4). Every other field is an admin-settable knob — no
    hardcoded params. See docs/knowledge-graphiti-pivot-design.md §9–10.
    """

    backend: KnowledgeGraphBackend = Field(
        default="off",
        title="Graph backend",
        description=(
            "Master switch for knowledge retrieval. Off = today's flat Qdrant retrieval (graph untouched). "
            "Graphiti = answer from the graph's facts."
        ),
    )
    # Phase 7b step 5: each Graphiti model tier's model + tuning profile pair became one AI profile
    # (``jobs`` "graph_extraction" / "graph_small").
    extraction_profile: str | None = pref_field(
        ai_profile_ref=True,
        default=None,
        title="Graph extraction",
        description=(
            "The AI profile Graphiti uses to read each chunk/turn and pull out entities + facts. "
            "Must be structured-output-capable; keep it deterministic. Empty uses Hiro's chat model."
        ),
    )
    small_profile: str | None = pref_field(
        ai_profile_ref=True,
        default=None,
        title="Graph small steps",
        description=(
            "A cheaper AI profile for Graphiti's sub-steps — node dedupe, entity summaries, "
            "timestamps. Empty uses the graph extraction model."
        ),
    )
    # An embedding profile (``embedding.profiles``). Locked once the graph holds vectors: they are
    # bound to the model that made them (``io.check_embedder_transition``).
    embedder_profile: str | None = pref_field(
        embedding_profile_ref=True,
        default=None,
        title="Embedding profile",
        description=(
            "Embeds entity names and facts into the graph. Empty = the graph can't be built or "
            "searched. Locked once the graph holds data: another model needs a new graph."
        ),
    )
    # Default temporal lens at retrieval: current facts only vs include historical.
    temporal_default: KnowledgeGraphTemporalDefault = Field(
        default="all",
        title="Temporal lens (default)",
        description=(
            "Default time lens at retrieval. Current = only facts valid now (superseded facts "
            "hidden). Include historical = also surface invalidated facts. Overridable per query."
        ),
    )
    # Retrieval expansion radius (hops) when gathering related facts/chunks.
    k_hop: int = Field(
        default=2,
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
        default="typed",
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
        default=0.4,
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
