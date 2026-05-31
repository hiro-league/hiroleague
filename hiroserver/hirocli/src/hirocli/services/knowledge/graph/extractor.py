"""L3 single-call entity + relation extractor.

One structured-output LLM call per chunk yields typed entities **and** typed
relations (LightRAG single-call pattern — research §2.1). Reuses the workspace's
``model_factory`` and the locked ``knowledge_graph_extraction`` tuning profile —
no hardcoded model params, no separate prompt scaffolding.

This module is intentionally **engine-agnostic on the model side**: it accepts a
``BaseChatModel`` (already constructed elsewhere) plus the chunk text and the
prompt. The orchestrator wires the model + prompt; the extractor owns the
structured-output binding + parsing + usage reporting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hiro_commons.log import Logger
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from .ontology import NODE_TYPE_GUIDE, ChunkExtraction

log = Logger.get("SVC.KNOWLEDGE.GRAPH.EXTRACT")


# Prompt-level pollution control (Graphiti research §1.7) — exclusion rules,
# possessive qualification, two-distinct-entity rule, Wikipedia/uniquely-identifiable
# test. These are the cheapest, highest-leverage quality lever for chatter-heavy
# sources; keep them strict here so downstream resolution / retrieval isn't fed junk.
def _build_extraction_prompt() -> str:
    type_lines = "\n".join(f"- {t}: {desc}" for t, desc in NODE_TYPE_GUIDE.items())
    return f"""You extract a small, high-quality knowledge graph from one document chunk.

Output two lists in the required structured format: `entities[]` and `relations[]`.

ENTITIES — what to extract
Extract concrete, **uniquely identifiable** things from the chunk. Each one MUST be:
- Specific enough to be its own entry in a personal knowledge graph (the "Wikipedia test").
- Named, or qualified by its possessor when it's a relational term — extract "Maya's sister",
  not "sister"; "Jordan's cat", not "cat"; "the apartment in Paris", not "the apartment".
- Preserve specificity — "wool coat" not "coat", "road cycling" not "cycling".

Type each entity as ONE of:
{type_lines}

Use the generic "Entity" type ONLY when none of the specific types fit. When in doubt, extract.

DO NOT extract:
- Pronouns (he/she/they/it). If a pronoun has a clear referent in the chunk, use the referent's name.
- Abstract concepts, feelings, opinions, moods.
- Generic common nouns without qualification (stuff, things, food, time, day, place).
- Generic media nouns (photo, video, picture, message) unless uniquely named.
- Bare kinship or pet terms (mom, dad, cat, dog) — always qualify with the possessor.

ALIASES — when to populate
Populate `aliases` ONLY when the chunk pairs a kinship/possessive/relational term WITH the proper
name in the same passage. The point is to give the SAME entity multiple surface forms so future
bare mentions resolve deterministically:
  - "my mother Sara called" → name="Sara", aliases=["my mother", "mom"]
  - "Maya's cat Whiskers"   → name="Whiskers", aliases=["Maya's cat"]
  - "Eiffel Tower (the tower in Paris)" → name="Eiffel Tower", aliases=["the tower in Paris"]
Rules:
- Do NOT invent aliases that aren't in the text or directly implied by it.
- Do NOT include the canonical `name` itself in aliases.
- If the chunk only gives a kinship term ("mom called today") with no proper name in scope,
  extract the kinship form as the name (qualified: "Maya's mom") — don't guess the proper name.

RELATIONS — what to extract
Each relation MUST connect TWO DISTINCT entities from your entities[] list. Reject single-entity
emotional states ("Alice feels happy") unless anchored to a second concrete entity. Use a
SCREAMING_SNAKE_CASE predicate, e.g. PARTICIPANT, LIVES_IN, SPOUSE, WORKS_AT, LOCATED_IN,
KNOWS, OWNS, OCCURRED_IN, BORN_IN, ATTENDED, AUTHORED, PHOTOGRAPHED_AT.

Include a one-sentence `fact` that preserves concrete details (dates, numbers, places) for
citation. Decompose n-ary statements into binary relations. Treat relations as undirected
unless the predicate has a clear direction (WORKS_AT, OWNS).

OUTPUT
Return only the structured JSON in the required schema. When in doubt about whether to extract,
PREFER OMITTING. A small accurate graph is better than a noisy one.
""".strip()


_EXTRACTION_PROMPT = _build_extraction_prompt()


@dataclass(frozen=True)
class ExtractionUsage:
    """Token/error envelope for ledger reporting. Mirrors the shape ``rewrite_query``
    publishes so the graph-ingest node folds into the existing run cost view."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    finish_reason: str = ""
    parsing_error: str = ""


@dataclass(frozen=True)
class ExtractionResult:
    extraction: ChunkExtraction
    usage: ExtractionUsage
    raw: Any = None  # the underlying LangChain response, for debugging


