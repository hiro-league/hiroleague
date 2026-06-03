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

from pathlib import Path
from typing import TYPE_CHECKING, Any

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver.kuzu_driver import KuzuDriver
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

from .graphiti_adapters import (
    GraphitiEmbedderClient,
    GraphitiLLMClient,
    GraphitiModelSpec,
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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.llm_client.client import LLMClient

    from hirocli.domain.credential_store import CredentialStore

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI")


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


def _release_kuzu(driver: Any) -> None:
    """Explicitly close the underlying kuzu Connection + Database to release the
    file lock NOW.

    Graphiti's ``KuzuDriver.close()`` is a no-op (it relies on GC), which keeps the
    Kuzu single-opener file lock held — blocking any subsequent open of the same DB
    (e.g. a snapshot read right after ingest). Closing the connection then the
    database releases the lock deterministically."""
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
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        log.info("⬇️ graphiti — opening Kuzu graph · path=%s", self._db_path)
        try:
            driver = KuzuDriver(str(self._db_path))
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
    ) -> GraphitiIngestStats:
        """Ingest document chunks as Graphiti episodes (F7 write-gated, sequential).

        Auto-initializes the graph on first use. Uses the pinned entity ontology;
        edge-type vocabulary is left free-form for now (see graphiti_ontology)."""
        await self.initialize()
        return await ingest_episodes(
            self._graphiti,
            episodes,
            source_role=source_role,
            group_id=self._group_id,
            entity_types=GRAPHITI_ENTITY_TYPES,
            event_sink=event_sink,
        )

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
        # Graphiti's KuzuDriver.close() is a no-op → release the Kuzu file lock now.
        _release_kuzu(getattr(self._graphiti, "driver", None))

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
            on_usage=on_usage,
        )
        embedder = GraphitiEmbedderClient(backend)

        return cls(
            db_path=graphiti_db_path(workspace_path),
            llm_client=llm_client,
            embedder=embedder,
        )


async def read_graph_snapshot(
    db_path: Path,
    *,
    node_limit: int | None = None,
    edge_limit: int | None = None,
) -> tuple[list[Any], list[Any]]:
    """Read all entity nodes + RELATES_TO facts for the default group (read-only).

    Opens a Kuzu driver **directly** — a snapshot only touches the graph, so no
    LLM/embedder (and thus no provider key) is needed. Returns ``([], [])`` when the
    DB file does not exist (nothing graph-ingested yet) — never a side effect.
    The load path for the admin Graph tab (docs/knowledge-graphiti-pivot-design.md §5.6).
    """
    from graphiti_core.edges import EntityEdge
    from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError
    from graphiti_core.nodes import EntityNode

    path = Path(db_path)
    if not path.exists():
        return [], []
    driver = KuzuDriver(str(path))
    nodes: list[Any] = []
    edges: list[Any] = []
    try:
        gid = get_default_group_id(driver.provider)
        # The get_by_group_ids helpers RAISE (not return []) on an empty graph.
        try:
            nodes = await EntityNode.get_by_group_ids(driver, [gid], limit=node_limit)
        except GroupsNodesNotFoundError:
            nodes = []
        try:
            edges = await EntityEdge.get_by_group_ids(driver, [gid], limit=edge_limit)
        except GroupsEdgesNotFoundError:
            edges = []
    finally:
        try:
            await driver.close()
        except Exception:
            log.warning("⚠️ graphiti — snapshot driver close failed", exc_info=True)
        _release_kuzu(driver)
    return list(nodes or []), list(edges or [])


__all__ = ["GraphitiMemoryService", "graphiti_db_path", "read_graph_snapshot"]
