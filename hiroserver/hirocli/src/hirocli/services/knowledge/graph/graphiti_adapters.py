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
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from graphiti_core.cross_encoder.client import CrossEncoderClient
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
    (same pattern as ``GraphEventSink`` in ``ingest.py``).

    ``operation`` is the Graphiti response-model name (e.g. ``ExtractedEntities``,
    ``EdgeDuplicate``) — the only signal the adapter has for *which* internal
    add_episode step made the call, so the ingest ledger can bucket per-call
    usage into per-operation nodes (the ingestion observability the ledger exists
    for). ``elapsed_ms`` is this single call's wall time.

    ``preview`` is a compact, human-readable summary of the *parsed result* (e.g.
    the entities extracted, the fact resolved/invalidated) so a Graph-Runs node can
    show **what the step produced**, not just call/token counts (docs §12.2.1,
    ``ledger_detail=rich``).
    """

    model_id: str
    model_size: str
    input_tokens: int
    output_tokens: int
    operation: str = ""
    elapsed_ms: float = 0.0
    preview: str = ""


# ``on_usage`` sink: called once per LLM call with its token usage. None = no-op.
UsageSink = Callable[[GraphitiLLMUsage], None]
# ``on_embed`` sink: called once per embedder call with (vector_count, elapsed_ms).
# None = no-op. Lets the ingest ledger surface an ``embed`` node per episode.
EmbedSink = Callable[[int, float], None]
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

    Primary source is ``usage_metadata`` (the provider-neutral shape LangChain
    normalizes to). Some providers/streaming responses leave it empty but still
    report counts under ``response_metadata`` (OpenAI ``token_usage`` / others
    ``usage``) — fall back to those before giving up, so token accounting doesn't
    silently read 0 on those backends. Returns ``(0, 0)`` only when no source
    carries counts; never raises."""
    meta = getattr(raw, "usage_metadata", None)
    if isinstance(meta, dict):
        in_tok = int(meta.get("input_tokens", 0) or 0)
        out_tok = int(meta.get("output_tokens", 0) or 0)
        if in_tok or out_tok:
            return in_tok, out_tok
    # Fallback: provider-native usage block on response_metadata.
    resp_meta = getattr(raw, "response_metadata", None)
    if isinstance(resp_meta, dict):
        block = resp_meta.get("token_usage") or resp_meta.get("usage")
        if isinstance(block, dict):
            in_tok = int(block.get("input_tokens") or block.get("prompt_tokens") or 0)
            out_tok = int(block.get("output_tokens") or block.get("completion_tokens") or 0)
            if in_tok or out_tok:
                return in_tok, out_tok
    return 0, 0


# Models already warned about (zero token usage). We warn ONCE per model so an
# operator notices token accounting is off for a backend, without per-call log spam.
_warned_zero_usage: set[str] = set()


def _warn_zero_usage_once(model_id: str, operation: str) -> None:
    """Surface the silent-zero case: a model that reports no usable token counts."""
    if model_id in _warned_zero_usage:
        return
    _warned_zero_usage.add(model_id)
    log.warning(
        "⚠️ graphiti.llm — no token usage reported · model=%s · op=%s · "
        "ledger tokens read 0 for this backend (usage_metadata + response_metadata empty)",
        model_id,
        operation,
    )


# Keys whose value, in a Graphiti response model, is the "payload list" worth
# previewing (entities extracted, edges, resolutions). First match wins.
_PREVIEW_LIST_KEYS = (
    "extracted_entities",
    "edges",
    "extracted_edges",
    "entity_resolutions",
    "duplicate_facts",
    "contradicted_facts",
    "extracted_nodes",
    "nodes",
    "entities",
)
# Per-item label keys, in preference order (an item is a dict; pick the first present).
_PREVIEW_ITEM_KEYS = ("name", "fact", "relation_type", "summary", "id")


def _result_preview(data: Any, *, limit: int = 4) -> str:
    """Compact, human-readable summary of a parsed Graphiti result.

    Generic on purpose — graphiti's response-model shapes vary by op/version, so we
    find the first list payload and label its items, else show a few scalar fields.
    Drives the Graph-Runs per-node content preview (docs §12.2.1). Never raises."""
    if not isinstance(data, dict):
        return ""
    try:
        for key in _PREVIEW_LIST_KEYS:
            items = data.get(key)
            if isinstance(items, list) and items:
                labels: list[str] = []
                for item in items[:limit]:
                    if isinstance(item, dict):
                        label = next(
                            (str(item[k]) for k in _PREVIEW_ITEM_KEYS if item.get(k) not in (None, "")),
                            "",
                        )
                        labels.append(label or "?")
                    else:
                        labels.append(str(item))
                more = f" (+{len(items) - limit})" if len(items) > limit else ""
                return f"{key}[{len(items)}]: " + ", ".join(labels) + more
        # No list payload — show a couple of salient scalar fields (e.g. timestamps).
        scalars = [
            f"{k}={v}" for k, v in data.items() if isinstance(v, (str, int, float, bool)) and v not in (None, "")
        ]
        return " · ".join(scalars[:limit])[:160]
    except Exception:
        return ""


