"""GraphitiMemoryService — bootstrap + lifecycle for the Graphiti temporal graph.

Mirrors how the prior mem0 service sits behind a single service boundary: nothing
outside this module imports ``graphiti_core`` directly, so the brain stays
rip-out-able (decision G3/G8, docs/knowledge-graphiti-pivot-design.md §4).

Bootstrap wires:

  Graphiti(
      graph_driver = KuzuDriver(workspace/db/graphiti_kuzu.db),
      llm_client   = GraphitiLLMClient(model_factory + tuning profiles + ledger),
      embedder     = GraphitiEmbedderClient(shared knowledge embedder),
      cross_encoder= RRF passthrough (avoids Graphiti's default OpenAI reranker),
  )

Ingest (``add_episode``) and search land in later phases; this module owns
construction, ``build_indices_and_constraints``, and teardown only.
"""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

import kuzu
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.errors import NodeNotFoundError
from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF
from graphiti_core.utils.maintenance import node_operations as _graphiti_node_ops
from hiro_commons.constants.storage import DB_DIR
from hiro_commons.log import Logger

from hirocli.domain.preferences import (
    ModelTuning,
    ResolvedModel,
    WorkspacePreferences,
    resolve_graph_reranker_model,
    resolve_graphiti_embedder_model,
    resolve_graphiti_extraction_model,
    resolve_graphiti_small_model,
)
from hirocli.services.knowledge.constants import KUZU_DB_FILENAME

from . import kuzu_registry
from .graphiti_adapters import (
    GraphitiEmbedderClient,
    GraphitiLLMClient,
    GraphitiModelSpec,
    HiroRerankerCrossEncoder,
    UsageSink,
)
from .graphiti_ingest import (
    GraphEventSink,
    GraphitiEpisodeInput,
    GraphitiIngestStats,
    ingest_episodes,
    rebuild_fts_indices,
)
from .graphiti_ontology import GRAPHITI_ENTITY_TYPES
from .group_scope import (
    KNOWLEDGE_GROUP_ID,
    is_memory_group_id,
    validate_group_id,
)
from .graphiti_search import GraphitiExpansion
from .graphiti_search import search_chunk_ids as _search_chunk_ids
from .ingest_ledger import record_episode_embed, record_episode_llm_usage
from .ledger_tracer import LedgerTracer, record_rerank_usage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.llm_client.client import LLMClient

    from hirocli.domain.credential_store import CredentialStore
    from hirocli.runtime.agent_graph.ledger import LedgerSink

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI")


# Reranker ``top_n`` for the cross-encoder: rank ALL candidate facts Graphiti hands it
# (the final cut is Graphiti's ``SearchConfig.limit``). Generous so we never pre-trim.
_RERANK_CANDIDATE_CAP = 512

# Page size for the scope-based episode wipe (remove_episodes_by_document). Paged via
# uuid_cursor so an arbitrarily large prior run is fully swept — never tail-truncated.
_EPISODE_WIPE_PAGE = 500

# Dedicated read-connection pool size for the Graph-tab snapshot (docs
# kuzu-shared-database-design.md §8, option b — "1 writer + N readers"). The snapshot
# reads through its OWN AsyncConnection on the shared kuzu.Database so it never queues
# behind the writer's pinned pool=1 connection during a build. Read-only ⇒ a larger pool
# is safe (concurrent reads never open a write txn); only the WRITER driver must stay at 1
# (§4.4). 4 matches kuzu's AsyncConnection default.
_SNAPSHOT_READ_POOL = 4


def _apply_dedup_min_score(score: float) -> None:
    """Align graphiti's INTERNAL ingest-dedup similarity floor with our embedder-tuned
    ``sim_min_score`` (single source of truth — no separate user pref).

    graphiti's ``add_episode`` finds duplicate / to-be-invalidated EDGES via
    ``search(config=EDGE_HYBRID_SEARCH_RRF)`` and duplicate NODES via
    ``node_similarity_search(..., NODE_DEDUP_COSINE_MIN_SCORE)``. Both default to graphiti's
    ``DEFAULT_MIN_SCORE = 0.6`` — calibrated for graphiti's reference embedder and too strict
    for ours (paraphrase-distant facts score < 0.6), so existing edges/nodes are not retrieved
    as dedup candidates → duplicate facts + missed temporal supersession. We lower both to the
    configured floor so dedup is recall-biased (an LLM verifies precision afterward).

    Our SEARCH path is unaffected: ``_build_search_config`` deep-copies the recipe and sets
    ``sim_min_score`` explicitly, so mutating the shared recipe object only reaches the dedup
    path (which reads it directly). Defensive ``hasattr`` so a future graphiti rename degrades
    visibly (warning) instead of silently writing a dead attribute."""
    score = max(0.0, min(1.0, float(score)))
    if EDGE_HYBRID_SEARCH_RRF.edge_config is not None:
        EDGE_HYBRID_SEARCH_RRF.edge_config.sim_min_score = score
    if hasattr(_graphiti_node_ops, "NODE_DEDUP_COSINE_MIN_SCORE"):
        _graphiti_node_ops.NODE_DEDUP_COSINE_MIN_SCORE = score
    else:
        log.warning(
            "⚠️ graphiti — NODE_DEDUP_COSINE_MIN_SCORE missing (graphiti drift?); "
            "node dedup floor left at graphiti default"
        )
    log.info("✅ graphiti — ingest-dedup sim_min_score aligned · score=%.3f", score)


def _registry_key(db_path: Path) -> str:
    """Stable process-wide key for the shared Kuzu driver of one workspace graph.

    Both the ingest service and the snapshot reader derive the key from the SAME
    absolute path so they share one ``Database`` via ``kuzu_registry`` (resolve() so
    differing relative/symlinked spellings of the same file map to one entry)."""
    return str(Path(db_path).resolve())


def _apply_query_timeout(client: Any, timeout_s: int) -> None:
    """Set Kuzu's per-query timeout on an ``AsyncConnection`` (``graph.query_timeout_s`` pref).

    Why: a Kuzu CHECKPOINT (e.g. triggered by ``CREATE_FTS_INDEX``) waits for every active
    transaction to leave — and that native wait was observed to hold the GIL, starving the
    event loop (and thus the whole admin UI) for ~2.5 minutes before Kuzu's own internal
    timeout fired. A query-level ceiling turns that into a bounded, catchable failure that the
    non-fatal FTS-rebuild retry absorbs. ``timeout_s <= 0`` = unlimited (skip). Best-effort:
    a failure to set the timeout must never block opening the graph."""
    if client is None or timeout_s <= 0:
        return
    try:
        client.set_query_timeout(int(timeout_s) * 1000)
    except Exception:
        log.warning(
            "⚠️ graphiti — failed to set Kuzu query timeout · timeout_s=%s", timeout_s,
            exc_info=True,
        )


