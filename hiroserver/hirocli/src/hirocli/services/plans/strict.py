"""A JSON schema as OpenAI's strict structured output wants it, and the answer back as the schema had it (Michel,
2026-10-28: StudyHiro's questions failed on Codex). Ported from HomeHiro's llm/strict.py for the core's Codex
plan tool (Phase 7a Part B). Strict mode refuses a schema unless every object, nested ones too,
is closed (`additionalProperties: false`) and lists every property as required; a property the schema left optional
is then required and may be null, and a null there is dropped from the answer, so the asker gets what its own schema
said. Pure: no I/O.
"""

from __future__ import annotations

import json
from typing import Any


def closed(schema: Any) -> Any:
    """The schema with every object closed and every property required, those that weren't also allowed null."""
    if isinstance(schema, list):
        return [closed(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: closed(v) for k, v in schema.items()}
    props = out.get("properties")
    if isinstance(props, dict):
        given = set(schema.get("required", []))
        out["properties"] = {k: p if k in given else _nullable(p) for k, p in props.items()}
        out["required"] = list(props)
        out["additionalProperties"] = False
    return out


def _nullable(spec: Any) -> Any:
    if not isinstance(spec, dict):
        return spec
    kind = spec.get("type")
    if kind is None:
        return {"anyOf": [spec, {"type": "null"}]}
    kinds = kind if isinstance(kind, list) else [kind]
    return spec if "null" in kinds else {**spec, "type": [*kinds, "null"]}


def opened(text: str, schema: dict) -> str:
    """The answer to the closed schema as the schema itself had it: a null where a property was optional dropped.
    Text that isn't JSON is left as it is, for the asker to refuse."""
    try:
        answer = json.loads(text)
    except ValueError:
        return text
    return json.dumps(_drop_nulls(answer, schema), ensure_ascii=False)


def _drop_nulls(value: Any, schema: Any) -> Any:
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
        props, given = schema["properties"], set(schema.get("required", []))
        return {k: _drop_nulls(v, props.get(k)) for k, v in value.items() if not (v is None and k in props and k not in given)}
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_drop_nulls(v, schema["items"]) for v in value]
    return value
