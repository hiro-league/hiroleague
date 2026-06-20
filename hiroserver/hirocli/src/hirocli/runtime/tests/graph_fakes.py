"""Shared fakes + capture helpers for the agent-graph characterization net (docs §5.2).

These pin the *observable contract* of the two LangGraph graphs so the upcoming refactor
(see ``docs/agent-graph-refactor-design.md``) can move code underneath them. The contract has
three dimensions, captured here without mocking graph internals:

  1. **Events** — the ordered ``GRAPH_*`` domain events a run writes to the custom stream
     (exactly how ``AgentManager`` consumes them: ``astream(stream_mode=["values","custom"])``).
  2. **Final state** — the last ``values`` snapshot from the same stream.
  3. **Ledger rows** — the structured ``to_row()`` dicts each node flushes, captured by a
     :class:`RecordingLedgerSink` (no CSV / no pricing — just the dicts, for stable snapshots).

Everything is duck-typed against what the nodes actually call, so the fakes carry the minimum
surface and nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_IMAGE,
    CONTENT_TYPE_TEXT,
)
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import PrivateAttr

from hirocli.domain.memory import MemoryAddResult
from hirocli.runtime.agent_graph.ledger import LedgerSink
from hirocli.services.knowledge.models import KnowledgeSearchHit
from hirocli.services.stt.provider import TranscriptionResult
from hirocli.services.tts.provider import TTSResult

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
    """

    responses: list[Any]
    model_config = {"arbitrary_types_allowed": True}
    _cursor: list[int] = PrivateAttr(default_factory=lambda: [0])

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        i = self._cursor[0]
        msg = self.responses[min(i, len(self.responses) - 1)]
        self._cursor[0] = i + 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


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


@tool
def echo_tool(text: str) -> str:
    """Echo the input back (test tool for the tools-loop scenario)."""
    return f"echo: {text}"


# ---------------------------------------------------------------------------
# Media + memory service fakes (duck-typed against the node call sites)
# ---------------------------------------------------------------------------


class FakeSTT:
    """STT stub. ``mode='ok'`` transcribes; ``mode='fail'`` raises; ``mode='unavailable'``."""

    def __init__(self, *, text: str = "hello from audio", mode: str = "ok") -> None:
        self._text = text
        self._mode = mode
        self._default_model = "fake:stt"
        self._model_to_provider: dict[str, Any] = {}

    def is_available(self) -> bool:
        return self._mode != "unavailable"

    async def transcribe(self, body: str, *, mime_type: str) -> TranscriptionResult:
        if self._mode == "fail":
            raise RuntimeError("stt boom")
        return TranscriptionResult(
            text=self._text,
            model="fake:stt",
            provider="fake",
            usage_metadata={"audio_tokens": 4, "output_tokens": 2},
        )


class FakeVision:
    def __init__(self, *, description: str = "a red bicycle", mode: str = "ok") -> None:
        self._description = description
        self._mode = mode

    def is_available(self) -> bool:
        return self._mode != "unavailable"

    async def describe(self, source: str, prompt: str | None = None) -> str:
        if self._mode == "fail":
            raise RuntimeError("vision boom")
        return self._description


class FakeTTS:
    def __init__(self, *, mode: str = "ok") -> None:
        self._mode = mode

    def is_available(self) -> bool:
        return self._mode != "unavailable"

    async def synthesize(self, text: str, *, model: str, voice: str, instructions: str | None = None) -> TTSResult:
        if self._mode == "fail":
            raise RuntimeError("tts boom")
        return TTSResult(
            audio_bytes=b"AAAA",
            mime_type="audio/mpeg",
            duration_ms=1200,
            model=model or "fake:tts",
            voice=voice or "alloy",
            provider="fake",
            usage_metadata={},
        )


class FakeMemory:
    """Conversation-memory stub mirroring ``MemoryService.search`` / ``add``."""

    def __init__(self, *, hits: list[dict[str, Any]] | None = None, stored_count: int = 1) -> None:
        self._hits = hits if hits is not None else [{"memory": "User prefers concise replies"}]
        self._stored_count = stored_count
        self.added: list[dict[str, Any]] = []

    async def search(self, query: str, *, user_id: int, character_id: str, **_: Any) -> list[dict[str, Any]]:
        return list(self._hits)

    async def add(
        self,
        content: str,
        *,
        user_id: int,
        run_id: str,
        character_id: str,
        metadata: dict[str, Any] | None = None,
        ledger_sink: Any = None,
    ) -> MemoryAddResult:
        self.added.append({"content": content, "metadata": metadata or {}})
        stored = tuple({"memory": f"stored {i + 1}"} for i in range(self._stored_count))
        return MemoryAddResult(usage=None, stored_count=self._stored_count, stored_items=stored)


# ---------------------------------------------------------------------------
# Knowledge fakes — the nested chat subgraph + the service the full graph drives
# ---------------------------------------------------------------------------


