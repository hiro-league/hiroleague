"""Stand-ins for the AI and the voices, for a test environment whose switchboard sets them to fake (hiro-docs
standards/workflow.md, "The switchboard"). The core answers an app's ask itself: nothing reaches a provider, nothing is
paid, and the answer says it is fake. They make every page and flow that asks the AI run end to end; what they answer
means nothing.

- an ask: a short canned text; where the app asked for JSON in a shape (`schema`), the smallest value of that shape;
- a conversation: the same, as the model's reply, with no tool calls;
- vectors: made from each text's own hash, so the same text always gets the same vector (search runs, its order
  means nothing);
- reranking: by the words a document shares with the query;
- speech: a short soft tone as long as the words would take, so players and voice notes work.

Used only by the extensions' request handlers (runtime/*_for_extensions.py), after the switchboard's gate says fake.
"""

from __future__ import annotations

import array
import hashlib
import math
import re
from typing import Any

from hiro_commons import switchboard

PROVIDER = "fake"
MODEL = "fake"
PROFILE_NAME = "Fake (the switchboard)"

# What an embedding model's vectors measure, so a fake vector fits an index the real model filled. Others: DEFAULT_DIMS.
KNOWN_DIMS = (("text-embedding-3-large", 3072), ("text-embedding-3-small", 1536), ("text-embedding-ada", 1536),
              ("bge-large", 1024), ("bge-m3", 1024), ("bge-base", 768), ("mpnet", 768), ("bge-small", 384),
              ("minilm", 384))
DEFAULT_DIMS = 384
MAX_DEPTH = 12  # a schema that names itself stops here


def text() -> str:
    place = switchboard.board().place
    return f"A fake answer: AI is set to fake in {place}, so no model was asked and nothing was paid."


def from_schema(schema: Any, defs: dict[str, Any] | None = None, depth: int = 0) -> Any:
    """The smallest value a JSON schema allows: required fields only, empty lists, the first choice, zero, ""."""
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return None
    defs = defs if defs is not None else {**schema.get("$defs", {}), **schema.get("definitions", {})}
    if "$ref" in schema:
        return from_schema(defs.get(str(schema["$ref"]).rsplit("/", 1)[-1]), defs, depth + 1)
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    for many in ("anyOf", "oneOf"):
        if schema.get(many):
            return from_schema(schema[many][0], defs, depth + 1)
    if schema.get("allOf"):
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            value = from_schema(part, defs, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    if kind == "object" or (kind is None and "properties" in schema):
        props = schema.get("properties") or {}
        wanted = schema.get("required") or list(props)
        return {name: from_schema(props.get(name, {}), defs, depth + 1) for name in wanted}
    if kind == "array":
        return [from_schema(schema.get("items", {}), defs, depth + 1) for _ in range(int(schema.get("minItems") or 0))]
    if kind == "string":
        return "fake" if int(schema.get("minLength") or 0) <= 4 else "fake " * (int(schema["minLength"]) // 5 + 1)
    if kind in ("integer", "number"):
        low = schema.get("minimum", schema.get("exclusiveMinimum"))
        return (int(low) + (1 if "exclusiveMinimum" in schema else 0)) if low is not None else 0
    if kind == "boolean":
        return False
    return None


def dims_of(model: str) -> int:
    lower = model.lower()
    return next((d for name, d in KNOWN_DIMS if name in lower), DEFAULT_DIMS)


def vector(words: str, dims: int) -> list[float]:
    """A unit vector made from the text's hash: the same text, the same vector."""
    out: list[float] = []
    block = 0
    while len(out) < dims:
        digest = hashlib.sha256(f"{block}:{words}".encode()).digest()
        out.extend((b - 127.5) / 127.5 for b in digest)
        block += 1
    out = out[:dims]
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


def _words(s: str) -> set[str]:
    return set(re.findall(r"\w+", s.lower()))


def ranked(query: str, documents: list[str], top_n: int | None) -> list[dict[str, Any]]:
    """[{index, score}], best first: the share of the query's words each document has (ties: as they came)."""
    asked = _words(query)
    scored = [(len(asked & _words(doc)) / len(asked) if asked else 0.0, i) for i, doc in enumerate(documents)]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [{"index": i, "score": round(score, 4)} for score, i in scored[: top_n or len(scored)]]


TONE_RATE = 24000
TONE_HZ = 330
TONE_LEVEL = 1800  # of 32767: soft
SECONDS_PER_CHAR = 0.06
MIN_SECONDS, MAX_SECONDS = 0.8, 12.0


def tone(words: str) -> tuple[bytes, int, float]:
    """(16-bit mono PCM, its rate, its seconds): a soft tone about as long as the words would take to say, fading in
    and out."""
    seconds = max(MIN_SECONDS, min(MAX_SECONDS, len(words) * SECONDS_PER_CHAR))
    n = int(seconds * TONE_RATE)
    fade = TONE_RATE // 10
    samples = array.array("h", (
        int(TONE_LEVEL * min(1.0, i / fade, (n - i) / fade) * math.sin(2 * math.pi * TONE_HZ * i / TONE_RATE))
        for i in range(n)))
    return samples.tobytes(), TONE_RATE, seconds
