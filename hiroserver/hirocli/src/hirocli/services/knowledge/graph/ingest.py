"""L3 graph ingestion service — orchestrates extract → resolve → write per chunk.

Wires the per-chunk pipeline:

  chunk_text  →  extractor (1 LLM call)  →  resolver (link-or-create per mention)
              →  edge upserts (per relation)  →  ledger reporting

Implements the **F7 write-gate** (research §4.2.3, mem0 #4573 bleed fix): only
content with an allowed ``source_role`` is ingested. Retrieved-knowledge and
system content are rejected before any extraction call — by construction the
graph cannot become a stale echo of its own retrieval output.

The service is engine-agnostic on the model side: pass it an already-resolved
``BaseChatModel`` (the Tool does this via ``model_factory``). Keeping model
construction out of this module means tests don't need a network model.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger
from hirocli.runtime.agent_graph.ledger import LedgerSink
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..constants import (
    KNOWLEDGE_GRAPH_EDGE_UPSERTED,
    KNOWLEDGE_GRAPH_INGEST_PROGRESS,
    KNOWLEDGE_GRAPH_NODE_UPSERTED,
)
from .extractor import ExtractionResult, ExtractionUsage, extract_from_chunk
from .ingest_ledger import (
    finalize_graph_ingest_run,
    format_resolution_preview,
    knowledge_graph_ingest_ledger,
    ledger_step,
)
from .ontology import DisambiguationDecision, ExtractedEntity, ExtractedRelation
from .resolver import GraphResolver, LLMDisambiguator, ResolutionResult
from .serialize import edge_to_dto, node_to_dto
from .store import GraphEdge, GraphNode, GraphStore

log = Logger.get("SVC.KNOWLEDGE.GRAPH.INGEST")


# A sink for live graph-viz events: ``(event_type, payload) -> None``. The HTTP
# layer wires this to the Domain Event Bus so the admin Graph tab pops new
# nodes/edges in real time; tests and CLI callers leave it None (no-op). Kept as
# a plain callable so this module never imports the bus (engine-agnostic).
GraphEventSink = Callable[[str, dict[str, Any]], None]


# F7 — Source-role allow-list. The bleed bug (mem0 #4573 — one hallucination
# multiplied to 808 stored memories) happens when retrieved/system content is
# re-extracted. Defining the allow-list (not deny-list) means a future code
# path that forgets to tag its role gets REJECTED by default. Safer than relying
# on a deny-list. Add new roles here explicitly as ingest sources are wired up.
ALLOWED_SOURCE_ROLES: frozenset[str] = frozenset({"user_document"})

# Rejected — listed for documentation; ANY role not in ALLOWED is rejected.
REJECTED_SOURCE_ROLES: frozenset[str] = frozenset(
    {"retrieved_knowledge", "assistant_output", "system", "system_prompt"}
)

# Larger preview budget for ingest step rows so entity types + relation/edge triples fit (the
# default ledger preview caps at 280). Matches the retrieval-side knowledge preview budget.
_INGEST_PREVIEW_MAX = 600


@dataclass(frozen=True)
class ChunkInput:
    """One chunk to be graph-ingested. Carries the same ``chunk_id`` Qdrant uses
    (``KnowledgeSearchHit.point_id``) so graph→Qdrant lookups are a direct id join."""

    chunk_id: str
    document_id: str
    text: str


@dataclass
class GraphIngestStats:
    """Per-job counters surfaced to the ledger and the tool result.

    Branch counts answer "is the deterministic-first ladder actually saving LLM
    calls?" — a noisy graph with high ``llm_link`` proportion is a signal that
    extraction quality or thresholds need tuning."""

    chunks_received: int = 0
    chunks_processed: int = 0       # passed the write-gate
    chunks_rejected: int = 0        # failed the write-gate
    chunks_extraction_failed: int = 0
    entities_created: int = 0
    entities_linked_exact: int = 0
    entities_linked_fuzzy: int = 0
    entities_linked_llm: int = 0
    edges_written: int = 0
    edges_dropped_orphan: int = 0   # rel referenced an entity not in the chunk
    llm_extraction_calls: int = 0
    llm_disambiguation_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    rejected_roles: list[str] = field(default_factory=list)

    def record_resolution(self, result: ResolutionResult) -> None:
        if result.branch == "exact_link":
            self.entities_linked_exact += 1
        elif result.branch == "fuzzy_link":
            self.entities_linked_fuzzy += 1
        elif result.branch == "llm_link":
            self.entities_linked_llm += 1
        elif result.branch == "created":
            self.entities_created += 1
        if result.llm_call:
            self.llm_disambiguation_calls += 1

    def record_usage(self, usage: ExtractionUsage) -> None:
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunks_received": self.chunks_received,
            "chunks_processed": self.chunks_processed,
            "chunks_rejected": self.chunks_rejected,
            "chunks_extraction_failed": self.chunks_extraction_failed,
            "entities_created": self.entities_created,
            "entities_linked_exact": self.entities_linked_exact,
            "entities_linked_fuzzy": self.entities_linked_fuzzy,
            "entities_linked_llm": self.entities_linked_llm,
            "edges_written": self.edges_written,
            "edges_dropped_orphan": self.edges_dropped_orphan,
            "llm_extraction_calls": self.llm_extraction_calls,
            "llm_disambiguation_calls": self.llm_disambiguation_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "rejected_roles": list(self.rejected_roles),
        }


# ---------------------------------------------------------------------------
# LLM disambiguator factory — separate function so the service stays testable
# (tests pass their own stub disambiguator directly to GraphResolver).
# ---------------------------------------------------------------------------


_DISAMBIG_PROMPT = """You decide whether a newly-extracted entity mention refers to one of the
existing nodes in a personal knowledge graph.