def _close_kuzu_driver(driver: Any) -> None:
    """Registry closer — explicitly close the underlying kuzu Connection + Database to
    release the file lock NOW.

    Graphiti's ``KuzuDriver.close()`` is a no-op (it relies on GC), which keeps the
    Kuzu single-opener file lock held — blocking any subsequent open of the same DB.
    Closing the connection then the database releases the lock deterministically. Called
    by ``kuzu_registry.release`` only when the LAST consumer of the shared driver lets go
    (refcount → 0), so a snapshot read never tears down a driver the eval build still
    holds."""
    if driver is None:
        return
    for attr in ("client", "db"):
        obj = getattr(driver, attr, None)
        close = getattr(obj, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                log.warning("⚠️ graphiti — kuzu %s close failed", attr, exc_info=True)


def is_kuzu_lock_error(exc: BaseException) -> bool:
    """True when ``exc`` is Kuzu's "another process holds the file" lock error.

    With the shared registry, in-process opens can no longer collide; this only fires
    for an EXTERNAL process holding the lock (a second ``hiro``, a stale handle). The
    Graph route uses it to return a clean "DB busy" message instead of a raw stack."""
    return "could not set lock on file" in str(exc).lower()


class _RankByInputOrderCrossEncoder(CrossEncoderClient):
    """No-op reranker — returns passages in input order with descending scores.

    Graphiti defaults ``cross_encoder`` to ``OpenAIRerankerClient`` (forces an
    OpenAI key + network). Our default search recipe is RRF, which never calls the
    cross-encoder, so this passthrough keeps construction provider-free. A real
    cross-encoder (wrapping the knowledge reranker) can be injected in Phase 3 when
    the ``cross_encoder`` search recipe is exposed as an admin preference."""

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        n = len(passages)
        return [(p, float(n - i)) for i, p in enumerate(passages)]


def _spec(resolved: ResolvedModel) -> GraphitiModelSpec:
    """ResolvedModel (id + profile params) → adapter spec."""
    return GraphitiModelSpec(
        model_id=resolved.model_id,
        tuning=ModelTuning(
            temperature=resolved.temperature,
            max_tokens=resolved.max_tokens,
            thinking=resolved.thinking,
            num_ctx=resolved.num_ctx,
        ),
    )


def graphiti_db_path(workspace_path: Path) -> Path:
    """Per-workspace Kuzu DB file for the Graphiti graph (consolidated db/ folder)."""
    return workspace_path / DB_DIR / KUZU_DB_FILENAME


# Graphiti tags every entity with this base label in addition to its ontology type
# (mirrors graphiti_serialize._BASE_LABEL) — the first non-base label IS the entity type.
_BASE_ENTITY_LABEL = "Entity"


def _node_entity_type(node: Any) -> str:
    """First non-base ontology label is the entity's type (e.g. ``Person``); else ``Entity``."""
    for label in getattr(node, "labels", None) or []:
        if label and label != _BASE_ENTITY_LABEL:
            return str(label)
    return _BASE_ENTITY_LABEL


def _edge_to_memory(edge: Any) -> dict[str, Any]:
    """One Graphiti fact edge → a plain memory dict (facts-as-memory, decision D3).

    Reduces an ``EntityEdge`` to a render-ready dict so the conversation-memory facade can
    list facts WITHOUT importing graphiti_core (the brain stays inside this module, decision
    G3/G8). ``id`` is the edge uuid (the deletable unit); ``chunk_ids`` are the supporting
    episode uuids (== message ids).

    Structure fields make the admin Memories table read as a *graph* rather than prose:
    ``relation`` is the predicate (``PARENT_OF``); ``source_id``/``target_id`` are the
    endpoint entity uuids (their names are joined in :meth:`list_facts`, which already has the
    nodes in hand). Temporal fields expose the bi-temporal model: ``created_at`` (``valid_at``
    — became true), ``invalid_at`` (stopped being true), ``expired_at`` (when the system
    learned it was superseded)."""
    valid_at = getattr(edge, "valid_at", None)
    invalid_at = getattr(edge, "invalid_at", None)
    expired_at = getattr(edge, "expired_at", None)
    episodes = [str(ep) for ep in (getattr(edge, "episodes", None) or []) if ep]
    return {
        "kind": "relation",
        "memory": getattr(edge, "fact", "") or "",
        "relation": getattr(edge, "name", "") or "",
        "source_id": getattr(edge, "source_node_uuid", "") or "",
        "target_id": getattr(edge, "target_node_uuid", "") or "",
        "created_at": valid_at.isoformat() if isinstance(valid_at, dt.datetime) else None,
        "invalid_at": invalid_at.isoformat() if isinstance(invalid_at, dt.datetime) else None,
        "expired_at": expired_at.isoformat() if isinstance(expired_at, dt.datetime) else None,
        "id": getattr(edge, "uuid", "") or "",
        # The partition the fact lives in — the conversation facade parses the
        # ``(user, character)`` out of it to attribute the row in the admin view.
        "group_id": getattr(edge, "group_id", "") or "",
        "chunk_ids": episodes,
    }


def _node_to_memory(node: Any) -> dict[str, Any]:
    """One Graphiti entity node → a plain memory dict (attribute-style memory / entity).

    Graphiti stores two complementary memory shapes: relational facts on ``EntityEdge``
    (already surfaced by :func:`_edge_to_memory`) and per-entity attribute summaries on
    ``EntityNode.summary`` (e.g. "Misho turned 50 years old in June 2026"). Decision D3
    originally counted only edges, but that hides attribute facts — the user sees them
    on the Graph panel yet not in the Memories tab. We now emit them as ``kind="summary"``
    rows alongside relation rows so the tab honestly reflects what's remembered.

    reason (memories admin redesign): entities WITHOUT a summary are no longer dropped —
    they're emitted as ``kind="entity"`` rows (empty ``memory``, identified by name/type)
    so the Memories list shows every entity, including the endpoint entities that
    otherwise appeared only as names in a relation's Entities column. A ``summarize_entities``
    pass fills the summary later, flipping the row to ``kind="summary"``.

    ``chunk_ids`` are NOT carried for entity rows: a node summary is the *accumulated*
    state across every episode that mentioned the entity (so its provenance isn't a
    single chunk like a relation has — the chunk-detail panel correctly hides for these).
    """
    summary = (getattr(node, "summary", "") or "").strip()
    created_at = getattr(node, "created_at", None)
    return {
        # A summarized entity is an attribute memory; a bare one is just the entity.
        "kind": "summary" if summary else "entity",
        "memory": summary,
        # The entity this summary is *about* + its ontology type — lets the admin table show
        # "Misho (Person)" beside the prose so a summary reads as a graph node, not a sentence.
        "entity_name": getattr(node, "name", "") or "",
        "entity_type": _node_entity_type(node),
        "created_at": created_at.isoformat() if isinstance(created_at, dt.datetime) else None,
        "invalid_at": None,
        "expired_at": None,
        "id": getattr(node, "uuid", "") or "",
        "group_id": getattr(node, "group_id", "") or "",
        # Empty by design — see docstring. The Graph viz still resolves provenance via
        # the entity's own chunk_ids on the node itself.
        "chunk_ids": [],
    }


def _distinct_group_ids(rows: Any) -> list[str]:
    """Flatten a Kuzu ``execute_query`` result into a deduped list of ``group_id`` values.

    ``execute_query`` returns ``list[dict]`` (single statement) or ``list[list[dict]]``
    (multi) — flatten both. Order-preserving + deduped so the caller gets a stable group
    list."""
    out: list[str] = []
    seen: set[str] = set()
    flat: list[Any] = []
    for row in rows or []:
        if isinstance(row, list):
            flat.extend(row)
        else:
            flat.append(row)
    for row in flat:
        gid = row.get("group_id") if isinstance(row, dict) else None
        if gid and gid not in seen:
            seen.add(gid)
            out.append(str(gid))
    return out


class GraphitiMemoryService:
    """Owns the Graphiti client + its embedded Kuzu driver for one workspace.

    Construct with explicit clients (testable with stubs + a real temp Kuzu DB), or
    via :meth:`from_preferences` which resolves model tiers + the shared embedder
    from workspace preferences. Call :meth:`initialize` once (async — it builds the
    graph indices) before ingest/search, and :meth:`close` on teardown.
    """

    def __init__(
        self,
        *,
        db_path: Path,
        llm_client: "LLMClient",
        embedder: "EmbedderClient",
        cross_encoder: CrossEncoderClient | None = None,
        group_id: str | None = None,
        max_coroutines: int | None = None,
        observability: str = "ledger",
        search_recipe: str = "rrf",
        search_scope: str = "edges",
        k_hop: int = 1,
        reranker_min_score: float = 0.0,
        sim_min_score: float = 0.3,
        query_timeout_s: int = 60,
        entity_ontology: str = "open",
        custom_extraction_instructions: str = "",
    ) -> None:
        # Observability tier (off / ledger / trace) — the single dial that gates the ledger
        # roll-up rows, the tracer, the usage sinks, and the deep trace sidecars (docs §12.2).
        self._observability = observability
        # Retrieval knobs (admin prefs) threaded into every search_chunk_ids call.
        self._search_recipe = search_recipe
        # Which legs the search reads from (edges / +nodes / +nodes+episodes). Orthogonal
        # to ``search_recipe``: each leg ranks with its own variant of the chosen recipe.
        # Validated against ``search_recipe`` upstream in ``GraphPreferences`` so we never
        # see the invalid mmr×episodes combo here.
        self._search_scope = search_scope
        self._k_hop = k_hop
        # Ingest-time extraction ontology: "typed" pins GRAPHITI_ENTITY_TYPES, "open" passes
        # entity_types=None so Graphiti extracts freely (broader recall — see graphiti_ontology).
        self._entity_ontology = entity_ontology
        # Extra extraction-prompt guidance (graphiti's custom_extraction_instructions slot), threaded
        # into every add_episode. Empty ⇒ graphiti renders the slot as "" (a no-op).
        self._custom_extraction_instructions = custom_extraction_instructions
        self._reranker_min_score = reranker_min_score
        # Cosine candidate floor (graphiti's EdgeSearchConfig.sim_min_score). See
        # graphiti_search._build_search_config — lowering this fixes empty fact searches.
        self._sim_min_score = sim_min_score
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._registry_key = _registry_key(self._db_path)
        log.info("⬇️ graphiti — opening Kuzu graph · path=%s", self._db_path)
        try:
            # Shared, refcounted driver: ONE kuzu.Database per workspace for ALL consumers
            # (ingest / search / snapshot), so they never open a 2nd Database on the same
            # file → no "Could not set lock on file". Pinned to max_concurrent_queries=1 —
            # graphiti's default and its write-safety guarantee; bumping it would let
            # graphiti's internal writes self-collide with Kuzu's single-writer rule
            # (docs/kuzu-shared-database-design.md §3/§4.4).
            driver = kuzu_registry.acquire(
                self._registry_key,
                lambda: KuzuDriver(str(self._db_path), max_concurrent_queries=1),
            )
        except Exception:
            log.exception("❌ graphiti — failed to open Kuzu driver · path=%s", self._db_path)
            raise
        # Bound every query on the shared writer pool (graph.query_timeout_s pref). This is the
        # floor under the checkpoint-freeze: a CHECKPOINT stuck behind a concurrent reader dies
        # in ~timeout seconds instead of starving the event loop for Kuzu's multi-minute internal
        # wait. Re-applied on every service build (idempotent; the driver is shared/refcounted).
        self._query_timeout_s = query_timeout_s
        _apply_query_timeout(getattr(driver, "client", None), query_timeout_s)
        self._graphiti = Graphiti(
            graph_driver=driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder or _RankByInputOrderCrossEncoder(),
            max_coroutines=max_coroutines,
        )
        # Inject our Graph-Runs tracer (docs §12.2). graphiti's ``create_tracer``
        # only accepts an OpenTelemetry tracer (it would discard a custom ``Tracer``),
        # so we override post-construction on all three holders: the orchestrator
        # (``add_episode`` span), the search clients bundle (``search.*`` spans), and
        # the LLM client (``llm.generate``). The tracer no-ops unless a consumer has
        # set ``current_spans`` (graph_expand / ledger_episode), so this is safe for
        # every other graphiti caller.
        # Skip tracer wiring entirely at ``off`` — no spans buffered, no per-call hook overhead.
        # At ``ledger``/``trace`` the tracer is needed for the ``add_episode`` rollup span
        # (``edge.invalidated_count``, invisible to the response model).
        if self._observability != "off":
            try:
                tracer = LedgerTracer()
                self._graphiti.tracer = tracer
                self._graphiti.clients.tracer = tracer
                self._graphiti.llm_client.set_tracer(tracer)
            except Exception:
                # Observability must never break the graph itself.
                log.warning("⚠️ graphiti — ledger tracer injection failed", exc_info=True)
        # Resolve ONE concrete group_id shared by ingest / search / snapshot
        # (snapshot's get_by_group_ids needs a concrete list). Knowledge uses the NAMED
        # ``kb_main`` partition — NOT graphiti's empty default (which on Kuzu is ""), because
        # an empty group is falsy → reads fell through to "all groups" and leaked conversation
        # memory into knowledge search (docs/graph-group-policy-design.md §2). A caller may
        # still pass an explicit named group (a kb space, an eval set).
        self._group_id = group_id or KNOWLEDGE_GROUP_ID
        # graphiti-core 0.29.1's KuzuDriver never initializes `_database` (the base
        # GraphDriver only declares the annotation, no default). add_episode() with an
        # explicit group_id does `group_id != self.driver._database`, which raises
        # AttributeError on Kuzu. Seed it with our group_id so the comparison is False
        # → graphiti skips the Neo4j-only "clone to a per-group database" switch and
        # reuses the single embedded Kuzu file (one DB per workspace, group_id is just
        # a partition tag inside it). Fixes: add_episode AttributeError on ingest.
        driver._database = self._group_id
        self._initialized = False
        self._closed = False

    @property
    def graphiti(self) -> Graphiti:
        """The underlying client — ingest/search live on this in later phases."""
        return self._graphiti

    @property
    def group_id(self) -> str | None:
        return self._group_id

    async def initialize(self) -> None:
        """Build graph indices/constraints. Idempotent; safe to await once per service."""
        if self._initialized:
            return
        try:
            await self._graphiti.build_indices_and_constraints()
            # No-op for Kuzu (above) → we must (re)build the FTS indices ourselves, else
            # the first add_episode's edge dedup search crashes (graphiti-core gap). We
            # REBUILD (drop+create) rather than create-if-missing so that any rows already
            # in the DB get (re)indexed on restart — Kuzu's FTS snapshot is otherwise frozen
            # at first-create time, leaving pre-existing facts invisible to keyword search.
            # The unit-test fake graphiti has no real `.driver` → skip (no Kuzu there).
            driver = getattr(self._graphiti, "driver", None)
            if driver is not None:
                await rebuild_fts_indices(driver)
            # Match graphiti's internal ingest-dedup cosine floor to our configured
            # `sim_min_score` so duplicate facts/nodes are actually retrieved as dedup
            # candidates (graphiti's 0.6 default is too strict for our embedder).
            _apply_dedup_min_score(self._sim_min_score)
        except Exception:
            log.exception("❌ graphiti — build_indices_and_constraints failed")
            raise
        self._initialized = True
        log.info("✅ graphiti — graph ready · path=%s", self._db_path)

    @property
    def workspace_path(self) -> Path:
        """Workspace root derived from the Kuzu DB location (``<workspace>/db/graphiti_kuzu.db``).

        Exposed so callers that hold only the service (e.g. memory recall) can persist
        per-workspace artifacts — like the retrieval-trace sidecar — without threading
        ``workspace_path`` through every API."""
        # ``Path(...)`` so a caller that injected a plain string db_path (unit stubs that
        # bypass ``__init__``) doesn't crash on ``.parent`` — production always holds a Path.
        # Two levels up: db/graphiti_kuzu.db → db/ → <workspace> (consolidated db/ layout).
        return Path(self._db_path).parent.parent

    @property
    def observability(self) -> str:
        """Graph observability tier (``off``/``ledger``/``trace``) from the shared graph prefs.

        Exposed so the conversation-memory recall path gates its trace sidecar + rerank roll-up
        the same way ingest does (which reads ``self._observability`` directly)."""
        return self._observability

    async def ingest_chunks(
        self,
        episodes: "Sequence[GraphitiEpisodeInput]",
        *,
        source_role: str,
        group_id: str | None = None,
        event_sink: GraphEventSink | None = None,
        ledger_sink: "LedgerSink | None" = None,
        trace_label: str | None = None,
        extra_extraction_instructions: str | None = None,
        rebuild_fts: bool = True,
    ) -> GraphitiIngestStats:
        """Ingest document chunks as Graphiti episodes (F7 write-gated, sequential).

        Auto-initializes the graph on first use. Uses the pinned entity ontology;
        edge-type vocabulary is left free-form for now (see graphiti_ontology).

        ``group_id`` selects the graph partition to write into; ``None`` ⇒ this
        service's default group (knowledge, ``kb_main``). Conversation memory passes a
        per-``(user, character)`` group so its facts dedup/supersede in isolation
        (decision D1); eval passes an ``eval_{set}`` group. The per-episode
        ``driver._database`` re-point in ``ingest_episodes`` makes multi-group writes
        safe on Kuzu.

        The resolved group is validated against the firm partition policy (write
        boundary, docs/graph-group-policy-design.md §6) — an empty or non-namespaced
        group raises, so a write can never land in graphiti's empty catch-all.

        ``ledger_sink`` records a ``graph_ingest`` run (one priced roll-up row per episode)
        in Graph Runs; ``None`` = no ledger (tests/CLI). At ``observability=off`` the sink is
        dropped here so no episode rows are written at all."""
        await self.initialize()
        # Mint-or-default, then validate: bans the empty/unknown group that leaked
        # conversation memory into knowledge search (docs §2).
        target_group = validate_group_id(group_id or self._group_id)
        # ``off`` → no episode ledger rows regardless of what the caller handed in.
        effective_sink = ledger_sink if self._observability != "off" else None
        # Per-call extraction clause (conversation-memory windowing) APPENDED after the shared
        # workspace nudge — lets a caller add scope guidance (e.g. "attribute facts to the user
        # only" for a two-speaker window) without mutating the workspace-wide
        # ``graph.custom_extraction_instructions``. None/"" ⇒ just the shared nudge (no change).
        extra = (extra_extraction_instructions or "").strip()
        base = self._custom_extraction_instructions
        effective_instructions = f"{base}\n\n{extra}".strip() if extra else base
        return await ingest_episodes(
            self._graphiti,
            episodes,
            source_role=source_role,
            group_id=target_group,
            # "open" → no ontology (Graphiti extracts freely); "typed" → pinned 5-type vocabulary.
            entity_types=(GRAPHITI_ENTITY_TYPES if self._entity_ontology == "typed" else None),
            # Shared workspace nudge + optional per-call clause (computed above); "" ⇒ no-op.
            custom_extraction_instructions=effective_instructions,
            event_sink=event_sink,
            ledger_sink=effective_sink,
            observability=self._observability,
            # LangSmith span name for this ingest unit (e.g. ``graph_ingest_3`` from the
            # memory-eval remember loop); ``None`` ⇒ ingest_episodes' default ``graph_ingest``.
            trace_name=trace_label or "graph_ingest",
            # Where the per-stage ingest-trace sidecar is written (only when observability=trace
            # and a ledger sink is active).
            workspace_path=self.workspace_path,
            # Per-workspace write lock: serialize every writer (this ingest, a concurrent
            # eval/graph build, future chat-memory) to one add_episode at a time. Required
            # by Kuzu (single-writer) AND graphiti (sequential dedup). Held per-episode and
            # released between episodes (docs §4.2), so a waiting reader/writer isn't
            # blocked for the whole batch.
            write_lock=kuzu_registry.write_lock(self._registry_key),
            # Callers looping single-episode ingests (memory remember batch) pass False to defer
            # the per-episode Kuzu FTS checkpoint and call ``rebuild_search_index`` once at the end.
            rebuild_fts=rebuild_fts,
        )

    async def rebuild_search_index(self, *, attempts: int = 2, backoff_s: float = 1.0) -> None:
        """Rebuild the Kuzu FTS index ONCE (drop+create) under the write lock.

        For callers that ingested with ``rebuild_fts=False`` (deferred per-episode rebuild): run
        this after the batch so keyword (bm25) search + graphiti dedup see the new rows. Collapses
        a per-episode checkpoint storm into a single checkpoint. No-op on non-Kuzu backends.

        ``CREATE_FTS_INDEX`` triggers a Kuzu CHECKPOINT, which fails if any concurrent READ
        transaction is still open (e.g. the Graph-tab live export). We retry a BOUNDED number of
        times so a transient reader has a chance to clear — deliberately small (not aggressive)
        because the checkpoint wait can itself be long, and re-attempting many times would only
        extend a stall. Raises once every attempt fails; the caller decides whether that's fatal
        (the eval treats it as non-fatal — rows are already committed and ``initialize()`` rebuilds
        the FTS index on the next graph open)."""
        await self.initialize()
        driver = getattr(self._graphiti, "driver", None)
        if driver is None:
            return
        last_exc: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                async with kuzu_registry.write_lock(self._registry_key):
                    await rebuild_fts_indices(driver)
                return
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "⚠️ graphiti — FTS rebuild attempt %d/%d failed · path=%s",
                    attempt,
                    attempts,
                    self._db_path,
                    exc_info=True,
                )
                if attempt < attempts:
                    await asyncio.sleep(backoff_s * attempt)
        if last_exc is not None:
            raise last_exc

    async def remove_episodes(self, uuids: list[str]) -> int:
        """Delete the given episodes and the nodes/edges they EXCLUSIVELY own.

        Added for the eval reset path so a rerun can wipe only what a prior eval
        created — without touching other knowledge. graphiti's ``remove_episode``
        deletes only edges the episode created (``edge.episodes[0] == uuid``) and
        nodes mentioned by no other episode (``episode_count == 1``), so shared /
        real-data nodes survive; removing the whole eval set then cleans up every
        eval-exclusive node once its last reference drops. Missing ids (first run,
        or a partial prior run) are skipped — not an error. Serialized under the
        per-workspace Kuzu write lock (single-writer), like ingest.
        """
        await self.initialize()
        lock = kuzu_registry.write_lock(self._registry_key)
        removed = 0
        for episode_uuid in uuids:
            async with lock:
                try:
                    await self._graphiti.remove_episode(episode_uuid)
                except NodeNotFoundError:
                    continue  # nothing to delete for this id — skip
                except Exception:
                    log.exception("❌ graphiti — remove_episode failed · uuid=%s", episode_uuid)
                    raise
            removed += 1
        log.info("🧹 graphiti — removed eval episodes · count=%d/%d", removed, len(uuids))
        return removed

    async def remove_episodes_by_document(self, document_id: str) -> int:
        """Delete every episode in this graph that belongs to ``document_id`` — and
        the nodes/edges those episodes exclusively own.

        Scope-based counterpart to the per-uuid :meth:`remove_episodes`. A wipe must
        clear ALL of a document's episodes regardless of what the corpus file
        currently lists: a previous run may have ingested MORE episodes, and a
        truncated/renamed file must never strand them in the graph. (Bug fix: the eval
        reset used to derive the delete set from the current file's ids, so it could
        only ever remove what the file still named — leaving prior-run episodes
        behind.) Episodes carry their document_id in ``source_description`` at ingest,
        so we enumerate the in-graph set by that field, never from the file. Other
        knowledge (a different ``source_description``) is never matched. Idempotent:
        a missing document removes 0.
        """
        await self.initialize()
        uuids = await self._episode_uuids_in_group(
            self._group_id,
            match=lambda ep: (getattr(ep, "source_description", "") or "") == document_id,
        )
        if not uuids:
            log.info("🧹 graphiti — no episodes to remove · document_id=%s", document_id)
            return 0
        log.info(
            "🧹 graphiti — removing document episodes · document_id=%s count=%d",
            document_id,
            len(uuids),
        )
        return await self.remove_episodes(uuids)

    async def _episode_uuids_in_group(
        self, group_id: str, *, match: "Callable[[Any], bool] | None" = None
    ) -> list[str]:
        """Page through ``group_id``'s episodes (uuid_cursor) → their uuids, optionally
        filtered by ``match(ep)``.

        Shared by the per-document wipe (filter by ``source_description``) and the
        whole-group memory clear (no filter, memory Phase 2). Pages via uuid_cursor —
        ``get_by_group_ids`` orders by uuid DESC — so a large group can't leave a tail
        behind the page limit. Returns ``[]`` when the client has no driver (test fakes)
        or the group has no episodes."""
        from graphiti_core.errors import GroupsNodesNotFoundError
        from graphiti_core.nodes import EpisodicNode

        driver = getattr(self._graphiti, "driver", None)
        if driver is None:
            return []
        uuids: list[str] = []
        cursor: str | None = None
        while True:
            try:
                batch = await EpisodicNode.get_by_group_ids(
                    driver, [group_id], limit=_EPISODE_WIPE_PAGE, uuid_cursor=cursor
                )
            except GroupsNodesNotFoundError:
                break  # empty graph / no episodes in this group — nothing to collect
            if not batch:
                break
            for ep in batch:
                if match is None or match(ep):
                    uid = getattr(ep, "uuid", "") or ""
                    if uid:
                        uuids.append(uid)
            if len(batch) < _EPISODE_WIPE_PAGE:
                break
            cursor = getattr(batch[-1], "uuid", None)
            if not cursor:
                break
        return uuids

    async def clear_group(self, group_id: str) -> int:
        """Delete the WHOLE ``group_id`` partition via graphiti's group-scoped Kuzu clear.

        Conversation-memory wipe (memory Phase 2, decision D1): clearing a per-
        ``(user, character)`` memory group removes all of that pairing's remembered turns and
        the facts/entities derived from them. Groups are isolated partitions, so this drops the
        whole partition cleanly. Returns the episode count removed (counted up front, since the
        underlying op returns ``None``); the clear runs under the per-workspace write lock.

        Delegates to ``driver.graph_ops.clear_data(driver, group_ids=[group_id])`` —
        graphiti-core's Kuzu maintenance op, which DETACH DELETEs ``RelatesToNode_`` (Kuzu
        reifies edges as nodes) **plus** ``Entity`` / ``Episodic`` / ``Community`` scoped to the
        group. This replaces a hand-rolled wipe (per-episode ``remove_episode`` + an
        Entity-only ``DETACH DELETE``) that left orphan ``RelatesToNode_`` fact nodes behind:
        ``remove_episode`` only deletes what one episode exclusively owns, and deleting an
        ``Entity`` removes its relationships but NOT the reified fact *node* between two
        entities — so fact nodes orphaned across re-runs survived every clear and could
        resurface in recall.

        Why the DRIVER op and not the top-level ``graph_data_operations.clear_data`` helper:
        that helper only group-scopes when ``driver.graph_operations_interface`` is set, which
        the Kuzu driver leaves ``None`` — so it would fall through to a whole-DB
        ``MATCH (n) DETACH DELETE n`` and wipe EVERY group (incl. real conversation memory).
        The driver op is the group-safe path.
        """
        await self.initialize()
        driver = getattr(self._graphiti, "driver", None)
        if driver is None:
            return 0  # test fakes without a driver — nothing to clear
        count = len(await self._episode_uuids_in_group(group_id))
        lock = kuzu_registry.write_lock(self._registry_key)
        async with lock:
            try:
                # Group-scoped: deletes RelatesToNode_ + Entity + Episodic + Community for THIS
                # group only (graphiti_core kuzu graph_ops.clear_data) — no orphan fact nodes left.
                await driver.graph_ops.clear_data(driver, group_ids=[group_id])
            except Exception:
                # Real Kuzu writes — fail loud + let the caller surface it (general-coding-rule).
                log.exception("❌ graphiti — group clear failed · group=%s", group_id)
                raise
        log.info("🧹 graphiti — cleared group · group=%s episodes=%d", group_id, count)
        return count

    async def list_facts(
        self, group_ids: list[str], *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Read the remembered facts in ``group_ids`` → plain memory dicts.

        Two memory shapes are merged (decision D3 extended):
          - **relational facts** on ``EntityEdge`` (``kind="relation"``) — e.g.
            "Misho's first child is Mark"
          - **attribute summaries** on ``EntityNode.summary`` (``kind="summary"``) —
            e.g. "Misho turned 50 years old in June 2026" — for facts that don't fit
            a two-entity triple. Before this fix the tab missed every attribute memory
            even though the graph panel showed it on the node.

        Read-only on a dedicated connection (lock-free; safe during an active build),
        like the snapshot. Returns ``[]`` when the DB file doesn't exist or both reads
        find nothing. Maps via :func:`_edge_to_memory`/:func:`_node_to_memory` so
        graphiti types never leave this module."""
        from graphiti_core.edges import EntityEdge
        from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError
        from graphiti_core.nodes import EntityNode

        if not group_ids or not self._db_path.exists():
            return []
        async with _snapshot_read_driver(self._db_path, purpose="list_facts") as read_driver:
            try:
                edges = await EntityEdge.get_by_group_ids(read_driver, group_ids, limit=limit)
            except GroupsEdgesNotFoundError:
                edges = []
            except Exception:
                log.warning(
                    "⚠️ graphiti — list_facts (edges) failed · groups=%s",
                    group_ids,
                    exc_info=True,
                )
                raise
            try:
                nodes = await EntityNode.get_by_group_ids(read_driver, group_ids, limit=limit)
            except GroupsNodesNotFoundError:
                nodes = []
            except Exception:
                log.warning(
                    "⚠️ graphiti — list_facts (node summaries) failed · groups=%s",
                    group_ids,
                    exc_info=True,
                )
                raise
        # Resolve relation endpoints to entity names. The nodes are already loaded for the
        # summary rows below, so this join is free (no extra read) — it turns each relation
        # row into "Source —[REL]→ Target" instead of two opaque uuids.
        name_by_uuid = {
            (getattr(n, "uuid", "") or ""): (getattr(n, "name", "") or "") for n in (nodes or [])
        }
        rows: list[dict[str, Any]] = []
        for edge in edges or []:
            row = _edge_to_memory(edge)
            row["source_name"] = name_by_uuid.get(row["source_id"], "")
            row["target_name"] = name_by_uuid.get(row["target_id"], "")
            rows.append(row)
        # Every entity node becomes a row now (summarized → kind="summary", bare →
        # kind="entity"); _node_to_memory no longer returns None.
        for node in nodes or []:
            rows.append(_node_to_memory(node))
        return rows

    async def list_group_ids(self, prefix: str) -> list[str]:
        """Distinct ``group_id``s whose name starts with ``prefix`` (read-only).

        Enables the conversation facade's cross-character reads (decision L2.6): all of a
        user's memory groups = ``list_group_ids("mem_{user}_")``, then read/clear each.
        Naming-agnostic — this module knows nothing of the ``mem_`` convention; it just
        runs a DISTINCT-with-prefix over the ``Episodic`` node table. Returns ``[]`` when
        the DB file doesn't exist."""
        # reason: delegate to the module-level helper so the DISTINCT-by-prefix query lives
        # in one place (the corpus-listing route reuses it without a constructed service).
        return list(await distinct_group_ids_with_prefix(self._db_path, prefix))

    async def delete_facts(self, uuids: list[str]) -> int:
        """Delete specific fact edges (memories) by uuid → count requested.

        The conversation facade's ``forget`` (facts-as-memory: a "memory" is an
        ``EntityEdge``, decision D3). Serialized under the per-workspace write lock
        (single-writer). Missing ids are a no-op; empty input returns 0."""
        from graphiti_core.edges import EntityEdge

        ids = [str(u) for u in uuids if u]
        if not ids:
            return 0
        await self.initialize()
        lock = kuzu_registry.write_lock(self._registry_key)
        async with lock:
            try:
                await EntityEdge.delete_by_uuids(self._graphiti.driver, ids)
            except Exception:
                log.exception("❌ graphiti — delete_facts failed · count=%d", len(ids))
                raise
        log.info("🧹 graphiti — deleted memory facts · count=%d", len(ids))
        return len(ids)

    async def search_chunk_ids(
        self,
        query: str,
        *,
        group_id: str | None = None,
        num_results: int = 20,
        temporal: str = "current",
        k_hop: int | None = None,
        show_expiry: bool = False,
    ) -> GraphitiExpansion:
        """Graphiti fact search → focused Qdrant chunk_ids (+ fact texts).

        ``group_id`` selects the graph partition to search; ``None`` ⇒ this service's
        default group (knowledge). Conversation memory recall passes a per-
        ``(user, character)`` group (memory Phase 1, decision D1). Reads pass
        ``group_ids`` explicitly to the search, so the multi-group ``driver._database``
        write-path concern does not apply here.

        Read-only; does not require :meth:`initialize` (the graph was built at
        ingest). Returns an empty expansion on a blank query — the caller folds
        ``chunk_ids`` into the Qdrant filter and falls back to flat search when empty.
        """
        return await _search_chunk_ids(
            self._graphiti,
            query,
            group_id=group_id or self._group_id,
            num_results=num_results,
            temporal=temporal,
            recipe=self._search_recipe,
            k_hop=self._k_hop if k_hop is None else k_hop,
            min_relevance=self._reranker_min_score,
            sim_min_score=self._sim_min_score,
            scope=self._search_scope,
            show_expiry=show_expiry,
        )

    async def close(self) -> None:
        """Release the Graphiti client + Kuzu driver. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._graphiti.close()
        except Exception:
            log.warning("⚠️ graphiti — close encountered an error", exc_info=True)
        # Shared driver: drop our refcount. The underlying kuzu Database is closed (file
        # lock freed) by the registry only when the LAST consumer releases (refcount → 0),
        # so closing one service never tears down a driver another still holds.
        kuzu_registry.release(self._registry_key, _close_kuzu_driver)

    @classmethod
    def from_preferences(
        cls,
        prefs: WorkspacePreferences,
        workspace_path: Path,
        *,
        workspace_id: str | None = None,
        credential_store: "CredentialStore | None" = None,
        on_usage: UsageSink | None = None,
        require_backend: bool = True,
    ) -> "GraphitiMemoryService | None":
        """Build the service from workspace preferences, or ``None`` when unavailable.

        Returns ``None`` (no error) when ``knowledge.graph.backend`` is ``off``
        (unless ``require_backend=False`` — explicit build-graph/ingest actions still
        run with the backend toggle off) or no extraction model is configured. Same
        enable-gating shape as the prior mem0 service. Resolves both model tiers via
        tuning profiles and the shared knowledge embedder (G8).
        """
        if require_backend and prefs.graph.backend == "off":
            log.info("⬇️ graphiti — backend=off · service not created")
            return None

        extraction = resolve_graphiti_extraction_model(
            prefs, workspace_path, workspace_id=workspace_id, credential_store=credential_store
        )
        if extraction is None:
            log.warning(
                "⚠️ graphiti — no extraction model available (configure knowledge.graph "
                "or knowledge.answering model) · service not created"
            )
            return None
        small = (
            resolve_graphiti_small_model(
                prefs, workspace_path, workspace_id=workspace_id, credential_store=credential_store
            )
            or extraction
        )

        # Shared embedder (G8): build the SAME knowledge backend (same model id ⇒
        # identical vectors). Lazy import keeps the heavy embedder deps off this
        # module's import path.
        from hirocli.services.knowledge.embedder import resolve_knowledge_embedder

        # No forced default: the graph needs a real embedder to build its vector index. Gate here
        # rather than silently picking a model (would orphan vectors on a later change).
        embedder_model_id = resolve_graphiti_embedder_model(prefs)
        if not embedder_model_id:
            raise ValueError(
                "No graph embedder configured. Set the Graph embedder, or a workspace default "
                "embedder (Preferences → General → Default models), before building the graph."
            )
        backend = resolve_knowledge_embedder(
            workspace_path, embedder_model_id, credential_store=credential_store
        )

        # Observability tier gates every usage sink: at ``off`` we wire NONE of them, so the
        # adapters skip the per-call hook entirely (the choke point that spares CPU). ``ledger``
        # and ``trace`` both capture usage — the difference is detail rendering, handled downstream.
        observability = prefs.graph.observability
        observe = observability != "off"

        llm_client = GraphitiLLMClient(
            medium=_spec(extraction),
            small=_spec(small),
            workspace_path=workspace_path,
            workspace_id=workspace_id,
            credential_store=credential_store,
            # Route per-call usage into the active ingest episode (no-op outside
            # ingest, so retrieval/memory paths are unaffected). An explicit
            # ``on_usage`` still overrides for callers that want their own sink.
            on_usage=(on_usage or record_episode_llm_usage) if observe else None,
        )
        embedder = GraphitiEmbedderClient(
            backend, on_embed=record_episode_embed if observe else None
        )

        # Cross-encoder reranker for the fact-search leg (only when the recipe asks for
        # it). Resolve the SAME reranker the flat path uses (cloud or local) and wrap it
        # as Graphiti's CrossEncoderClient. If it can't resolve (unconfigured / local
        # model not downloaded), degrade the recipe to RRF rather than ship a no-op that
        # masquerades as reranking.
        graph = prefs.graph
        recipe = graph.search_recipe
        cross_encoder: CrossEncoderClient | None = None
        reranker_min_score = 0.0
        if recipe == "cross_encoder":
            # Graph override, else the workspace default reranker (llm.default_reranker).
            reranker_model_id = resolve_graph_reranker_model(prefs)
            if reranker_model_id:
                try:
                    from hirocli.services.knowledge.reranker import resolve_reranker

                    compressor, _calibrated = resolve_reranker(
                        reranker_model_id,
                        workspace_path=workspace_path,
                        workspace_id=workspace_id,
                        top_n=_RERANK_CANDIDATE_CAP,  # rank ALL candidates; SearchConfig.limit cuts
                        device=graph.reranker.device,
                        credential_store=credential_store,
                    )
                    # Report rerank usage into the active recall accumulator so the ``rerank``
                    # ledger node carries model + processed tokens and prices via the catalog
                    # (no-op outside a ledgered search; cross_encoder never runs during ingest).
                    cross_encoder = HiroRerankerCrossEncoder(
                        compressor,
                        model_id=reranker_model_id,
                        on_rank=record_rerank_usage if observe else None,
                    )
                    reranker_min_score = graph.reranker.min_relevance
                    log.info("⬇️ graphiti — cross-encoder reranker · model=%s", reranker_model_id)
                except Exception:
                    log.warning(
                        "⚠️ graphiti — cross-encoder reranker %r unavailable; falling back to "
                        "RRF (configure/download the reranker model)",
                        reranker_model_id,
                        exc_info=True,
                    )
                    recipe = "rrf"
            else:
                log.info(
                    "⬇️ graphiti — search_recipe=cross_encoder but no reranker model set "
                    "(graph.reranker.model_id / llm.default_reranker) · using RRF"
                )
                recipe = "rrf"

        return cls(
            db_path=graphiti_db_path(workspace_path),
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
            observability=observability,
            search_recipe=recipe,
            # Which graph elements participate in recall. Validated against ``search_recipe``
            # at pref load (mmr × episodes is rejected up-front), so any value reaching here
            # is a legal combo.
            search_scope=graph.search_scope,
            k_hop=graph.k_hop,
            reranker_min_score=reranker_min_score,
            sim_min_score=graph.sim_min_score,
            query_timeout_s=graph.query_timeout_s,
            entity_ontology=graph.entity_ontology,
            custom_extraction_instructions=graph.custom_extraction_instructions,
        )


@asynccontextmanager
async def _snapshot_read_driver(path: Path, purpose: str = "") -> AsyncIterator[Any]:
    """Yield a dedicated read connection on the *shared* Kuzu ``Database`` (lock-free reads).

    Shared across every read-only graph access (snapshot export, chunk-detail temporal
    lookup). Rationale (docs/kuzu-shared-database-design.md §8, option b): a shallow copy of
    the shared driver reuses its provider/ops/group seed but swaps in our OWN AsyncConnection
    on the shared Database, so reads run on a separate connection from the writer's pinned
    pool=1 one — no head-of-line blocking during a build. Safe: a read never opens a write
    txn (Kuzu = single-writer + concurrent lock-free reads, §3); we only ever touch the
    shared Database object, never a 2nd open (which is what threw "Could not set lock on
    file"). No write lock is taken (reads are lock-free, §4.3). The connection is closed
    BEFORE the refcount is dropped — it's bound to the shared Database and must not outlive
    our hold; the registry closes the shared driver only if we were the last holder.
    """
    key = _registry_key(path)
    driver = kuzu_registry.acquire(
        key, lambda: KuzuDriver(str(path), max_concurrent_queries=1)
    )
    read_driver = copy.copy(driver)
    read_driver.client = kuzu.AsyncConnection(
        driver.db, max_concurrent_queries=_SNAPSHOT_READ_POOL
    )
    # Same per-query ceiling as the writer pool (graph.query_timeout_s): an open snapshot READ
    # is exactly what a checkpoint waits on, so bounding readers kills the blocker side of the
    # freeze too. Pref read is best-effort (db path → workspace root); fallback = pref default.
    timeout_s = 60
    try:
        from hirocli.domain.preferences import load_preferences

        # db/graphiti_kuzu.db → db/ → <workspace> (consolidated db/ layout).
        timeout_s = load_preferences(path.parent.parent).graph.query_timeout_s
    except Exception:
        log.warning("⚠️ graphiti — query-timeout pref read failed; using default", exc_info=True)
    _apply_query_timeout(read_driver.client, timeout_s)
    # Forensic trail for the checkpoint-vs-reader freeze: the OPEN line names which read was
    # in flight when a stall hit (the close line never lands in that case — that's the signal).
    log.info("⬇️ graphiti — snapshot read open · purpose=%s", purpose or "unspecified")
    started = time.perf_counter()
    try:
        yield read_driver
    finally:
        try:
            read_driver.client.close()
        except Exception:
            log.warning(
                "⚠️ graphiti — snapshot read connection close failed", exc_info=True
            )
        kuzu_registry.release(key, _close_kuzu_driver)
        log.info(
            "✅ graphiti — snapshot read closed · purpose=%s · elapsed_ms=%d",
            purpose or "unspecified",
            int((time.perf_counter() - started) * 1000),
        )


async def read_graph_snapshot(
    db_path: Path,
    *,
    node_limit: int | None = None,
    edge_limit: int | None = None,
    group_ids: list[str] | None = None,
) -> tuple[list[Any], list[Any], dict[str, str], dict[str, set[str]]]:
    """Read all entity nodes + RELATES_TO facts for ``group_ids`` (read-only).

    ``group_ids`` defaults to the **knowledge** default group; pass a
    ``mem_{user}_{character}`` group (or any group id) to snapshot a conversation-memory
    graph instead — this is what the admin Graph tab's group filter selects.

    No LLM/embedder (and thus no provider key) is needed — a snapshot only touches the
    graph. Returns ``([], [], {}, {})`` when the DB file does not exist (nothing
    graph-ingested yet) — never a side effect. The third element is a
    ``chunk_id → document_id`` map (episode uuid → ``source_description``) so the viz can
    fill node/edge ``document_ids`` (§5.6). The fourth element maps ``entity_uuid → {episode
    uuids}`` from the ``MENTIONS`` membership, so node provenance includes episodes that NAME
    an entity even when they produced no fact about it (e.g. a single-speaker preference turn
    whose only relation was a dropped self-loop) — without it, such an entity carries no
    chunk_id for that episode and the Graph tab's episode filter can never surface it. Reads
    run on a dedicated connection (see :func:`_snapshot_read_driver`) so a Graph-tab load
    DURING an active build never queues behind the writer.
    """
    from graphiti_core.edges import EntityEdge, EpisodicEdge
    from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError
    from graphiti_core.nodes import EntityNode, EpisodicNode

    path = Path(db_path)
    if not path.exists():
        return [], [], {}, {}
    nodes: list[Any] = []
    edges: list[Any] = []
    chunk_to_document: dict[str, str] = {}
    async with _snapshot_read_driver(path, purpose="graph_snapshot_export") as read_driver:
        # Default to the named knowledge group (kb_main) when no explicit selection is made
        # (docs/graph-group-policy-design.md §7) — never graphiti's empty default group.
        gids = [g for g in (group_ids or []) if g] or [KNOWLEDGE_GROUP_ID]
        # The get_by_group_ids helpers RAISE (not return []) on an empty graph.
        try:
            nodes = await EntityNode.get_by_group_ids(read_driver, gids, limit=node_limit)
        except GroupsNodesNotFoundError:
            nodes = []
        try:
            edges = await EntityEdge.get_by_group_ids(read_driver, gids, limit=edge_limit)
        except GroupsEdgesNotFoundError:
            edges = []
        # Episodes carry document_id in ``source_description`` (set at ingest); map
        # chunk_id (episode uuid) → document_id for node/edge document_ids provenance.
        try:
            episodes = await EpisodicNode.get_by_group_ids(read_driver, gids, limit=node_limit)
        except GroupsNodesNotFoundError:
            episodes = []
        for ep in episodes or []:
            uuid = getattr(ep, "uuid", "") or ""
            doc = getattr(ep, "source_description", "") or ""
            if uuid and doc:
                chunk_to_document[uuid] = doc
        # Episode→entity provenance from the MENTIONS membership (Episodic -[:MENTIONS]-> Entity):
        # source_node_uuid = episode (== chunk_id), target_node_uuid = the entity it names. An
        # entity's chunk_ids are otherwise derived ONLY from the facts touching it, so an entity
        # born from a fact-less episode would be invisible to the episode filter (see docstring).
        episode_mentions: dict[str, set[str]] = {}
        try:
            mentions = await EpisodicEdge.get_by_group_ids(read_driver, gids, limit=edge_limit)
        except GroupsEdgesNotFoundError:
            mentions = []
        for m in mentions or []:
            episode_uuid = getattr(m, "source_node_uuid", "") or ""  # Episodic node == chunk_id
            entity_uuid = getattr(m, "target_node_uuid", "") or ""
            if episode_uuid and entity_uuid:
                episode_mentions.setdefault(entity_uuid, set()).add(episode_uuid)
    return list(nodes or []), list(edges or []), chunk_to_document, episode_mentions


async def read_graph_group_ids(db_path: Path) -> tuple[list[str], str | None]:
    """Distinct group_ids present in the graph + the knowledge default group id (read-only).

    Backs the admin Graph tab's group selector: the knowledge group (``kb_main``) is labeled
    "Knowledge", ``mem_{user}_{character}`` are conversation-memory graphs, ``eval_{set}`` are
    eval corpora (docs/graph-group-policy-design.md §7). Returns ``([], None)`` when the DB
    file does not exist.
    """
    path = Path(db_path)
    if not path.exists():
        return [], None
    # The knowledge partition is the NAMED kb_main group, not graphiti's empty default.
    default_gid = KNOWLEDGE_GROUP_ID
    async with _snapshot_read_driver(path, purpose="group_ids") as read_driver:
        query = "MATCH (e:Episodic) RETURN DISTINCT e.group_id AS group_id"
        try:
            rows, _, _ = await read_driver.execute_query(query)
        except Exception:
            log.warning("⚠️ graphiti — read_graph_group_ids failed", exc_info=True)
            return [], default_gid
    return _distinct_group_ids(rows), default_gid


async def distinct_group_ids_with_prefix(db_path: Path, prefix: str) -> set[str]:
    """Distinct ``group_id``s starting with ``prefix`` present in the graph (read-only).

    A cheap existence probe over the ``Episodic`` node table — one DISTINCT query returns
    every group under a namespace prefix (e.g. ``eval_kb_`` / ``eval_mem_``), so callers
    can test membership instead of opening the DB once per corpus. Returns an empty set
    when ``prefix`` is blank or the DB file does not exist (nothing built yet). Backs the
    eval corpus picker's ``has_graph`` flag.
    """
    path = Path(db_path)
    if not prefix or not path.exists():
        return set()
    query = (
        "MATCH (e:Episodic) WHERE e.group_id STARTS WITH $prefix "
        "RETURN DISTINCT e.group_id AS group_id"
    )
    async with _snapshot_read_driver(path, purpose="group_ids_prefix") as read_driver:
        try:
            rows, _, _ = await read_driver.execute_query(query, prefix=prefix)
        except Exception:
            log.warning(
                "⚠️ graphiti — distinct_group_ids_with_prefix failed · prefix=%s",
                prefix,
                exc_info=True,
            )
            raise
    return set(_distinct_group_ids(rows))


async def read_episode_valid_at(db_path: Path, uuids: list[str]) -> dict[str, str | None]:
    """Map episode uuid (== Qdrant point_id / chunk_id) → its event time (``valid_at`` ISO).

    The Graph tab's chunk-detail panel shows each chunk's *semantic* event time. ``valid_at``
    is the episode's ``reference_time`` (the eval/corpus timestamp) — NOT the Qdrant
    ``ingested_at`` (processing time) — and it lives on the ``EpisodicNode`` in Kuzu, so it
    needs this graph read. Returns ``{}`` when the DB file doesn't exist or ``uuids`` is
    empty; ids with no episode are omitted; episodes with a null ``valid_at`` map to ``None``.
    Read-only on a dedicated connection (lock-free; safe during an active build).
    """
    from graphiti_core.nodes import EpisodicNode

    ids = [str(u) for u in uuids if u]
    path = Path(db_path)
    if not ids or not path.exists():
        return {}
    out: dict[str, str | None] = {}
    async with _snapshot_read_driver(path, purpose="episode_valid_at") as read_driver:
        try:
            episodes = await EpisodicNode.get_by_uuids(read_driver, ids)
        except Exception:
            # A temporal-date lookup is best-effort provenance — a graph read hiccup must
            # not fail the whole chunk-detail panel. Log and return what we have (none).
            log.warning(
                "⚠️ graphiti — episode valid_at lookup failed · count=%d", len(ids), exc_info=True
            )
            return {}
    for ep in episodes or []:
        uuid = getattr(ep, "uuid", "") or ""
        if uuid:
            valid_at = getattr(ep, "valid_at", None)
            out[uuid] = valid_at.isoformat() if isinstance(valid_at, dt.datetime) else None
    return out


async def read_episode_chunks(db_path: Path, uuids: list[str]) -> dict[str, dict[str, Any]]:
    """Map episode uuid → ``{text, group_id, source_description, valid_at}`` from Kuzu.

    Authoritative chunk-text source for **memory** chunks: conversation episodes are
    written to Graphiti/Kuzu only and never to Qdrant, so the Graph viz panel's
    chunk-detail resolver must read their text from ``EpisodicNode.content`` here. The
    same call also returns ``group_id`` so the caller can tell memory from knowledge
    episodes, plus ``source_description`` (the conversation thread / document id) and
    ``valid_at`` (semantic event time) to populate the panel's "doc title" + "when"
    fields without a second read.

    Returns ``{}`` when the DB file does not exist or ``uuids`` is empty; ids with no
    matching episode are omitted. Read-only on a dedicated connection (lock-free; safe
    during an active build) — same pattern as :func:`read_episode_valid_at`.
    """
    from graphiti_core.nodes import EpisodicNode

    ids = [str(u) for u in uuids if u]
    path = Path(db_path)
    if not ids or not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    async with _snapshot_read_driver(path, purpose="episode_chunks") as read_driver:
        try:
            episodes = await EpisodicNode.get_by_uuids(read_driver, ids)
        except Exception:
            # Chunk-text resolution is best-effort provenance — a graph read hiccup
            # must not fail the whole chunk-detail panel. Log and return what we have.
            log.warning(
                "⚠️ graphiti — episode chunk lookup failed · count=%d", len(ids), exc_info=True
            )
            return {}
    for ep in episodes or []:
        uuid = getattr(ep, "uuid", "") or ""
        if not uuid:
            continue
        valid_at = getattr(ep, "valid_at", None)
        out[uuid] = {
            "text": getattr(ep, "content", "") or "",
            "group_id": getattr(ep, "group_id", "") or "",
            "source_description": getattr(ep, "source_description", "") or "",
            "valid_at": valid_at.isoformat() if isinstance(valid_at, dt.datetime) else None,
        }
    return out


async def read_graph_episodes(
    db_path: Path, group_id: str, *, limit: int = 2000
) -> list[dict[str, Any]]:
    """List a group's episodes for the admin Graph tab's episode filter (read-only).

    Backs the "Episodes" multi-select beside the partition selector. Each episode IS a
    citable chunk (decision G6: ``EpisodicNode.uuid == chunk_id == Qdrant point_id``), so the
    returned ``id`` is exactly what node/edge ``chunk_ids`` carry — selecting episodes filters
    the graph to the entities/facts those episodes produced.

    Ordered by ``uuid`` ascending: corpus episode ids are structured + zero-padded
    (``..._m0002``, ``ep_001``), so a lexical sort reproduces the true 1-based corpus order
    WITHOUT relying on ``valid_at`` (which is not unique across a session and would tie — the
    reason a timestamp sort was rejected). Returns
    ``[{id, snippet, preview, valid_at, document_id}]``, or ``[]`` when the DB file doesn't exist /
    the group has no episodes. ``preview`` is the de-stamped transcript for the picker's hover
    tooltip (see :func:`clean_episode_transcript`); the compact "time · turns" label is built
    client-side from ``snippet``.

    Pages via ``uuid_cursor`` (``get_by_group_ids`` orders uuid DESC) so a large group can't
    strand a tail behind the page limit. Read-only on a dedicated connection (lock-free; safe
    during an active build) — same pattern as :func:`read_episode_chunks`.
    """
    from graphiti_core.errors import GroupsNodesNotFoundError
    from graphiti_core.nodes import EpisodicNode

    from hirocli.services.knowledge.graph.episode_summary import clean_episode_transcript

    gid = (group_id or "").strip()
    path = Path(db_path)
    if not gid or not path.exists():
        return []
    out: list[dict[str, Any]] = []
    async with _snapshot_read_driver(path, purpose="graph_episodes") as read_driver:
        cursor: str | None = None
        while len(out) < limit:
            try:
                batch = await EpisodicNode.get_by_group_ids(
                    read_driver, [gid], limit=_EPISODE_WIPE_PAGE, uuid_cursor=cursor
                )
            except GroupsNodesNotFoundError:
                break  # empty graph / no episodes in this group
            if not batch:
                break
            for ep in batch:
                uuid = getattr(ep, "uuid", "") or ""
                if not uuid:
                    continue
                content = getattr(ep, "content", "") or ""
                valid_at = getattr(ep, "valid_at", None)
                out.append(
                    {
                        "id": uuid,
                        "snippet": " ".join(content.split())[:120],
                        # Clean multi-line transcript (speaker turns, no "[ts]" stamps) for the
                        # picker's hover tooltip; the compact label is derived client-side.
                        "preview": clean_episode_transcript(content),
                        "valid_at": valid_at.isoformat()
                        if isinstance(valid_at, dt.datetime)
                        else None,
                        "document_id": getattr(ep, "source_description", "") or "",
                    }
                )
            if len(batch) < _EPISODE_WIPE_PAGE:
                break
            cursor = getattr(batch[-1], "uuid", None)
            if not cursor:
                break
    # Corpus order: lexical asc on the structured, zero-padded chunk_id (see docstring) — the
    # 1-based episode number is then just the row position, deterministic and tie-free.
    out.sort(key=lambda e: e["id"])
    return out[:limit]


# ``is_memory_group_id`` now lives in the shared group-ID policy module (group_scope) and is
# imported above; re-exported here so existing ``from ...graphiti_service import is_memory_group_id``
# callers keep working (docs/graph-group-policy-design.md).


__all__ = [
    "GraphitiMemoryService",
    "graphiti_db_path",
    "is_memory_group_id",
    "read_episode_chunks",
    "read_episode_valid_at",
    "read_graph_episodes",
    "read_graph_snapshot",
]
