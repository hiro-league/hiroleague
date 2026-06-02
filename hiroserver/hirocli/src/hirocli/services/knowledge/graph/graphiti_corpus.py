"""Parse a single multi-episode file (``*.episodes.jsonl``) into episodes.

One JSON object per line = one episode (decision G6, docs/knowledge-graphiti-pivot-design.md
§8.3). **We** split on line boundaries and hand Graphiti one small body at a time,
so its internal ``should_chunk`` never fires and the ``episode == chunk ==
point_id`` invariant holds. Episodes are returned sorted by ``timestamp`` so a
later fact supersedes an earlier one when ingested in order.

Reusable beyond eval: this is the general **series-ingest** format (upload a
journal / chat-log file, processed as a dated episode series).

Line schema: ``{id, timestamp, type?, speaker?, body, metadata?}`` —
``id`` (→ episode uuid == Qdrant point_id), ``timestamp`` (ISO-8601), ``body``
(the small chunk text). Blank lines and ``#`` comments are skipped.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from graphiti_core.helpers import CHUNK_MIN_TOKENS
from graphiti_core.utils.content_chunking import estimate_tokens
from hiro_commons.log import Logger

from .graphiti_ingest import GraphitiEpisodeInput

log = Logger.get("SVC.KNOWLEDGE.GRAPH.GRAPHITI.CORPUS")


def _parse_timestamp(value: object, *, lineno: int) -> dt.datetime:
    s = str(value).strip()
    # Accept a trailing 'Z' (fromisoformat handles it only on 3.11+, normalize anyway).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"episodes.jsonl line {lineno}: bad timestamp {value!r}") from exc
    # Naive → assume UTC so ordering/temporal comparisons are well-defined.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def parse_episodes_jsonl(
    text: str, *, default_document_id: str = "corpus"
) -> list[GraphitiEpisodeInput]:
    """Parse JSONL episode lines → sorted :class:`GraphitiEpisodeInput` list.

    Raises ``ValueError`` on invalid JSON, missing required fields (``id`` /
    ``body`` / ``timestamp``), duplicate ids, or a body large enough that Graphiti
    would re-chunk it (which would fork ``episode == chunk == point_id``)."""
    episodes: list[GraphitiEpisodeInput] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"episodes.jsonl line {lineno}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"episodes.jsonl line {lineno}: expected a JSON object")

        eid = str(obj.get("id") or "").strip()
        body = str(obj.get("body") or "").strip()
        ts_raw = obj.get("timestamp")
        if not eid or not body or not ts_raw:
            raise ValueError(
                f"episodes.jsonl line {lineno}: 'id', 'body', 'timestamp' are required"
            )
        if eid in seen:
            raise ValueError(f"episodes.jsonl line {lineno}: duplicate id {eid!r}")
        seen.add(eid)

        # Fail loud if the body is big enough that Graphiti's should_chunk would
        # split it — the author must keep one episode = one small chunk.
        if estimate_tokens(body) >= CHUNK_MIN_TOKENS:
            raise ValueError(
                f"episodes.jsonl line {lineno} ({eid}): body too large "
                f"(~{estimate_tokens(body)} tokens ≥ {CHUNK_MIN_TOKENS}); split it so "
                f"one episode stays one chunk."
            )

        meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        document_id = str(meta.get("document_id") or default_document_id)
        episodes.append(
            GraphitiEpisodeInput(
                chunk_id=eid,
                document_id=document_id,
                text=body,
                reference_time=_parse_timestamp(ts_raw, lineno=lineno),
                document_title=str(meta.get("document_title") or document_id),
                source=str(obj.get("type") or "text"),
                speaker=str(obj.get("speaker") or ""),
            )
        )

    # Chronological so supersession is correct when ingested in order.
    episodes.sort(key=lambda e: e.reference_time or dt.datetime.min.replace(tzinfo=dt.UTC))
    return episodes


def load_episodes_file(path: Path | str) -> list[GraphitiEpisodeInput]:
    """Read + parse a ``*.episodes.jsonl`` file; document_id defaults to the stem."""
    p = Path(path)
    return parse_episodes_jsonl(p.read_text(encoding="utf-8"), default_document_id=p.stem)


__all__ = ["load_episodes_file", "parse_episodes_jsonl"]
