"""GraphitiMemoryService — bootstrap + lifecycle for the Graphiti temporal graph.

Mirrors how ``Mem0MemoryService`` sits behind a single service boundary: nothing
outside this module imports ``graphiti_core`` directly, so the brain stays
rip-out-able (decision G3/G8, docs/knowledge-graphiti-pivot-design.md §4).

Bootstrap wires:

  Graphiti(
      graph_driver = KuzuDriver(workspace/knowledge/graph/graphiti_kuzu.db),
      llm_client   = GraphitiLLMClient(model_factory + tuning profiles + ledger),
      embedder     = GraphitiEmbedderClient(shared knowledge embedder),
      cross_encoder= RRF passthrough (avoids Graphiti's default OpenAI reranker),
  )

Ingest (``add_episode``) and search land in later phases; this module owns
construction, ``build_indices_and_constraints``, and teardown only.
"""

from __future__ import annotations

import copy
import datetime as dt
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

import kuzu
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.errors import NodeNotFoundError
from graphiti_core.graph_queries import get_fulltext_indices
from graphiti_core.helpers import get_default_group_id
from hiro_commons.log import Logger

from hirocli.domain.preferences import (
    ModelTuning,
    ResolvedModel,
    WorkspacePreferences,
    resolve_graphiti_embedder_model,
    resolve_graphiti_extraction_model,
    resolve_graphiti_small_model,
)
from hirocli.services.knowledge.constants import GRAPH_DIR, KNOWLEDGE_DIR, KUZU_DB_FILENAME

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
)
from .graphiti_ontology import GRAPHITI_ENTITY_TYPES
from .graphiti_search import GraphitiExpansion
from .graphiti_search import search_chunk_ids as _search_chunk_ids
from .ingest_ledger import record_episode_embed, record_episode_llm_usage
from .ledger_tracer import LedgerTracer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.llm_client.client import LLMClient

    from hirocli.domain.credential_store import CredentialStore
    from hirocli.runtime.agent_graph.ledger import LedgerSink

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI")

# Reranker ``top_n`` for the cross-encoder: rank ALL candidate facts Graphiti hands it
# (the final cut is Graphiti's ``SearchConfig.limit``). Generous so we never pre-trim.
_RERANK_CANDIDATE_CAP = 512

# Dedicated read-connection pool size for the Graph-tab snapshot (docs
# kuzu-shared-database-design.md §8, option b — "1 writer + N readers"). The snapshot
# reads through its OWN AsyncConnection on the shared kuzu.Database so it never queues
# behind the writer's pinned pool=1 connection during a build. Read-only ⇒ a larger pool
# is safe (concurrent reads never open a write txn); only the WRITER driver must stay at 1
# (§4.4). 4 matches kuzu's AsyncConnection default.
_SNAPSHOT_READ_POOL = 4


async def _ensure_fts_indices(driver: Any) -> None:
    """Create the Kuzu full-text indices graphiti-core 0.29.1 never builds.

    graphiti's ``KuzuDriver.build_indices_and_constraints()`` is a no-op and
    ``setup_schema()`` only creates the node/rel TABLES — but its edge/node dedup
    search runs ``QUERY_FTS_INDEX('RelatesToNode_', 'edge_name_and_fact', …)``. Without
    these indices, the FIRST ``add_episode`` crashes with "Table RelatesToNode_ doesn't
    have an index with name edge_name_and_fact". We run graphiti's OWN DDL
    (``get_fulltext_indices`` — no duplication) once here. Kuzu auto-loads the ``fts``
    extension, and creating over empty tables is fine.

    Idempotent: the DB file persists across restarts, so a re-create raises
    "Index … already exists" — swallow only that, raise anything else.
    """
    for stmt in get_fulltext_indices(driver.provider):
        try:
            await driver.execute_query(stmt)
        except Exception as exc:
            if "already exists" in str(exc).lower():
                continue
            log.exception("❌ graphiti — FTS index creation failed · stmt=%s", stmt[:64])
            raise


def _registry_key(db_path: Path) -> str:
    """Stable process-wide key for the shared Kuzu driver of one workspace graph.

    Both the ingest service and the snapshot reader derive the key from the SAME
    absolute path so they share one ``Database`` via ``kuzu_registry`` (resolve() so
    differing relative/symlinked spellings of the same file map to one entry)."""
    return str(Path(db_path).resolve())


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
        ),
    )


