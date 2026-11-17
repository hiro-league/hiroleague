"""What an owner hands ``KnowledgeAgentGraph`` for one build.

The library never imports its owner. The core and EvalHiro each build a ``KnowledgeGraphConfig``: the retrieval
engine (embed + search over the Qdrant collection), the settings values, the answering and rewrite models, the
reranker, and the graph leg. Everything that needs the owner's catalog, credentials or preferences is resolved by the
owner, behind the callables here, so it runs at the same moment it always did (per node run, not per build).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.language_models.chat_models import BaseChatModel

from hiro_memory.knowledge.settings import KnowledgeSettings

if TYPE_CHECKING:
    from qdrant_client import models as qm

    from hiro_memory.knowledge.embedding_backends import SparseVectorData
    from hiro_memory.knowledge.graph_session import GraphitiSession
    from hiro_memory.knowledge.models import KnowledgeSearchHit


class KnowledgeRetriever(Protocol):
    """The retrieval engine the graph drives: embed the query, search the collection, fetch passages by id.

    The core's ``KnowledgeService`` is one; any object over ``KnowledgeVectorStore`` and the two embedders is another.
    """

    async def embed_query(self, query: str) -> list[float]: ...

    async def embed_query_sparse(self, query: str) -> "SparseVectorData": ...

    async def vector_search_by_vector(
        self,
        vector: list[float],
        sparse_vector: "SparseVectorData | None" = None,
        *,
        top_k: int,
        min_score: float,
        prefetch_limit: int = 40,
        hybrid: bool = True,
        explain: bool = False,
        qdrant_filter: "qm.Filter | None" = None,
    ) -> list["KnowledgeSearchHit"]: ...

    async def fetch_hits_by_point_ids(self, point_ids: list[str]) -> list["KnowledgeSearchHit"]: ...


@dataclass(frozen=True)
class KnowledgeModel:
    """A chat model the owner picked for one step (answering or rewrite), with the tuning the ledger shows.

    ``build`` makes the LangChain model (it may raise: the node records the failure and falls back).
    ``structured_output`` says whether the model can return structured output, which the rewrite step needs.
    """

    model_id: str
    build: Callable[[], BaseChatModel]
    temperature: float | None = None
    max_tokens: int | None = None
    thinking: str | None = None
    structured_output: bool = True


@dataclass(frozen=True)
class KnowledgeReranker:
    """The reranker the owner picked: its model id (ledger and pricing) and the call that reorders and trims hits.

    ``rerank(query, hits, top_n)`` returns the hits reordered with ``rerank_score`` and ``relevance`` set
    (``hiro_memory.knowledge.rerank.rerank_hits`` over a LangChain ``BaseDocumentCompressor`` does exactly that).
    """

    model_id: str
    rerank: Callable[[str, list["KnowledgeSearchHit"], int], Awaitable[list["KnowledgeSearchHit"]]]


@dataclass(frozen=True)
class KnowledgeGraphLeg:
    """The Graphiti graph the ``graphiti`` leg reads.

    ``workspace_path`` holds the graph's Kuzu file and the retrieval-trace sidecars. ``open_session`` opens a
    ``GraphitiSession`` (or yields None when the graph backend is off or has no model): see
    ``hiro_memory.knowledge.graph_session.open_graphiti_session``. ``query_timeout_s`` is read at each graph read.
    """

    workspace_path: Path
    open_session: Callable[[], AbstractAsyncContextManager["GraphitiSession | None"]]
    query_timeout_s: Callable[[], int]


# Pushes one model call's usage payload onto the run's stream (the owner's event name and shape).
UsageEmitter = Callable[[Any, dict[str, Any]], None]
# Binds a response schema to a model, ``with_structured_output(schema, include_raw=True)`` shape. The owner may hand
# in one that works around provider quirks (the core's ``with_structured_output_compat``).
StructuredOutput = Callable[[BaseChatModel, Any], Any]


def default_structured_output(model: BaseChatModel, schema: Any) -> Any:
    return model.with_structured_output(schema, include_raw=True)


@dataclass(frozen=True)
class KnowledgeGraphConfig:
    """Per-build inputs for ``KnowledgeAgentGraph``.

    - ``engine``: the retrieval engine (``KnowledgeRetriever``).
    - ``settings``: the settings values for this build (a snapshot).
    - ``answering_model`` / ``rewrite_model``: called when the step runs; None = no model configured (the answer
      falls back to a source list, the rewrite is skipped).
    - ``reranker``: called when the rerank step runs; None = no reranker (retrieval order kept).
    - ``embedder_model``: the dense embedder's model id, for the ledger's model column and pricing.
    - ``graph``: the graph leg; None = no graph (``graph_mode=graphiti`` falls back to the flat leg).
    - ``emit_usage``: pushes each model call's usage onto the stream (None = not pushed).
    - ``structured_output``: how the rewrite step binds its schema.
    """

    engine: KnowledgeRetriever
    settings: KnowledgeSettings = field(default_factory=KnowledgeSettings)
    answering_model: Callable[[], KnowledgeModel | None] = lambda: None
    rewrite_model: Callable[[], KnowledgeModel | None] = lambda: None
    reranker: Callable[[], KnowledgeReranker | None] = lambda: None
    embedder_model: str | None = None
    graph: KnowledgeGraphLeg | None = None
    emit_usage: UsageEmitter | None = None
    structured_output: StructuredOutput = default_structured_output