Rules:
- Two mentions are the SAME entity only if they refer to the same real-world thing.
- Same name + different real-world thing → NOT a match (e.g. two people named Ahmed,
  Java the language vs Java the island).
- Aliases / abbreviations / possessive variants of the same thing ARE a match
  (NYC = New York City; "Marco's car" = "Marco's vehicle").
- A descriptive label that clearly refers to a named candidate IS a match
  (e.g. "my colleague" → the named coworker, when context makes it unambiguous).

Return the candidate id of the matching node, or null if none of the candidates
is the same entity (a new node will be created).
""".strip()


def make_llm_disambiguator(model: BaseChatModel) -> LLMDisambiguator:
    """Build an :class:`LLMDisambiguator` closure backed by a chat model.

    The closure embeds the mention + candidates into a prompt and parses a
    :class:`DisambiguationDecision`. Failures degrade to ``None`` (the resolver
    treats that as "no match" and creates a new node).
    """
    structured = model.with_structured_output(DisambiguationDecision, include_raw=True)

    async def _disambiguate(
        mention: ExtractedEntity, candidates: list[GraphNode]
    ) -> str | None:
        if not candidates:
            return None
        candidate_block = "\n".join(
            f"- id={c.id} · name={c.name!r} · type={c.type} · "
            f"aliases={list(c.aliases)} · seen_in_chunks={len(c.chunk_ids)}"
            for c in candidates
        )
        human = (
            f"Mention: name={mention.name!r}, type={mention.type}\n"
            f"Existing candidates:\n{candidate_block}\n\n"
            "Pick the candidate id this mention refers to, or null."
        )
        try:
            result = await structured.ainvoke(
                [SystemMessage(content=_DISAMBIG_PROMPT), HumanMessage(content=human)]
            )
        except Exception as exc:
            log.warning(
                "⚠️ graph.disambiguate — call failed · returning None",
                error=str(exc)[:200],
                exc_info=True,
            )
            return None
        parsed = result.get("parsed") if isinstance(result, dict) else None
        if not isinstance(parsed, DisambiguationDecision):
            return None
        return parsed.matched_candidate_id or None

    return _disambiguate


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _edge_id(source_id: str, target_id: str, rel_type: str) -> str:
    """Deterministic edge id — same (src, rel, tgt) re-ingest produces the same
    id, so MERGE-on-id correctly updates instead of duplicating (LightRAG §2.5
    content-hash join pattern, applied to edges)."""
    digest = hashlib.md5(f"{source_id}|{rel_type}|{target_id}".encode()).hexdigest()
    return f"r_{digest[:16]}"


class GraphIngestService:
    """Orchestrator: chunks → graph mutations, with F7 write-gate + ledger stats.

    The service is **stateless** between calls — each ``ingest_chunks`` call is
    self-contained. The :class:`GraphStore` provides the persistence; the
    extractor + resolver provide the per-chunk work. Threading the model in
    through ``ingest_chunks`` (rather than storing it on the instance) keeps the
    service indifferent to model lifecycle — Tools that span multiple jobs can
    construct one model per job from the tuning profile and pass it in.

    **Observability:** when ``workspace_path`` is provided, a :class:`LedgerSink`
    is created and per-chunk rows (extract / resolve / write) plus an aggregate
    ``@run`` row are written to Graph Runs — same surface the retrieval side uses
    via ``knowledge_answer_ledger``. When omitted (tests), the ledger calls are
    no-ops and the service behaves as before.
    """

    def __init__(
        self,
        store: GraphStore,
        *,
        workspace_path: Path | None = None,
        event_sink: GraphEventSink | None = None,
    ) -> None:
        self._store = store
        # Sink is workspace-scoped (matches BaseAgentGraph). Optional so the
        # service stays usable without a workspace path (kept for unit tests
        # that don't care about ledger output).
        self._sink: LedgerSink | None = (
            LedgerSink(workspace_path) if workspace_path is not None else None
        )
        # Optional live-viz event sink (Graph tab). None in tests/CLI → no emits.
        self._event_sink = event_sink

    async def ingest_chunks(
        self,
        chunks: Sequence[ChunkInput] | Iterable[ChunkInput],
        *,
        source_role: str,
        model: BaseChatModel | None,
        model_id: str = "",
        disambiguator: LLMDisambiguator | None = None,
        document_id: str = "",
        document_title: str = "",
    ) -> GraphIngestStats:
        """Run the per-chunk pipeline. Returns aggregate stats.

        - ``source_role`` is the **F7 write-gate** key. Roles outside
          ``ALLOWED_SOURCE_ROLES`` are rejected before any model call — no
          extraction, no graph mutation, just a counter.
        - ``model`` is the structured-output chat model used for extraction.
          Must be provided unless ``chunks`` is empty.
        - ``disambiguator`` is optional. When None, the resolver falls back to
          "create new" on ambiguity (safe default; less precise).
        - ``document_id`` / ``document_title`` populate the aggregate ledger
          ``@run`` row's input preview so a tail-the-log workflow can identify
          which document each ingest call belonged to.
        """
        stats = GraphIngestStats()
        chunk_list = list(chunks)
        stats.chunks_received = len(chunk_list)

        async with knowledge_graph_ingest_ledger(
            sink=self._sink, document_id=document_id
        ) as ledger_run:
            terminal_status = "completed"
            terminal_error = ""
            try:
                # F7 write-gate (allow-list). One log + bail rather than per-chunk noise.
                if source_role not in ALLOWED_SOURCE_ROLES:
                    stats.chunks_rejected = len(chunk_list)
                    stats.rejected_roles.append(source_role)
                    log.warning(
                        "❌ graph.ingest — REJECTED %d chunk(s) · source_role=%s not in allow-list",
                        len(chunk_list),
                        source_role,
                        allowed=sorted(ALLOWED_SOURCE_ROLES),
                    )
                    return stats

                if not chunk_list:
                    return stats

                if model is None:
                    raise ValueError(
                        "GraphIngestService.ingest_chunks: model is required when chunks is non-empty"
                    )

                resolver = GraphResolver(self._store, disambiguator=disambiguator)

                total = len(chunk_list)
                for index, chunk in enumerate(chunk_list):
                    await self._ingest_one_chunk(
                        chunk, model=model, model_id=model_id, resolver=resolver, stats=stats
                    )
                    # Live-viz progress (no-op when no event sink wired).
                    self._emit_progress(
                        document_id=chunk.document_id, index=index + 1, total=total
                    )

                log.info(
                    "✅ graph.ingest — done · chunks=%d/%d · created=%d linked=%d edges=%d "
                    "llm_extract=%d llm_disambig=%d in_tok=%d out_tok=%d",
                    stats.chunks_processed,
                    stats.chunks_received,
                    stats.entities_created,
                    stats.entities_linked_exact
                        + stats.entities_linked_fuzzy
                        + stats.entities_linked_llm,
                    stats.edges_written,
                    stats.llm_extraction_calls,
                    stats.llm_disambiguation_calls,
                    stats.total_input_tokens,
                    stats.total_output_tokens,
                )
                return stats
            except Exception as exc:
                terminal_status = "failed"
                terminal_error = type(exc).__name__
                raise
            finally:
                # Aggregate row gets written even on failure / rejection so the
                # admin always has a single row per ingest call to find/group on.
                if ledger_run.accumulator is not None:
                    finalize_graph_ingest_run(
                        ledger_run.accumulator,
                        document_id=document_id,
                        document_title=document_title,
                        source_role=source_role,
                        chunks_count=stats.chunks_received,
                        stats=stats,
                        status=terminal_status,
                        error_code=terminal_error,
                    )

    async def _ingest_one_chunk(
        self,
        chunk: ChunkInput,
        *,
        model: BaseChatModel,
        model_id: str = "",
        resolver: GraphResolver,
        stats: GraphIngestStats,
    ) -> None:
        # Three ledger rows per chunk — extract / resolve / write — so each step's
        # cost + decisions are visible separately in Graph Runs. Each ``ledger_step``
        # is a no-op when ``self._sink`` is None (tests that don't set a workspace).
        chunk_label = chunk.chunk_id[:10] or "?"

        # ---- extract ---------------------------------------------------------
        # captures: ``usage`` exposes token columns; ``decision`` exposes
        # decision_kind/decision_detail. ``to_row()`` blanks both groups by default.
        async with ledger_step(self._sink, "extract", captures={"usage", "decision"}) as entry:
            if entry is not None:
                entry.set_input_preview(
                    f"chunk: {chunk_label} (doc: {chunk.document_id[:12]}) · "
                    f"text: {chunk.text[:140].strip()}"
                )
            stats.llm_extraction_calls += 1
            extraction_result: ExtractionResult = await extract_from_chunk(
                chunk.text, model=model
            )
            stats.record_usage(extraction_result.usage)
            if extraction_result.usage.parsing_error:
                stats.chunks_extraction_failed += 1
            ext = extraction_result.extraction
            if entry is not None:
                usage = extraction_result.usage
                # Record the extraction model + tokens so the row shows WHICH model ran and
                # ``_with_cost`` can price it (was tokens-only → model/cost columns were blank).
                provider = model_id.split(":", 1)[0] if ":" in model_id else ""
                entry.add_usage(
                    provider=provider,
                    model=model_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cached_input_tokens=usage.cached_input_tokens,
                    reasoning_tokens=usage.reasoning_tokens,
                )
                if usage.parsing_error:
                    entry.fail(
                        "extraction_failed",
                        message=str(usage.parsing_error)[:200],
                    )
                else:
                    entry.set_decision(
                        "extracted",
                        f"e{len(ext.entities)}_r{len(ext.relations)}",
                    )
                    # Show the typed entities + the actual relation triples (node types, relation
                    # types, and proposed links) — not just counts.
                    ents = ", ".join(f"{e.name}({e.type})" for e in ext.entities[:6])
                    ent_more = f" (+{len(ext.entities) - 6})" if len(ext.entities) > 6 else ""
                    rels = " | ".join(
                        f"{r.source_name}—{r.rel_type}→{r.target_name}" for r in ext.relations[:5]
                    )
                    rel_more = f" (+{len(ext.relations) - 5})" if len(ext.relations) > 5 else ""
                    entry.set_output_preview(
                        f"entities[{len(ext.entities)}]: {ents}{ent_more}"
                        f" · relations[{len(ext.relations)}]: {rels}{rel_more}",
                        max_len=_INGEST_PREVIEW_MAX,
                    )

        if not ext.entities and not ext.relations:
            # Nothing to write — still count the chunk as processed (LLM was paid).
            stats.chunks_processed += 1
            return

        # ---- resolve ---------------------------------------------------------
        name_to_id: dict[str, str] = {}
        resolutions: list[tuple[str, str, str]] = []
        branch_counts: dict[str, int] = {}
        llm_calls_before = stats.llm_disambiguation_calls
        async with ledger_step(self._sink, "resolve", captures={"decision"}) as entry:
            if entry is not None:
                names = ", ".join(e.name for e in ext.entities[:6])
                overflow = f" (+{len(ext.entities) - 6} more)" if len(ext.entities) > 6 else ""
                entry.set_input_preview(f"mentions[{len(ext.entities)}]: {names}{overflow}")
            for mention in ext.entities:
                result = await resolver.link_or_create(
                    mention, chunk_id=chunk.chunk_id, document_id=chunk.document_id
                )
                stats.record_resolution(result)
                name_to_id[mention.name] = result.node_id
                resolutions.append((mention.name, result.branch, result.node_id))
                branch_counts[result.branch] = branch_counts.get(result.branch, 0) + 1
                # Live-viz: pop the node (is_new) or pulse it (provenance merge).
                self._emit_node(
                    result.node_id,
                    is_new=result.branch == "created",
                    document_id=chunk.document_id,
                )
            if entry is not None:
                llm_calls_made = stats.llm_disambiguation_calls - llm_calls_before
                summary = "+".join(
                    f"{name}={count}" for name, count in sorted(branch_counts.items())
                ) or "none"
                entry.set_decision(
                    "resolved",
                    f"{summary}+disambig{llm_calls_made}",
                )
                entry.set_output_preview(format_resolution_preview(resolutions))

        # ---- write -----------------------------------------------------------
        edges_written_this_chunk = 0
        edges_dropped_this_chunk = 0
        written_edges: list[str] = []
        async with ledger_step(self._sink, "write", captures={"decision"}) as entry:
            if entry is not None:
                entry.set_input_preview(
                    f"nodes={len(name_to_id)} · pending_relations={len(ext.relations)}"
                )
            # Orphan rels (endpoint missing from this chunk's entity list) are
            # dropped — the extractor already cleans, but defensive here.
            for rel in ext.relations:
                src_id = name_to_id.get(rel.source_name)
                tgt_id = name_to_id.get(rel.target_name)
                if not src_id or not tgt_id or src_id == tgt_id:
                    stats.edges_dropped_orphan += 1
                    edges_dropped_this_chunk += 1
                    continue
                edge = _build_edge(src_id, tgt_id, rel, chunk)
                # Pre-check existence only when emitting events, so we can tell a
                # brand-new edge from a re-asserted one (pop vs pulse).
                edge_existed = (
                    self._store.get_edge(edge.id) is not None
                    if self._event_sink is not None
                    else False
                )
                self._store.upsert_edge(edge)
                stats.edges_written += 1
                edges_written_this_chunk += 1
                written_edges.append(f"{rel.source_name}—{rel.rel_type}→{rel.target_name}")
                self._emit_edge(
                    edge.id, is_new=not edge_existed, document_id=chunk.document_id
                )
            if entry is not None:
                entry.set_decision(
                    "wrote",
                    f"n{len(name_to_id)}_e{edges_written_this_chunk}"
                    + (f"_drop{edges_dropped_this_chunk}" if edges_dropped_this_chunk else ""),
                )
                # Show the actual edges (links) persisted — the relation types between resolved
                # nodes — not just an edge count.
                edges_preview = " | ".join(written_edges[:6])
                edges_more = f" (+{len(written_edges) - 6})" if len(written_edges) > 6 else ""
                entry.set_output_preview(
                    f"upserted {len(name_to_id)} node(s), {edges_written_this_chunk} edge(s)"
                    + (f": {edges_preview}{edges_more}" if written_edges else "")
                    + (
                        f" · dropped {edges_dropped_this_chunk} orphan/self-loop"
                        if edges_dropped_this_chunk
                        else ""
                    ),
                    max_len=_INGEST_PREVIEW_MAX,
                )

        stats.chunks_processed += 1

    # ---- live-viz event emits (all no-ops when no event sink is wired) ----

    def _emit_node(self, node_id: str, *, is_new: bool, document_id: str) -> None:
        if self._event_sink is None:
            return
        node = self._store.get_node(node_id)
        if node is None:  # defensive — the upsert just happened
            return
        self._safe_emit(
            KNOWLEDGE_GRAPH_NODE_UPSERTED,
            {"node": node_to_dto(node), "is_new": is_new, "document_id": document_id},
        )

    def _emit_edge(self, edge_id: str, *, is_new: bool, document_id: str) -> None:
        if self._event_sink is None:
            return
        edge = self._store.get_edge(edge_id)
        if edge is None:  # defensive — the upsert just happened
            return
        self._safe_emit(
            KNOWLEDGE_GRAPH_EDGE_UPSERTED,
            {"edge": edge_to_dto(edge), "is_new": is_new, "document_id": document_id},
        )

    def _emit_progress(self, *, document_id: str, index: int, total: int) -> None:
        if self._event_sink is None:
            return
        self._safe_emit(
            KNOWLEDGE_GRAPH_INGEST_PROGRESS,
            {"document_id": document_id, "chunk_index": index, "chunk_total": total},
        )

    def _safe_emit(self, event_type: str, payload: dict[str, Any]) -> None:
        # A viz event must never abort an ingest — swallow + log (the graph write
        # already succeeded; only the live notification failed).
        try:
            self._event_sink(event_type, payload)  # type: ignore[misc]
        except Exception:
            log.warning("⚠️ graph.ingest — event emit failed · type=%s", event_type, exc_info=True)


def _build_edge(src_id: str, tgt_id: str, rel: ExtractedRelation, chunk: ChunkInput) -> GraphEdge:
    """Construct a :class:`GraphEdge` from an :class:`ExtractedRelation`.

    The ``fact`` paraphrase is stored as a node attribute (``attrs.fact``) so it
    can flow into citations. ``rel_type`` stays the SCREAMING_SNAKE_CASE label."""
    return GraphEdge(
        id=_edge_id(src_id, tgt_id, rel.rel_type),
        source_id=src_id,
        target_id=tgt_id,
        rel_type=rel.rel_type,
        chunk_ids=(chunk.chunk_id,) if chunk.chunk_id else (),
        document_ids=(chunk.document_id,) if chunk.document_id else (),
        attrs={"fact": rel.fact} if rel.fact else {},
        created_at=_now_iso(),
    )


__all__ = [
    "ALLOWED_SOURCE_ROLES",
    "REJECTED_SOURCE_ROLES",
    "ChunkInput",
    "GraphEventSink",
    "GraphIngestService",
    "GraphIngestStats",
    "make_llm_disambiguator",
]
