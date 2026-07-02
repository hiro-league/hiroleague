"""Context assembly — render per-turn context blocks into one ephemeral context string.

The single place that converts *(a list of context blocks)* into the per-turn context text that
``call_model`` injects into the current user turn (context first, question last). Persona is NOT
assembled here — it stays a stable system message (cache-friendly). Sources stay decoupled from
the prompt: each contributes a :class:`ContextBlock`; the assembler owns ordering, (future) token
budget, and rendering. The output is ephemeral and never enters the durable ``messages`` history.

Knowledge chunk bodies are Markdown and can carry **structural** markup (headers, thematic breaks)
that would compete with the prompt's own structure. ``neutralize_structural_markdown`` strips that
structure (headers → bold, rules removed) while keeping inline emphasis, and each item is wrapped
in a ``<source …>`` tag so bodies cannot bleed into one another or the surrounding sections.

Phase 1: ordering + rendering only. ``budget`` is a no-op seam for Phase 2 (token budgeting).
See ``docs/context-assembly.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ...services.memory.agent.presentation import RecallRenderOptions, format_recall_context

# Section order (lower first). Instructions → knowledge → memory, matching the prompt design;
# the citation instruction trails last (it refers back to the knowledge it annotates).
_PRIORITY_INSTRUCTIONS = 10
_PRIORITY_KNOWLEDGE = 20
_PRIORITY_MEMORY = 30
_PRIORITY_CITATION = 90

_KNOWLEDGE_HEADING = "## Knowledge retrieved"
_MEMORY_HEADING = "## Memories retrieved"
_EMPTY_SECTION = "(none for this message)"
_CITATION_INSTRUCTION = (
    "When you use the knowledge above, cite the sources inline as [n], matching their rank."
)

# --- Markdown structural neutralization --------------------------------------------------------
# ATX header: up to 3 leading spaces, 1–6 '#', a space, then the title (drop trailing '#').
_ATX_HEADER_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$")
# Thematic break: a line of only '-', '*', or '_' (3+ of the same), optional spaces between.
_THEMATIC_BREAK_RE = re.compile(r"^[ \t]{0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
# Setext H1 underline: a line of only '=' (the H2 '---' underline is caught as a thematic break).
_SETEXT_EQ_RE = re.compile(r"^[ \t]{0,3}=+[ \t]*$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def neutralize_structural_markdown(text: str) -> str:
    """Strip structural Markdown from a body, keeping inline emphasis and lists.

    Converts headers (ATX ``# …`` and setext ``…\\n===``) to ``**bold**`` and removes thematic
    breaks (``---`` / ``***`` / ``___``). Inline ``**bold**`` / ``*italic*``, bullets, and ordered
    lists are left untouched. Used on knowledge chunk text before it is embedded in the prompt so a
    chunk's own headers do not read as new prompt sections.
    """
    src = (text or "").split("\n")
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        line = src[i]
        # Setext H1: a non-empty line immediately followed by a line of only '='.
        if line.strip() and i + 1 < n and _SETEXT_EQ_RE.match(src[i + 1]):
            out.append(f"**{line.strip()}**")
            i += 2
            continue
        atx = _ATX_HEADER_RE.match(line)
        if atx:
            content = atx.group(1).strip()
            out.append(f"**{content}**" if content else "")
            i += 1
            continue
        if _THEMATIC_BREAK_RE.match(line):
            out.append("")  # drop the rule; keep a blank so paragraphs stay separated
            i += 1
            continue
        out.append(line)
        i += 1
    return _MULTI_BLANK_RE.sub("\n\n", "\n".join(out)).strip()


@dataclass(frozen=True)
class ContextBlock:
    """One labeled section of per-turn context contributed by a source.

    ``priority`` orders blocks (lower first) and, in Phase 2, decides drop/trim order under a
    token budget. ``tokens`` is filled by the assembler when budgeting is enabled.
    """

    source: str
    heading: str
    body: str
    priority: int = 100
    tokens: int = 0


class ContextAssembler:
    """Render ordered context blocks into a single context string (no persona).

    Phase 1 includes everything (``budget=None``). The ``budget`` parameter is the seam where
    Phase 2 will enforce a token budget (drop / trim lowest-priority blocks to fit).
    """

    def __init__(self, *, budget: int | None = None) -> None:
        self._budget = budget

    def assemble(self, *, blocks: list[ContextBlock]) -> str:
        parts: list[str] = []
        for block in sorted(blocks, key=lambda b: b.priority):
            body = (block.body or "").strip()
            if not body:
                continue
            parts.append(f"{block.heading}\n{body}" if block.heading else body)
        return "\n\n".join(parts)


# --- Block builders (pure; each reads one scratch slot → ContextBlock) -------------------------


def instructions_block(instructions: str) -> ContextBlock | None:
    """General answering instructions (author-controlled Markdown, including its own header)."""
    text = (instructions or "").strip()
    if not text:
        return None
    return ContextBlock(
        source="instructions", heading="", body=text, priority=_PRIORITY_INSTRUCTIONS
    )


def knowledge_block(sources: list[Any]) -> ContextBlock:
    """Render retrieved knowledge as ``<source …>`` items with neutralized bodies.

    Always returns a block (placeholder body when empty) so the section is a stable part of the
    prompt. ``doc`` is the document title, ``section`` the chunk's heading path.
    """
    items: list[str] = []
    for index, source in enumerate(sources or [], start=1):
        rank = _get(source, "ref") or index
        doc = _xml_attr(_get(source, "title"))
        section = _xml_attr(_get(source, "heading_path"))
        score = _get(source, "score")
        body = neutralize_structural_markdown(str(_get(source, "text") or ""))
        attrs = f'rank="{rank}"'
        if isinstance(score, (int, float)):
            attrs += f' score="{score:.2f}"'
        attrs += f' doc="{doc}"'
        if section:
            attrs += f' section="{section}"'
        items.append(f"<source {attrs}>\n{body}\n</source>")
    body = "\n".join(items) if items else _EMPTY_SECTION
    return ContextBlock(
        source="knowledge", heading=_KNOWLEDGE_HEADING, body=body, priority=_PRIORITY_KNOWLEDGE
    )


def memory_block(
    memories: list[dict[str, Any]], render: RecallRenderOptions | None = None
) -> ContextBlock:
    """Render recalled memory richly — **Relevant Facts / Entities / Messages** with temporal
    validity (``as of`` / ``until`` / ``SUPERSEDED``), grouped by kind, no truncation beyond the
    per-kind caps — via the shared ``format_recall_context`` (P3; replaces the old flat one-bullet
    list that dropped temporal/relationship info). ``render`` comes from ``memory.retrieval.render``
    (toggles + caps); placeholder when empty."""
    body = format_recall_context(memories or [], render) or _EMPTY_SECTION
    return ContextBlock(
        source="memory", heading=_MEMORY_HEADING, body=body, priority=_PRIORITY_MEMORY
    )


def citation_block(*, has_sources: bool, cite_enabled: bool) -> ContextBlock | None:
    if not (has_sources and cite_enabled):
        return None
    return ContextBlock(
        source="citation", heading="", body=_CITATION_INSTRUCTION, priority=_PRIORITY_CITATION
    )


# --- helpers ----------------------------------------------------------------------------------


def _get(item: Any, key: str) -> Any:
    """Read ``key`` from a dict or an object (KnowledgeSource / memory hit)."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _xml_attr(value: Any) -> str:
    """Make a tag-attribute-safe one-liner (no double quotes / newlines)."""
    return " ".join(str(value or "").replace('"', "'").split())
