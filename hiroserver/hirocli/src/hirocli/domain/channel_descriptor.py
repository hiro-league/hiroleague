"""Channel descriptor — the config schema + capabilities a plugin declares
at registration (design §5.1/§5.2).

The server cannot import a plugin package (plugins run in isolated environments),
so a plugin ships its JSON Schema and capability descriptor over the wire on
``channel.register``. The ChannelManager persists them here so the config Tools
and admin routes can validate writes and render the UI generically — even across
restarts, or from the CLI while the server is down.

Persisted at ``<workspace>/channels/<name>/descriptor.json`` (the per-channel
state directory, design §5.7). A channel that has never connected has no
descriptor; callers treat that as "no schema" and skip validation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DESCRIPTOR_FILENAME = "descriptor.json"


class ChannelDescriptor(BaseModel):
    """What a plugin declared about itself at registration."""

    channel: str
    version: str = ""
    # JSON Schema for the channel's config dict (from the plugin's pydantic model).
    config_schema: dict[str, Any] | None = None
    # Capability descriptor (see hiro_channel_sdk.capabilities.ChannelCapabilities).
    capabilities: dict[str, Any] | None = None


def descriptor_path(workspace_path: Path, name: str) -> Path:
    """Location of a channel's persisted descriptor under the workspace."""
    return workspace_path / "channels" / name / _DESCRIPTOR_FILENAME


def save_channel_descriptor(workspace_path: Path, descriptor: ChannelDescriptor) -> None:
    """Persist a channel's declared schema + capabilities to disk (idempotent)."""
    path = descriptor_path(workspace_path, descriptor.channel)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(descriptor.model_dump_json(indent=2), encoding="utf-8")
    except OSError as exc:
        # Persisting the descriptor is best-effort — a channel with no descriptor
        # simply skips schema validation until it registers again.
        logger.warning(
            "⚠️ Could not persist channel descriptor — %s · %s",
            descriptor.channel,
            exc,
        )


def load_channel_descriptor(workspace_path: Path, name: str) -> ChannelDescriptor | None:
    """Load a channel's descriptor, or None if it never registered / is unreadable."""
    path = descriptor_path(workspace_path, name)
    if not path.exists():
        return None
    try:
        return ChannelDescriptor.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("⚠️ Corrupt channel descriptor (name=%r): %s", name, exc)
        return None


# ---------------------------------------------------------------------------
# Schema-driven coercion + validation
# ---------------------------------------------------------------------------

def _target_scalar_type(spec: dict[str, Any]) -> str | None:
    """The single scalar JSON-Schema type of a property, or None if ambiguous.

    Handles pydantic's nullable rendering: ``str | None`` becomes
    ``{"anyOf": [{"type": "string"}, {"type": "null"}]}`` rather than a bare type.
    """
    t = spec.get("type")
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        return non_null[0] if len(non_null) == 1 else None
    for combinator in ("anyOf", "oneOf"):
        branches = spec.get(combinator)
        if isinstance(branches, list):
            types = [
                b.get("type")
                for b in branches
                if isinstance(b, dict) and b.get("type") and b.get("type") != "null"
            ]
            if len(types) == 1:
                return types[0]
    return None


def _coerce_scalar(value: Any, target: str | None) -> Any:
    """Best-effort coercion of a loosely-typed value to the schema's declared type.

    CLI/HTTP values arrive JSON-parsed (e.g. a phone number typed on the command
    line becomes an int), so coerce them to what the schema declares before
    validating. Only unambiguous, lossless conversions are applied; anything else
    is left as-is for the validator to reject.
    """
    if target == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if target == "integer" and isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
    if target == "boolean" and isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return value


def secret_keys(schema: dict[str, Any]) -> set[str]:
    """Config keys the schema marks ``secret: true`` (routed to the keyring, §5.6)."""
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {
        key
        for key, spec in props.items()
        if isinstance(spec, dict) and spec.get("secret") is True
    }


def _schema_excluding(schema: dict[str, Any], keys: frozenset[str] | set[str]) -> dict[str, Any]:
    """Shallow copy of *schema* with the named properties removed (secret fields)."""
    if not keys:
        return schema
    props = schema.get("properties")
    if not isinstance(props, dict):
        return schema
    clone = dict(schema)
    clone["properties"] = {k: v for k, v in props.items() if k not in keys}
    return clone


def coerce_config_to_schema(schema: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Return *config* with scalar values coerced to their declared schema types."""
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    coerced = dict(config)
    for key, value in list(coerced.items()):
        spec = props.get(key)
        if isinstance(spec, dict):
            coerced[key] = _coerce_scalar(value, _target_scalar_type(spec))
    return coerced


def coerce_and_validate_config(
    schema: dict[str, Any],
    config: dict[str, Any],
    *,
    secret_keys: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """Coerce *config* to the schema's types, validate it, and return the coerced dict.

    Raises ``ValueError`` (with a human-readable message) when the config violates
    the schema — an unknown key (additionalProperties:false) or a wrong type.

    *secret_keys* fields hold a keyring marker rather than a real value (§5.6), so
    they are excluded from type validation while still being preserved in the
    returned dict.
    """
    coerced = coerce_config_to_schema(schema, config)
    instance = {k: v for k, v in coerced.items() if k not in secret_keys}
    validation_schema = _schema_excluding(schema, secret_keys)
    try:
        jsonschema.validate(instance=instance, schema=validation_schema)
    except jsonschema.ValidationError as exc:
        # exc.message is concise; prefix with the offending key path when present.
        location = ".".join(str(p) for p in exc.absolute_path)
        where = f" (at '{location}')" if location else ""
        raise ValueError(f"Invalid channel config{where}: {exc.message}") from exc
    except jsonschema.SchemaError as exc:
        # A malformed declared schema shouldn't hard-block a write — log and pass through.
        logger.warning("⚠️ Channel config schema is invalid, skipping validation: %s", exc)
    return coerced