async def extract_from_chunk(
    chunk_text: str,
    *,
    model: BaseChatModel,
) -> ExtractionResult:
    """Run one structured-output LLM call → ``ChunkExtraction``.

    Fails safe: any parse failure or model error returns an EMPTY extraction +
    populated ``usage.parsing_error`` rather than raising. The orchestrator
    treats an empty extraction as "nothing to add" — the chunk is still recorded
    as processed; the graph is just not grown from it. This mirrors the
    ``rewrite_query`` fallback contract (research §1.7 / existing code).
    """
    text = (chunk_text or "").strip()
    if not text:
        return ExtractionResult(
            extraction=ChunkExtraction(),
            usage=ExtractionUsage(parsing_error="empty_chunk_text"),
        )

    structured = model.with_structured_output(ChunkExtraction, include_raw=True)
    messages = [
        SystemMessage(content=_EXTRACTION_PROMPT),
        HumanMessage(content=f"CHUNK:\n{text}"),
    ]
    try:
        raw_result = await structured.ainvoke(messages)
    except Exception as exc:
        # External call MUST log + raise the right thing (general-coding rule).
        # Here we degrade gracefully because empty extraction is well-defined,
        # and a single bad chunk shouldn't abort an ingest job.
        log.warning(
            "⚠️ graph.extract — model call failed · falling back to empty extraction",
            error=str(exc)[:200],
            exc_info=True,
        )
        return ExtractionResult(
            extraction=ChunkExtraction(),
            usage=ExtractionUsage(parsing_error=f"model_call_failed: {str(exc)[:160]}"),
        )

    # ``include_raw=True`` returns a dict: {parsed, raw, parsing_error}. Inspect
    # parsing_error explicitly — structured_output does NOT raise on parse failure.
    parsed = raw_result.get("parsed") if isinstance(raw_result, dict) else None
    raw_msg = raw_result.get("raw") if isinstance(raw_result, dict) else None
    parsing_error = raw_result.get("parsing_error") if isinstance(raw_result, dict) else None

    usage = _extract_usage(raw_msg, parsing_error=parsing_error)

    if not isinstance(parsed, ChunkExtraction):
        log.warning(
            "⚠️ graph.extract — unparsable structured output · falling back to empty extraction",
            error=str(parsing_error)[:200] if parsing_error else "no parsed object returned",
            finish_reason=usage.finish_reason or "unknown",
        )
        return ExtractionResult(
            extraction=ChunkExtraction(),
            usage=usage,
            raw=raw_msg,
        )

    # Validate cross-references: every relation must reference an entity in the list.
    # Drop orphan relations (don't fail) — the chunk is still useful for what survived.
    entity_names = {e.name for e in parsed.entities}
    cleaned_relations = [
        r for r in parsed.relations
        if r.source_name in entity_names and r.target_name in entity_names
        and r.source_name != r.target_name  # two-distinct-entity rule
    ]
    if len(cleaned_relations) != len(parsed.relations):
        log.warning(
            "⚠️ graph.extract — dropped %d orphan/self-loop relation(s)",
            len(parsed.relations) - len(cleaned_relations),
        )
        parsed = ChunkExtraction(entities=parsed.entities, relations=cleaned_relations)

    return ExtractionResult(extraction=parsed, usage=usage, raw=raw_msg)


def _extract_usage(raw_msg: Any, *, parsing_error: Any) -> ExtractionUsage:
    """Pull token counts + finish reason from a LangChain ``AIMessage``."""
    if raw_msg is None:
        return ExtractionUsage(parsing_error=str(parsing_error or "") or "")

    usage_meta: dict[str, Any] = {}
    response_meta: dict[str, Any] = {}
    if hasattr(raw_msg, "usage_metadata"):
        candidate = getattr(raw_msg, "usage_metadata", None)
        if isinstance(candidate, dict):
            usage_meta = candidate
    if hasattr(raw_msg, "response_metadata"):
        candidate = getattr(raw_msg, "response_metadata", None)
        if isinstance(candidate, dict):
            response_meta = candidate

    input_tokens = int(usage_meta.get("input_tokens") or 0)
    output_tokens = int(usage_meta.get("output_tokens") or 0)
    details = usage_meta.get("input_token_details") or {}
    cached = int(details.get("cache_read") or 0) if isinstance(details, dict) else 0
    out_details = usage_meta.get("output_token_details") or {}
    reasoning = int(out_details.get("reasoning") or 0) if isinstance(out_details, dict) else 0
    finish = str(response_meta.get("finish_reason") or "")

    return ExtractionUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached,
        reasoning_tokens=reasoning,
        finish_reason=finish,
        parsing_error=str(parsing_error or "") or "",
    )


__all__ = ["ExtractionResult", "ExtractionUsage", "extract_from_chunk"]
