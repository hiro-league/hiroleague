"""Adapters that let ``graphiti-core`` drive Hiro's own model stack.

Graphiti ships its own LLM / embedder client families (OpenAI, Anthropic, …) and
does **not** speak LangChain. To keep the repo discipline — every model param
routed through a **tuning profile**, token usage flowing into the **ledger**, and
**no hardcoded model params** — we wrap Hiro's ``model_factory`` (LangChain
``BaseChatModel`` / ``Embeddings``) behind Graphiti's tiny ABCs instead of
configuring Graphiti's native clients.

Two adapters:

- :class:`GraphitiLLMClient` implements ``graphiti_core.llm_client.LLMClient``.
  Honors Graphiti's ``ModelSize`` (``medium`` → main extraction model, ``small``
  → cheap sub-step model), each backed by its own ``GraphitiModelSpec``
  (catalog model id + :class:`ModelTuning`). Structured output is produced with
  LangChain ``with_structured_output(..., include_raw=True)`` so we get both the
  validated Pydantic object (Graphiti's return contract is a plain ``dict``) and
  the raw message (for token usage → ledger).
- :class:`GraphitiEmbedderClient` implements ``graphiti_core.embedder.EmbedderClient``
  over a shared LangChain ``Embeddings`` (the same embedder the Qdrant knowledge
  layer uses — decision G8).

Both are engine-agnostic on construction: a ``model_builder`` / explicit
``Embeddings`` can be injected so tests never touch a network model.

See docs/knowledge-graphiti-pivot-design.md §5.1–5.2.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig, ModelSize
from graphiti_core.prompts.models import Message
from hiro_commons.log import Logger
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from hirocli.domain.credential_store import CredentialStore
from hirocli.domain.model_factory import build_chat_model_from_tuning
from hirocli.domain.preferences import ModelTuning

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI")


# ---------------------------------------------------------------------------
# Value objects passed across the adapter boundary.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphitiModelSpec:
    """A catalog model id + its tuning profile params — one per ``ModelSize``."""

    model_id: str
    tuning: ModelTuning


@dataclass(frozen=True)
class GraphitiLLMUsage:
    """One LLM call's token usage — handed to the optional ledger sink.

    Kept separate from any ledger import so this module stays engine-agnostic
    (same pattern as ``GraphEventSink`` in ``ingest.py``)."""

    model_id: str
    model_size: str
    input_tokens: int
    output_tokens: int


# ``on_usage`` sink: called once per LLM call with its token usage. None = no-op.
UsageSink = Callable[[GraphitiLLMUsage], None]
# Builds a LangChain chat model from a spec. Injectable so tests skip the network.
ChatModelBuilder = Callable[[GraphitiModelSpec], BaseChatModel]


def _to_langchain(messages: list[Message]) -> list[Any]:
    """Map Graphiti ``Message`` (role/content) → LangChain message objects.

    Graphiti only emits ``system`` and ``user`` roles today; ``assistant`` is
    mapped defensively, and any unknown role falls back to a human turn."""
    out: list[Any] = []
    for m in messages:
        if m.role == "system":
            out.append(SystemMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
        else:  # 'user' + defensive fallback
            out.append(HumanMessage(content=m.content))
    return out


def _usage_from_raw(raw: Any) -> tuple[int, int]:
    """Pull ``(input_tokens, output_tokens)`` off a LangChain AIMessage.

    ``usage_metadata`` is the provider-neutral shape LangChain normalizes to;
    absent (some providers/streaming) → zeros, never raise."""
    meta = getattr(raw, "usage_metadata", None)
    if not isinstance(meta, dict):
        return 0, 0
    return int(meta.get("input_tokens", 0) or 0), int(meta.get("output_tokens", 0) or 0)


# ---------------------------------------------------------------------------
# LLM client adapter
# ---------------------------------------------------------------------------


class GraphitiLLMClient(LLMClient):
    """Drive Graphiti extraction/resolution through Hiro's ``model_factory``.

    Construct with one :class:`GraphitiModelSpec` per size. ``medium`` is the
    extraction-quality model (structured-output capable — Graphiti fails on weak
    models per its README); ``small`` is the cheaper sub-step model. When ``small``
    is omitted it falls back to ``medium``.

    For production, pass ``workspace_path`` (+ optional ``workspace_id`` /
    ``credential_store``) and the adapter builds models via
    ``build_chat_model_from_tuning``. For tests, pass ``model_builder`` returning a
    stub so no provider/network is required.
    """

    def __init__(
        self,
        *,
        medium: GraphitiModelSpec,
        small: GraphitiModelSpec | None = None,
        workspace_path: Path | None = None,
        workspace_id: str | None = None,
        credential_store: CredentialStore | None = None,
        callbacks: list[Any] | None = None,
        on_usage: UsageSink | None = None,
        model_builder: ChatModelBuilder | None = None,
    ) -> None:
        self._medium_spec = medium
        self._small_spec = small or medium
        # The base class stores model names + tuning for tracing/cache-key use; the
        # actual call routing is ours. Disable Graphiti's file cache (we have the ledger).
        super().__init__(
            LLMConfig(
                model=medium.model_id,
                small_model=self._small_spec.model_id,
                temperature=medium.tuning.temperature,
                max_tokens=medium.tuning.max_tokens,
            ),
            cache=False,
        )
        self._on_usage = on_usage
        self._cache: dict[ModelSize, BaseChatModel] = {}

        if model_builder is not None:
            self._builder: ChatModelBuilder = model_builder
        else:
            if workspace_path is None:
                raise ValueError(
                    "GraphitiLLMClient: pass workspace_path (production) or model_builder (tests)."
                )
            cbs = callbacks or []

            def _default_builder(spec: GraphitiModelSpec) -> BaseChatModel:
                return build_chat_model_from_tuning(
                    spec.model_id,
                    workspace_path=workspace_path,
                    workspace_id=workspace_id,
                    tuning=spec.tuning,
                    credential_store=credential_store,
                    callbacks=cbs,
                )

            self._builder = _default_builder

    def _spec_for(self, model_size: ModelSize) -> GraphitiModelSpec:
        return self._small_spec if model_size == ModelSize.small else self._medium_spec

    def _model_for(self, model_size: ModelSize) -> BaseChatModel:
        cached = self._cache.get(model_size)
        if cached is None:
            cached = self._builder(self._spec_for(model_size))
            self._cache[model_size] = cached
        return cached

    def _report_usage(self, raw: Any, model_size: ModelSize) -> None:
        if self._on_usage is None:
            return
        in_tok, out_tok = _usage_from_raw(raw)
        try:
            self._on_usage(
                GraphitiLLMUsage(
                    model_id=self._spec_for(model_size).model_id,
                    model_size=model_size.value,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )
            )
        except Exception:
            # A ledger hiccup must never abort a graph build.
            log.warning("⚠️ graphiti.llm — usage sink failed", exc_info=True)

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        # NOTE: per-call ``max_tokens`` from Graphiti is intentionally ignored —
        # the tuning profile (admin-controlled) is the single source of truth for
        # model params (repo rule: no hardcoded/ad-hoc model params).
        model = self._model_for(model_size)
        lc_messages = _to_langchain(messages)

        try:
            if response_model is not None:
                structured = model.with_structured_output(response_model, include_raw=True)
                result = await structured.ainvoke(lc_messages)
                raw = result.get("raw") if isinstance(result, dict) else None
                parsed = result.get("parsed") if isinstance(result, dict) else None
                parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
                self._report_usage(raw, model_size)
                if parsed is None:
                    # Fail loud so the caller (Graphiti node op) surfaces the bad
                    # structured output rather than silently writing nothing.
                    raise ValueError(
                        f"structured output produced no parsed model "
                        f"(error={parsing_error!r}, model={self._spec_for(model_size).model_id})"
                    )
                return parsed.model_dump(mode="json")

            raw = await model.ainvoke(lc_messages)
            self._report_usage(raw, model_size)
            content = getattr(raw, "content", None)
            return {"content": content if isinstance(content, str) else str(content)}
        except Exception:
            # External model call — log + raise (general-coding-rule). Graphiti's
            # outer retry handles transient server errors; others fail loud.
            log.warning(
                "❌ graphiti.llm — generate failed · model=%s size=%s",
                self._spec_for(model_size).model_id,
                model_size.value,
                exc_info=True,
            )
            raise


# ---------------------------------------------------------------------------
# Embedder adapter
# ---------------------------------------------------------------------------


@runtime_checkable
class KnowledgeEmbeddingBackend(Protocol):
    """The shape of the knowledge layer's embedder (``services/knowledge/embedder.py``).

    Sync ``embed_texts`` (FastEmbed / sentence-transformers / catalog-wrapped) +
    a ``dimension``. Wrapping *this* — the exact backend Qdrant uses — is what makes
    the graph embeddings the *same* as the knowledge embeddings (decision G8)."""

    dimension: int

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


class GraphitiEmbedderClient(EmbedderClient):
    """Wrap the shared knowledge ``EmbeddingBackend`` for Graphiti node/fact embeddings.

    The backend is sync (FastEmbed/sentence-transformers); calls run in a worker
    thread so Graphiti's async pipeline never blocks the loop. ``embedding_dim``
    truncates vectors to a stable width (Graphiti stores them in Kuzu and casts
    query vectors to ``FLOAT[dim]`` — the width must match the data); it defaults to
    the backend's own ``dimension`` (G8)."""

    def __init__(
        self, backend: KnowledgeEmbeddingBackend, *, embedding_dim: int | None = None
    ) -> None:
        dim = embedding_dim if embedding_dim is not None else getattr(backend, "dimension", 0)
        if not dim or dim <= 0:
            raise ValueError(f"embedding_dim must be positive, got {dim!r}")
        self._backend = backend
        self._dim = int(dim)

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        # Graphiti calls ``create`` with a single string (one node name / fact). We
        # mirror the OpenAI adapter's contract: for list input, return the FIRST
        # embedding. Token-iterable inputs are not used by Graphiti.
        if isinstance(input_data, str):
            texts: list[str] = [input_data]
        elif isinstance(input_data, list) and input_data and isinstance(input_data[0], str):
            texts = input_data
        else:
            raise TypeError(
                f"GraphitiEmbedderClient.create: unsupported input type {type(input_data)!r}"
            )
        try:
            vecs = await asyncio.to_thread(self._backend.embed_texts, texts)
        except Exception:
            log.warning("❌ graphiti.embed — create failed", exc_info=True)
            raise
        return list(vecs[0][: self._dim]) if vecs else []

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        try:
            vecs = await asyncio.to_thread(self._backend.embed_texts, list(input_data_list))
        except Exception:
            log.warning("❌ graphiti.embed — create_batch failed", exc_info=True)
            raise
        return [list(v[: self._dim]) for v in vecs]


__all__ = [
    "ChatModelBuilder",
    "GraphitiEmbedderClient",
    "GraphitiLLMClient",
    "GraphitiLLMUsage",
    "GraphitiModelSpec",
    "UsageSink",
]