@dataclass
class FakeKnowledgeSource:
    """Minimal KnowledgeSource shape read by compose_context + reply serialization."""

    ref: int = 1
    title: str = "Hiro Overview"
    heading_path: str | None = "Intro"
    text: str = "Hiro is a local-first assistant."
    score: float = 0.9
    source_uri: str = "kb://doc1"
    document_id: str = "doc1"


class FakeKnowledgeSubgraph:
    """Stub for the compiled retrieval-only subgraph the chat graph nests (``ainvoke`` only)."""

    def __init__(self, *, sources: list[Any] | None = None, context: str = "KB context") -> None:
        self._sources = sources if sources is not None else [FakeKnowledgeSource()]
        self._context = context

    async def ainvoke(self, sub_input: dict[str, Any]) -> dict[str, Any]:
        return {"context": self._context, "sources": list(self._sources)}


def knowledge_hit(
    *,
    point_id: str = "p1",
    text: str = "Hiro is a local-first assistant.",
    score: float = 0.9,
    title: str = "Hiro Overview",
) -> KnowledgeSearchHit:
    """Build a fully-populated ``KnowledgeSearchHit`` for the full knowledge graph."""
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


class FakeKnowledgeService:
    """Stub for the knowledge service the full ``KnowledgeAgentGraph`` drives.

    Covers only the methods the retrieval nodes call: dense/sparse embed, vector search, and the
    by-id fetch (graphiti leg). Reranking is preference-gated (default off) so ``rerank_hits`` is
    present but unused in the characterization scenarios.
    """

    def __init__(self, *, hits: list[KnowledgeSearchHit] | None = None) -> None:
        self._hits = hits if hits is not None else [knowledge_hit()]

    async def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    async def embed_query_sparse(self, text: str) -> Any:
        return {"indices": [1], "values": [1.0]}

    async def vector_search_by_vector(self, vector: Any, sparse: Any = None, **_: Any) -> list[KnowledgeSearchHit]:
        return list(self._hits)

    async def rerank_hits(self, query: str, hits: list[Any], **_: Any) -> list[Any]:
        return list(hits)

    async def fetch_hits_by_point_ids(self, point_ids: list[str]) -> list[KnowledgeSearchHit]:
        return []


# ---------------------------------------------------------------------------
# Inbound envelope builder
# ---------------------------------------------------------------------------


def make_inbound_envelope(
    *,
    text: str | None = None,
    audio: str | None = None,
    image: str | None = None,
    sender_id: str = "user-1",
) -> dict[str, Any]:
    """Serialize a UnifiedMessage (as the graph receives it) with the requested content items."""
    items: list[ContentItem] = []
    if text is not None:
        items.append(ContentItem(content_type=CONTENT_TYPE_TEXT, body=text))
    if audio is not None:
        items.append(
            ContentItem(
                content_type=CONTENT_TYPE_AUDIO,
                body=audio,
                metadata={"mime_type": "audio/m4a", "duration_ms": 1000, "size": 4},
            )
        )
    if image is not None:
        items.append(ContentItem(content_type=CONTENT_TYPE_IMAGE, body=image))
    msg = UnifiedMessage(
        routing=MessageRouting(channel="test", direction="inbound", sender_id=sender_id),
        content=items,
    )
    return msg.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Run helper — single astream pass capturing events + final state
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    final: dict[str, Any] = field(default_factory=dict)

    def event_names(self) -> list[str]:
        return [str(e.get("event") or "") for e in self.events]

    def event_payload(self, name: str) -> dict[str, Any] | None:
        for e in self.events:
            if e.get("event") == name:
                return e.get("payload")
        return None


async def run_graph(compiled: Any, state: dict[str, Any], *, config: dict[str, Any] | None = None) -> RunResult:
    """Stream the compiled graph once, capturing custom events and the final state snapshot.

    Mirrors ``AgentManager``'s consumption (``stream_mode`` includes ``custom``); ``values`` gives
    the final state in the same pass so fakes are exercised exactly once.
    """
    result = RunResult()
    async for mode, chunk in compiled.astream(state, config or {}, stream_mode=["values", "custom"]):
        if mode == "custom":
            result.events.append(chunk)
        elif mode == "values":
            result.final = chunk
    return result


# ---------------------------------------------------------------------------
# AgentServices helpers — shared by unit + characterization tests (P4)
# ---------------------------------------------------------------------------


def make_agent_services(
    workspace_path: Any,
    *,
    ledger_sink: LedgerSink | None = None,
    preferences: Any = None,
    stt: Any = None,
    vision: Any = None,
    tts: Any = None,
    memory: Any = None,
    credentials: Any = None,
    checkpointer: Any = None,
    knowledge_subgraph: Any = None,
) -> "AgentServices":
    from hirocli.runtime.agent_graph.services import AgentServices

    return AgentServices(
        workspace_path=workspace_path,
        ledger_sink=ledger_sink or LedgerSink(workspace_path),
        preferences=preferences,
        stt=stt,
        vision=vision,
        tts=tts,
        memory=memory,
        credentials=credentials,
        checkpointer=checkpointer,
        knowledge_subgraph=knowledge_subgraph,
    )
