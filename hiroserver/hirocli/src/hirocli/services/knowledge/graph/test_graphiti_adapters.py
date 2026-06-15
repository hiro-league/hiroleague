"""Unit tests for the Graphiti LLM + embedder adapters.

No network / provider: chat models and embeddings are stubbed via the injectable
``model_builder`` and a duck-typed embeddings object. Verifies model-size routing,
the structured-output → dict contract, token-usage reporting, and embedding
truncation to the configured dimension.
"""

from __future__ import annotations

import pytest
from graphiti_core.llm_client.config import ModelSize
from graphiti_core.prompts.models import Message
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from hirocli.domain.preferences import ModelTuning
from hirocli.services.knowledge.graph.graphiti_adapters import (
    GraphitiEmbedderClient,
    GraphitiLLMClient,
    GraphitiModelSpec,
    HiroRerankerCrossEncoder,
)


class _Foo(BaseModel):
    name: str


class _FakeStructured:
    def __init__(self, parsed: object, raw: object, parsing_error: object = None) -> None:
        self._parsed = parsed
        self._raw = raw
        self._parsing_error = parsing_error

    async def ainvoke(self, _messages: object) -> dict[str, object]:
        return {"raw": self._raw, "parsed": self._parsed, "parsing_error": self._parsing_error}


class _FakeChat:
    """Duck-typed stand-in for a LangChain BaseChatModel."""

    def __init__(
        self, *, parsed: object | None, content: str = "plain", usage: dict | None = None
    ) -> None:
        self._parsed = parsed
        self._content = content
        self._usage = usage or {"input_tokens": 3, "output_tokens": 5}
        self.structured_calls: list[tuple[type, bool]] = []

    def with_structured_output(self, response_model: type, include_raw: bool = False):
        self.structured_calls.append((response_model, include_raw))
        raw = AIMessage(content="{}", usage_metadata={**self._usage, "total_tokens": 8})
        return _FakeStructured(self._parsed, raw)

    async def ainvoke(self, _messages: object) -> AIMessage:
        return AIMessage(content=self._content, usage_metadata={**self._usage, "total_tokens": 8})


def _tuning() -> ModelTuning:
    return ModelTuning(temperature=0.0, max_tokens=4096, thinking="off")


def _msgs() -> list[Message]:
    return [Message(role="system", content="sys"), Message(role="user", content="hi")]


def _client_with(fakes: dict[str, _FakeChat], usages: list) -> GraphitiLLMClient:
    medium = GraphitiModelSpec("openai:gpt-medium", _tuning())
    small = GraphitiModelSpec("openai:gpt-small", _tuning())
    return GraphitiLLMClient(
        medium=medium,
        small=small,
        model_builder=lambda spec: fakes[spec.model_id],
        on_usage=usages.append,
    )


@pytest.mark.asyncio
async def test_structured_output_returns_dict_and_reports_usage() -> None:
    usages: list = []
    fakes = {
        "openai:gpt-medium": _FakeChat(parsed=_Foo(name="m")),
        "openai:gpt-small": _FakeChat(parsed=_Foo(name="s")),
    }
    client = _client_with(fakes, usages)

    out = await client._generate_response(_msgs(), response_model=_Foo, model_size=ModelSize.medium)

    assert out == {"name": "m"}
    assert len(usages) == 1
    assert usages[0].model_id == "openai:gpt-medium"
    assert usages[0].model_size == "medium"
    assert usages[0].input_tokens == 3
    assert usages[0].output_tokens == 5
    # include_raw must be requested so we can read usage off the raw message.
    assert fakes["openai:gpt-medium"].structured_calls == [(_Foo, True)]


