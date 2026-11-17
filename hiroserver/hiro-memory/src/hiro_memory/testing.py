"""Test doubles for code built on the memory engine: a ledger sink that records rows, a scripted chat model
that replays canned replies, and a fake knowledge retrieval engine. Used by the library's tests and by its owners' tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from .ledger import LedgerSink

if TYPE_CHECKING:
    from .knowledge.models import KnowledgeSearchHit


# ---------------------------------------------------------------------------
# Recording ledger sink — captures the row dicts each node flushes
# ---------------------------------------------------------------------------


class RecordingLedgerSink(LedgerSink):
    """A ``LedgerSink`` that records flushed rows in memory instead of writing CSV.

    ``write_rows`` is the single sink path every node row passes through (``ledger.py``). We
    keep the ``to_row()`` dicts and skip both the CSV write and pricing so capture is fast,
    dependency-free, and stable for snapshotting.
    """

    def __init__(self, workspace_path: Any) -> None:
        super().__init__(workspace_path)
        self.captured: list[dict[str, Any]] = []

    def write_rows(self, rows: list[dict[str, Any]]) -> None:  # noqa: D102 (see class)
        self.captured.extend(rows)

    # -- projections used by tests -----------------------------------------

    def nodes(self) -> list[str]:
        """Ordered node names of captured rows (parent + child rows)."""
        return [str(r.get("node") or "") for r in self.captured]

    def decisions(self) -> dict[str, tuple[str, str]]:
        """Map ``node -> (decision_kind, decision_detail)`` (last write wins)."""
        return {
            str(r.get("node") or ""): (
                str(r.get("decision_kind") or ""),
                str(r.get("decision_detail") or ""),
            )
            for r in self.captured
        }

    def row(self, node: str) -> dict[str, Any] | None:
        for r in self.captured:
            if r.get("node") == node:
                return r
        return None

    def has_usage(self, node: str) -> bool:
        r = self.row(node) or {}
        return bool(r.get("input_tokens")) or bool(r.get("output_tokens"))


# ---------------------------------------------------------------------------
# Scripted chat model — returns canned AIMessages in order; bind_tools is a no-op
# ---------------------------------------------------------------------------


class ScriptedChatModel(BaseChatModel):
    """A ``BaseChatModel`` that replays ``responses`` in order, one per ``ainvoke``.

    The fake scripts tool calls itself (an ``AIMessage`` with ``tool_calls``), so ``bind_tools``
    just returns ``self``. Each response should carry ``usage_metadata`` when the test asserts
    the LLM-usage ledger/event.

    ``with_structured_output`` returns a small runnable that consumes the NEXT scripted response
    (sharing the same cursor) and parses its JSON content into ``schema`` — so the retrieval loop's
    dedicated final structured turn can be scripted alongside the search turns (see ``ai_final``).
    """

    responses: list[Any]
    model_config = {"arbitrary_types_allowed": True}
    _cursor: list[int] = PrivateAttr(default_factory=lambda: [0])

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _take(self) -> Any:
        i = self._cursor[0]
        msg = self.responses[min(i, len(self.responses) - 1)]
        self._cursor[0] = i + 1
        return msg

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, **kwargs: Any) -> Any:
        return _ScriptedStructured(self, schema, include_raw)

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._take())])


class _ScriptedStructured:
    """Runnable returned by ``ScriptedChatModel.with_structured_output`` — parses the next scripted
    response's JSON content into ``schema`` (mirrors langchain's ``include_raw`` envelope)."""

    def __init__(self, model: "ScriptedChatModel", schema: Any, include_raw: bool) -> None:
        self._model = model
        self._schema = schema
        self._include_raw = include_raw

    async def ainvoke(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        msg = self._model._take()
        content = getattr(msg, "content", "") or ""
        parsed = None
        error = None
        if isinstance(content, str) and content.strip().startswith("{"):
            try:
                parsed = self._schema.model_validate_json(content)
            except Exception as exc:  # noqa: BLE001 — surfaced via parsing_error like langchain
                error = exc
        if self._include_raw:
            return {"raw": msg, "parsed": parsed, "parsing_error": error}
        return parsed


def ai_text(text: str, *, input_tokens: int = 10, output_tokens: int = 5) -> AIMessage:
    """A plain text assistant reply carrying usage metadata."""
    return AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


def ai_tool_call(name: str, args: dict[str, Any], *, call_id: str = "call_1") -> AIMessage:
    """An assistant turn that requests one tool call (drives the tools loop)."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id}],
        usage_metadata={"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
    )


def ai_final(answer: str) -> AIMessage:
    """A final answer reply: a plain ``AIMessage`` whose content IS the answer. Reused for both an
    exit-A stop turn (no tool call) and the exit-B ``_final_answer_turn`` — both return content
    verbatim now that reduce is gone."""
    return AIMessage(
        content=answer,
        usage_metadata={"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
    )


# ---------------------------------------------------------------------------
# Knowledge fakes — the retrieval engine the knowledge graph drives
# ---------------------------------------------------------------------------


def knowledge_hit(
    *,
    point_id: str = "p1",
    text: str = "Hiro is a local-first assistant.",
    score: float = 0.9,
    title: str = "Hiro Overview",
) -> "KnowledgeSearchHit":
    """Build a fully-populated ``KnowledgeSearchHit`` for the knowledge graph."""
    from .knowledge.models import KnowledgeSearchHit

    return KnowledgeSearchHit(
        document_id="doc1",
        point_id=point_id,
        score=score,
        ord=0,
        text=text,
        heading_path="Intro",
        title=title,
        source_uri="kb://doc1",
        owner_kind="system",
        owner_id="",
        category_id=None,
        subcategory_id=None,
        tags=[],
    )


class FakeKnowledgeRetriever:
    """Stub for the retrieval engine ``KnowledgeAgentGraph`` drives (``KnowledgeRetriever``).

    Dense/sparse embed, vector search and the by-id fetch (graphiti leg); ``rerank_hits`` keeps the order (an
    owner's reranker hand-in can call it).
    """

    def __init__(self, *, hits: "list[KnowledgeSearchHit] | None" = None) -> None:
        self._hits = hits if hits is not None else [knowledge_hit()]

    async def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    async def embed_query_sparse(self, text: str) -> Any:
        return {"indices": [1], "values": [1.0]}

    async def vector_search_by_vector(self, vector: Any, sparse: Any = None, **_: Any) -> "list[KnowledgeSearchHit]":
        return list(self._hits)

    async def rerank_hits(self, query: str, hits: list[Any], **_: Any) -> list[Any]:
        return list(hits)

    async def fetch_hits_by_point_ids(self, point_ids: list[str]) -> "list[KnowledgeSearchHit]":
        return []