def _as_int(value: Any, default: int = -1) -> int:
    """Best-effort int coercion for LLM-supplied fields; never raises."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Operation names whose result is an entity-dedup decision (docs §12.2.1, #2). Both
# map to the ``resolve_entities`` ledger node (see ingest_ledger._NODE_FOR_OPERATION).
_ENTITY_RESOLUTION_OPS = frozenset({"NodeResolutions", "NodeDuplicate"})


def _resolution_preview(operation: str, data: Any) -> str:
    """Decision-oriented preview for the dedup steps (#2 — explain *what was decided*).

    The generic ``_result_preview`` only lists names; for resolution we instead want
    new-vs-merged (entities) and new/duplicate/supersede (facts) so the
    ``resolve_entities`` / ``resolve_facts`` Graph-Runs rows say what happened to the
    freshly-extracted ("unresolved") items. Returns "" for non-dedup ops so the caller
    falls back to the generic preview. Never raises."""
    if not isinstance(data, dict):
        return ""
    try:
        if operation in _ENTITY_RESOLUTION_OPS:
            return _entity_resolution_preview(data)
        if operation == "EdgeDuplicate":
            return _edge_resolution_preview(data)
    except Exception:
        return ""
    return ""


def _entity_resolution_preview(data: dict[str, Any], *, limit: int = 4) -> str:
    """``NodeResolutions`` → "resolved N: X new, Y merged · merged: …".

    ``duplicate_candidate_id >= 0`` means the extracted entity was MERGED into an
    existing node; ``-1`` means it became a NEW node. The single-node ``NodeDuplicate``
    shape (no ``entity_resolutions`` wrapper) is handled defensively."""
    resolutions = data.get("entity_resolutions")
    if not isinstance(resolutions, list):
        resolutions = [data] if "duplicate_candidate_id" in data else []
    merged_names: list[str] = []
    new_count = 0
    merged_count = 0
    for item in resolutions:
        if not isinstance(item, dict):
            continue
        if _as_int(item.get("duplicate_candidate_id", -1), -1) >= 0:
            merged_count += 1
            name = str(item.get("name") or "").strip()
            if name:
                merged_names.append(name)
        else:
            new_count += 1
    total = new_count + merged_count
    if not total:
        return ""
    head = f"resolved {total}: {new_count} new, {merged_count} merged"
    if merged_names:
        shown = ", ".join(merged_names[:limit])
        if len(merged_names) > limit:
            shown += f" (+{len(merged_names) - limit})"
        head += f" · merged: {shown}"
    return head


def _edge_resolution_preview(data: dict[str, Any]) -> str:
    """``EdgeDuplicate`` (one fact) → new / duplicate / supersede decision.

    ``duplicate_facts`` = idxs of existing facts this one duplicates; ``contradicted_facts``
    = idxs it supersedes (invalidates). Both empty ⇒ a brand-new fact."""
    dup = data.get("duplicate_facts")
    con = data.get("contradicted_facts")
    dup_n = len(dup) if isinstance(dup, list) else 0
    con_n = len(con) if isinstance(con, list) else 0
    if dup_n and con_n:
        return f"duplicate · supersedes {con_n}"
    if dup_n:
        return "duplicate of existing fact"
    if con_n:
        return f"new · supersedes {con_n}"
    return "new fact"


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

    def _report_usage(
        self,
        raw: Any,
        model_size: ModelSize,
        *,
        operation: str,
        elapsed_ms: float,
        preview: str = "",
    ) -> None:
        if self._on_usage is None:
            return
        in_tok, out_tok = _usage_from_raw(raw)
        if not in_tok and not out_tok:
            _warn_zero_usage_once(self._spec_for(model_size).model_id, operation)
        try:
            self._on_usage(
                GraphitiLLMUsage(
                    model_id=self._spec_for(model_size).model_id,
                    model_size=model_size.value,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    operation=operation,
                    elapsed_ms=elapsed_ms,
                    preview=preview,
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
        # The response-model name is the only handle on *which* internal add_episode
        # step this call serves (extract/dedupe/dates/…); the ingest ledger buckets by it.
        operation = response_model.__name__ if response_model is not None else "completion"
        started = time.perf_counter()

        try:
            if response_model is not None:
                structured = model.with_structured_output(response_model, include_raw=True)
                result = await structured.ainvoke(lc_messages)
                raw = result.get("raw") if isinstance(result, dict) else None
                parsed = result.get("parsed") if isinstance(result, dict) else None
                parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
                parsed_dump = parsed.model_dump(mode="json") if parsed is not None else None
                self._report_usage(
                    raw,
                    model_size,
                    operation=operation,
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    # What this step produced — for the Graph-Runs node preview. Dedup
                    # ops get a decision-oriented preview (new/merged/supersede, #2);
                    # everything else falls back to the generic name-list preview.
                    preview=_resolution_preview(operation, parsed_dump)
                    or _result_preview(parsed_dump),
                )
                if parsed is None:
                    # Fail loud so the caller (Graphiti node op) surfaces the bad
                    # structured output rather than silently writing nothing.
                    raise ValueError(
                        f"structured output produced no parsed model "
                        f"(error={parsing_error!r}, model={self._spec_for(model_size).model_id})"
                    )
                return parsed_dump

            raw = await model.ainvoke(lc_messages)
            self._report_usage(
                raw,
                model_size,
                operation=operation,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
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
        self,
        backend: KnowledgeEmbeddingBackend,
        *,
        embedding_dim: int | None = None,
        on_embed: "EmbedSink | None" = None,
    ) -> None:
        dim = embedding_dim if embedding_dim is not None else getattr(backend, "dimension", 0)
        if not dim or dim <= 0:
            raise ValueError(f"embedding_dim must be positive, got {dim!r}")
        self._backend = backend
        self._dim = int(dim)
        # Reports (vector_count, elapsed_ms) per call so the ingest ledger can show
        # an ``embed`` node per episode. Fired on the event loop (after the worker
        # thread returns), so the ledger collector is only touched on one thread.
        self._on_embed = on_embed

    def _report_embed(self, count: int, elapsed_ms: float) -> None:
        if self._on_embed is None:
            return
        try:
            self._on_embed(count, elapsed_ms)
        except Exception:
            # A ledger hiccup must never abort a graph build.
            log.warning("⚠️ graphiti.embed — embed sink failed", exc_info=True)

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
        started = time.perf_counter()
        try:
            vecs = await asyncio.to_thread(self._backend.embed_texts, texts)
        except Exception:
            log.warning("❌ graphiti.embed — create failed", exc_info=True)
            raise
        self._report_embed(len(vecs), (time.perf_counter() - started) * 1000.0)
        return list(vecs[0][: self._dim]) if vecs else []

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        try:
            vecs = await asyncio.to_thread(self._backend.embed_texts, list(input_data_list))
        except Exception:
            log.warning("❌ graphiti.embed — create_batch failed", exc_info=True)
            raise
        self._report_embed(len(vecs), (time.perf_counter() - started) * 1000.0)
        return [list(v[: self._dim]) for v in vecs]


# ---------------------------------------------------------------------------
# Cross-encoder (reranker) adapter
# ---------------------------------------------------------------------------


class HiroRerankerCrossEncoder(CrossEncoderClient):
    """Wrap Hiro's knowledge reranker as Graphiti's ``CrossEncoderClient``.

    Graphiti's default ``cross_encoder`` is ``OpenAIRerankerClient`` (forces an OpenAI
    key). We instead wrap the SAME ``BaseDocumentCompressor`` the flat Qdrant path uses
    (cloud Cohere/Voyage OR local FlashRank/FastEmbed/sentence-transformers, resolved by
    ``resolve_reranker``) so the ``cross_encoder`` search recipe reranks fact edges with
    a real model — no extra provider, one model to manage (decision G8).

    ``compress_documents`` is synchronous (model inference / network), so we run it in a
    worker thread to keep Graphiti's async search off the event loop. The compressor is
    built with a large ``top_n`` (it scores ALL candidate facts; Graphiti then applies
    its own ``SearchConfig.limit``), so we must NOT pre-trim here. Graphiti only sorts by
    the returned score, so raw ``relevance_score`` is passed through (no normalization).
    """

    def __init__(self, compressor: Any) -> None:
        self._compressor = compressor

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        if not passages:
            return []
        from langchain_core.documents import Document

        docs = [Document(page_content=p, metadata={"_i": i}) for i, p in enumerate(passages)]
        try:
            ranked = await asyncio.to_thread(self._compressor.compress_documents, docs, query)
        except Exception:
            # A reranker failure must not abort the search — fall back to input order
            # (the same defensive behavior as the no-op passthrough).
            log.warning("⚠️ graphiti.rerank — cross-encoder failed; using input order", exc_info=True)
            n = len(passages)
            return [(p, float(n - i)) for i, p in enumerate(passages)]
        out: list[tuple[str, float]] = []
        for doc in ranked:
            score = doc.metadata.get("relevance_score")
            out.append((doc.page_content, float(score) if score is not None else 0.0))
        return out


__all__ = [
    "ChatModelBuilder",
    "GraphitiEmbedderClient",
    "GraphitiLLMClient",
    "GraphitiLLMUsage",
    "GraphitiModelSpec",
    "HiroRerankerCrossEncoder",
    "UsageSink",
]