def graphiti_db_path(workspace_path: Path) -> Path:
    """Per-workspace Kuzu DB file for the Graphiti graph."""
    return workspace_path / KNOWLEDGE_DIR / GRAPH_DIR / KUZU_DB_FILENAME


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
        ledger_detail: str = "rich",
        search_recipe: str = "rrf",
        k_hop: int = 1,
        reranker_min_score: float = 0.0,
        sim_min_score: float = 0.3,
    ) -> None:
        self._ledger_detail = ledger_detail
        # Retrieval knobs (admin prefs) threaded into every search_chunk_ids call.
        self._search_recipe = search_recipe
        self._k_hop = k_hop
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
        try:
            tracer = LedgerTracer()
            self._graphiti.tracer = tracer
            self._graphiti.clients.tracer = tracer
            self._graphiti.llm_client.set_tracer(tracer)
        except Exception:
            # Observability must never break the graph itself.
            log.warning("⚠️ graphiti — ledger tracer injection failed", exc_info=True)
        # Resolve ONE concrete group_id shared by ingest / search / snapshot
        # (snapshot's get_by_group_ids needs a concrete list).
        self._group_id = group_id or get_default_group_id(driver.provider)
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
            # No-op for Kuzu (above) → we must create the FTS indices ourselves, else
            # the first add_episode's edge dedup search crashes (graphiti-core gap). The
            # unit-test fake graphiti has no real `.driver` → skip (no Kuzu there).
            driver = getattr(self._graphiti, "driver", None)
            if driver is not None:
                await _ensure_fts_indices(driver)
        except Exception:
            log.exception("❌ graphiti — build_indices_and_constraints failed")
            raise
        self._initialized = True
        log.info("✅ graphiti — graph ready · path=%s", self._db_path)

    async def ingest_chunks(
        self,
        episodes: "Sequence[GraphitiEpisodeInput]",
        *,
        source_role: str,
        event_sink: GraphEventSink | None = None,
        ledger_sink: "LedgerSink | None" = None,
    ) -> GraphitiIngestStats:
        """Ingest document chunks as Graphiti episodes (F7 write-gated, sequential).

        Auto-initializes the graph on first use. Uses the pinned entity ontology;
        edge-type vocabulary is left free-form for now (see graphiti_ontology).

        ``ledger_sink`` records a ``graph_ingest`` run (per-episode step + per-operation
        sub-step nodes) in Graph Runs; ``None`` = no ledger (tests/CLI)."""
        await self.initialize()
        return await ingest_episodes(
            self._graphiti,
            episodes,
            source_role=source_role,
            group_id=self._group_id,
            entity_types=GRAPHITI_ENTITY_TYPES,
            event_sink=event_sink,
            ledger_sink=ledger_sink,
            ledger_detail=self._ledger_detail,
            # Per-workspace write lock: serialize every writer (this ingest, a concurrent
            # eval/graph build, future chat-memory) to one add_episode at a time. Required
            # by Kuzu (single-writer) AND graphiti (sequential dedup). Held per-episode and
            # released between episodes (docs §4.2), so a waiting reader/writer isn't
            # blocked for the whole batch.
            write_lock=kuzu_registry.write_lock(self._registry_key),
        )

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

    async def search_chunk_ids(
        self,
        query: str,
        *,
        num_results: int = 20,
        temporal: str = "current",
    ) -> GraphitiExpansion:
        """Graphiti fact search → focused Qdrant chunk_ids (+ fact texts).

        Read-only; does not require :meth:`initialize` (the graph was built at
        ingest). Returns an empty expansion on a blank query — the caller folds
        ``chunk_ids`` into the Qdrant filter and falls back to flat search when empty.
        """
        return await _search_chunk_ids(
            self._graphiti,
            query,
            group_id=self._group_id,
            num_results=num_results,
            temporal=temporal,
            recipe=self._search_recipe,
            k_hop=self._k_hop,
            min_relevance=self._reranker_min_score,
            sim_min_score=self._sim_min_score,
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
        enable-gating shape as ``Mem0MemoryService``. Resolves both model tiers via
        tuning profiles and the shared knowledge embedder (G8).
        """
        if require_backend and prefs.knowledge.graph.backend == "off":
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

        embedder_model_id = resolve_graphiti_embedder_model(prefs)
        backend = resolve_knowledge_embedder(
            workspace_path, embedder_model_id, credential_store=credential_store
        )

        llm_client = GraphitiLLMClient(
            medium=_spec(extraction),
            small=_spec(small),
            workspace_path=workspace_path,
            workspace_id=workspace_id,
            credential_store=credential_store,
            # Route per-call usage into the active ingest episode (no-op outside
            # ingest, so retrieval/memory paths are unaffected). An explicit
            # ``on_usage`` still overrides for callers that want their own sink.
            on_usage=on_usage or record_episode_llm_usage,
        )
        embedder = GraphitiEmbedderClient(backend, on_embed=record_episode_embed)

        # Cross-encoder reranker for the fact-search leg (only when the recipe asks for
        # it). Resolve the SAME reranker the flat path uses (cloud or local) and wrap it
        # as Graphiti's CrossEncoderClient. If it can't resolve (unconfigured / local
        # model not downloaded), degrade the recipe to RRF rather than ship a no-op that
        # masquerades as reranking.
        graph = prefs.knowledge.graph
        recipe = graph.search_recipe
        cross_encoder: CrossEncoderClient | None = None
        reranker_min_score = 0.0
        if recipe == "cross_encoder":
            reranker_model_id = (graph.reranker.model_id or "").strip() or (
                prefs.knowledge.retrieval.reranker.model_id or ""
            ).strip() or None
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
                    cross_encoder = HiroRerankerCrossEncoder(compressor)
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
                    "(graph.reranker.model_id / knowledge.retrieval.reranker.model_id) · using RRF"
                )
                recipe = "rrf"

        return cls(
            db_path=graphiti_db_path(workspace_path),
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
            ledger_detail=graph.ledger_detail,
            search_recipe=recipe,
            k_hop=graph.k_hop,
            reranker_min_score=reranker_min_score,
            sim_min_score=graph.sim_min_score,
        )


@asynccontextmanager
async def _snapshot_read_driver(path: Path) -> AsyncIterator[Any]:
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


async def read_graph_snapshot(
    db_path: Path,
    *,
    node_limit: int | None = None,
    edge_limit: int | None = None,
) -> tuple[list[Any], list[Any], dict[str, str]]:
    """Read all entity nodes + RELATES_TO facts for the default group (read-only).

    No LLM/embedder (and thus no provider key) is needed — a snapshot only touches the
    graph. Returns ``([], [], {})`` when the DB file does not exist (nothing
    graph-ingested yet) — never a side effect. The third element is a
    ``chunk_id → document_id`` map (episode uuid → ``source_description``) so the viz can
    fill node/edge ``document_ids`` (§5.6). The load path for the admin Graph tab
    (docs/knowledge-graphiti-pivot-design.md §5.6). Reads run on a dedicated connection
    (see :func:`_snapshot_read_driver`) so a Graph-tab load DURING an active build never
    queues behind the writer.
    """
    from graphiti_core.edges import EntityEdge
    from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError
    from graphiti_core.nodes import EntityNode, EpisodicNode

    path = Path(db_path)
    if not path.exists():
        return [], [], {}
    nodes: list[Any] = []
    edges: list[Any] = []
    chunk_to_document: dict[str, str] = {}
    async with _snapshot_read_driver(path) as read_driver:
        gid = get_default_group_id(read_driver.provider)
        # The get_by_group_ids helpers RAISE (not return []) on an empty graph.
        try:
            nodes = await EntityNode.get_by_group_ids(read_driver, [gid], limit=node_limit)
        except GroupsNodesNotFoundError:
            nodes = []
        try:
            edges = await EntityEdge.get_by_group_ids(read_driver, [gid], limit=edge_limit)
        except GroupsEdgesNotFoundError:
            edges = []
        # Episodes carry document_id in ``source_description`` (set at ingest); map
        # chunk_id (episode uuid) → document_id for node/edge document_ids provenance.
        try:
            episodes = await EpisodicNode.get_by_group_ids(read_driver, [gid], limit=node_limit)
        except GroupsNodesNotFoundError:
            episodes = []
        for ep in episodes or []:
            uuid = getattr(ep, "uuid", "") or ""
            doc = getattr(ep, "source_description", "") or ""
            if uuid and doc:
                chunk_to_document[uuid] = doc
    return list(nodes or []), list(edges or []), chunk_to_document


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
    async with _snapshot_read_driver(path) as read_driver:
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


__all__ = [
    "GraphitiMemoryService",
    "graphiti_db_path",
    "read_episode_valid_at",
    "read_graph_snapshot",
]