class _FakeDeepSeek:
    """DeepSeek stub — class name is overridden to ``ChatDeepSeek`` below so the compat
    wrapper (which keys on the class name) treats it as the real client. Records the
    ``method`` kwarg passed to ``with_structured_output`` so the json_mode fallback is testable."""

    def __init__(self, parsed: object, *, thinking_enabled: bool) -> None:
        self._parsed = parsed
        self.extra_body = {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
        self.structured_calls: list[dict] = []

    def with_structured_output(self, response_model: type, include_raw: bool = False, **kwargs):
        self.structured_calls.append(
            {"response_model": response_model, "include_raw": include_raw, **kwargs}
        )
        raw = AIMessage(content="{}", usage_metadata={"input_tokens": 3, "output_tokens": 5, "total_tokens": 8})
        return _FakeStructured(self._parsed, raw)

    async def ainvoke(self, _messages: object) -> AIMessage:
        return AIMessage(content="plain", usage_metadata={"input_tokens": 3, "output_tokens": 5, "total_tokens": 8})


# The compat wrapper checks ``__class__.__name__ == "ChatDeepSeek"``; rename so the stub matches.
_FakeDeepSeek.__name__ = "ChatDeepSeek"


@pytest.mark.asyncio
async def test_deepseek_thinking_uses_json_mode_structured_output() -> None:
    """DeepSeek thinking mode 400s on the forced tool_choice, so the adapter must route
    structured output through method=json_mode (graphiti injects the JSON schema into the prompt)."""
    model = _FakeDeepSeek(_Foo(name="m"), thinking_enabled=True)
    client = GraphitiLLMClient(
        medium=GraphitiModelSpec("deepseek:deepseek-v4-flash", _tuning()),
        model_builder=lambda spec: model,
    )

    out = await client._generate_response(_msgs(), response_model=_Foo, model_size=ModelSize.medium)

    assert out == {"name": "m"}
    assert model.structured_calls[0]["method"] == "json_mode"
    assert model.structured_calls[0]["include_raw"] is True


@pytest.mark.asyncio
async def test_deepseek_nonthinking_keeps_default_method() -> None:
    """Non-thinking DeepSeek supports the default function_calling method — no json_mode override."""
    model = _FakeDeepSeek(_Foo(name="m"), thinking_enabled=False)
    client = GraphitiLLMClient(
        medium=GraphitiModelSpec("deepseek:deepseek-v4-flash", _tuning()),
        model_builder=lambda spec: model,
    )

    await client._generate_response(_msgs(), response_model=_Foo, model_size=ModelSize.medium)

    assert "method" not in model.structured_calls[0]


@pytest.mark.asyncio
async def test_model_size_routes_to_small_model() -> None:
    usages: list = []
    fakes = {
        "openai:gpt-medium": _FakeChat(parsed=_Foo(name="m")),
        "openai:gpt-small": _FakeChat(parsed=_Foo(name="s")),
    }
    client = _client_with(fakes, usages)

    out = await client._generate_response(_msgs(), response_model=_Foo, model_size=ModelSize.small)

    assert out == {"name": "s"}
    assert usages[0].model_id == "openai:gpt-small"
    assert usages[0].model_size == "small"


@pytest.mark.asyncio
async def test_parsed_none_raises() -> None:
    usages: list = []
    fakes = {
        "openai:gpt-medium": _FakeChat(parsed=None),
        "openai:gpt-small": _FakeChat(parsed=None),
    }
    client = _client_with(fakes, usages)

    with pytest.raises(ValueError, match="no parsed model"):
        await client._generate_response(_msgs(), response_model=_Foo, model_size=ModelSize.medium)


@pytest.mark.asyncio
async def test_unstructured_returns_content() -> None:
    usages: list = []
    fakes = {
        "openai:gpt-medium": _FakeChat(parsed=None, content="hello world"),
        "openai:gpt-small": _FakeChat(parsed=None),
    }
    client = _client_with(fakes, usages)

    out = await client._generate_response(_msgs(), response_model=None, model_size=ModelSize.medium)

    assert out == {"content": "hello world"}
    assert usages[0].output_tokens == 5


@pytest.mark.asyncio
async def test_model_is_built_once_and_cached() -> None:
    builds: list[str] = []
    fake = _FakeChat(parsed=_Foo(name="m"))

    def builder(spec: GraphitiModelSpec) -> _FakeChat:
        builds.append(spec.model_id)
        return fake

    client = GraphitiLLMClient(
        medium=GraphitiModelSpec("openai:gpt-medium", _tuning()),
        model_builder=builder,
    )
    await client._generate_response(_msgs(), response_model=_Foo)
    await client._generate_response(_msgs(), response_model=_Foo)

    assert builds == ["openai:gpt-medium"]  # built once, reused


def test_llm_requires_workspace_or_builder() -> None:
    with pytest.raises(ValueError, match="workspace_path"):
        GraphitiLLMClient(medium=GraphitiModelSpec("openai:gpt-medium", _tuning()))


# ---- embedder ----


class _FakeBackend:
    """Stand-in for the knowledge EmbeddingBackend (sync embed_texts + dimension)."""

    def __init__(self, dimension: int = 4) -> None:
        self.dimension = dimension

    def embed_texts(self, texts) -> list[list[float]]:
        # First row is distinct so single/str input is identifiable; rest are indexed.
        return [[0.1, 0.2, 0.3, 0.4] if i == 0 else [float(i)] * 4 for i, _ in enumerate(texts)]


@pytest.mark.asyncio
async def test_embedder_create_truncates_to_dim() -> None:
    emb = GraphitiEmbedderClient(_FakeBackend(), embedding_dim=3)
    vec = await emb.create("hello")
    assert vec == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_embedder_create_batch() -> None:
    emb = GraphitiEmbedderClient(_FakeBackend(), embedding_dim=2)
    vecs = await emb.create_batch(["a", "b", "c"])
    assert vecs == [[0.1, 0.2], [1.0, 1.0], [2.0, 2.0]]


@pytest.mark.asyncio
async def test_embedder_list_input_returns_first() -> None:
    emb = GraphitiEmbedderClient(_FakeBackend(), embedding_dim=4)
    vec = await emb.create(["x", "y"])
    assert vec == [0.1, 0.2, 0.3, 0.4]


@pytest.mark.asyncio
async def test_embedder_dim_defaults_to_backend_dimension() -> None:
    emb = GraphitiEmbedderClient(_FakeBackend(dimension=2))
    vec = await emb.create("hello")
    assert vec == [0.1, 0.2]


def test_embedder_rejects_bad_dim() -> None:
    with pytest.raises(ValueError, match="embedding_dim"):
        GraphitiEmbedderClient(_FakeBackend(dimension=0))


# ---------------------------------------------------------------------------
# Cross-encoder (reranker) adapter
# ---------------------------------------------------------------------------


class _FakeCompressor:
    """Stand-in for a BaseDocumentCompressor: reorders docs by a fixed score map."""

    def __init__(self, scores: dict[str, float]) -> None:
        self._scores = scores

    def compress_documents(self, documents, query, callbacks=None):
        from langchain_core.documents import Document

        ranked = sorted(documents, key=lambda d: self._scores.get(d.page_content, 0.0), reverse=True)
        return [
            Document(
                page_content=d.page_content,
                metadata={**d.metadata, "relevance_score": self._scores.get(d.page_content, 0.0)},
            )
            for d in ranked
        ]


@pytest.mark.asyncio
async def test_cross_encoder_reranks_by_compressor_score() -> None:
    xenc = HiroRerankerCrossEncoder(_FakeCompressor({"a": 0.1, "b": 0.9, "c": 0.5}))
    ranked = await xenc.rank("q", ["a", "b", "c"])
    assert [p for p, _ in ranked] == ["b", "c", "a"]  # sorted by score desc
    assert ranked[0] == ("b", 0.9)


@pytest.mark.asyncio
async def test_cross_encoder_empty_passages_noop() -> None:
    xenc = HiroRerankerCrossEncoder(_FakeCompressor({}))
    assert await xenc.rank("q", []) == []


@pytest.mark.asyncio
async def test_cross_encoder_falls_back_to_input_order_on_error() -> None:
    class _Boom:
        def compress_documents(self, *a, **k):
            raise RuntimeError("model down")

    xenc = HiroRerankerCrossEncoder(_Boom())
    ranked = await xenc.rank("q", ["x", "y", "z"])
    # Input order preserved (defensive, never aborts the search).
    assert [p for p, _ in ranked] == ["x", "y", "z"]
