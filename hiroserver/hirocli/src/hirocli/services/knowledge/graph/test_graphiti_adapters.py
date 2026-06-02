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
