"""Tests for channel descriptor persistence + schema-driven config validation (§5.1/§5.2)."""

from __future__ import annotations

import pytest

from hirocli.domain.channel_descriptor import (
    ChannelDescriptor,
    coerce_and_validate_config,
    coerce_config_to_schema,
    load_channel_descriptor,
    save_channel_descriptor,
    secret_keys,
)

# A trimmed WhatsApp-shaped schema: a nullable string, a list, a bool — with
# additionalProperties:false (as pydantic emits for extra="forbid").
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "owner_number": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "allowed_senders": {"type": "array", "items": {"type": "string"}},
        "send_read_receipts": {"type": "boolean"},
    },
}


def test_descriptor_round_trip(tmp_path) -> None:
    save_channel_descriptor(
        tmp_path,
        ChannelDescriptor(
            channel="whatsapp",
            version="0.1.0",
            config_schema=_SCHEMA,
            capabilities={"pairing": "qr", "actions": ["logout"]},
        ),
    )
    loaded = load_channel_descriptor(tmp_path, "whatsapp")
    assert loaded is not None
    assert loaded.channel == "whatsapp"
    assert loaded.config_schema == _SCHEMA
    assert loaded.capabilities == {"pairing": "qr", "actions": ["logout"]}


def test_load_missing_descriptor_returns_none(tmp_path) -> None:
    assert load_channel_descriptor(tmp_path, "nope") is None


def test_coerce_int_owner_number_to_string() -> None:
    # CLI JSON-parses a bare number → int; the nullable-string field must coerce it.
    coerced = coerce_config_to_schema(_SCHEMA, {"owner_number": 201223504849})
    assert coerced["owner_number"] == "201223504849"


def test_coerce_and_validate_accepts_int_phone_via_coercion() -> None:
    # This is the live-config case: owner_number stored as an int must pass.
    out = coerce_and_validate_config(
        _SCHEMA, {"owner_number": 201223504849, "send_read_receipts": True}
    )
    assert out["owner_number"] == "201223504849"
    assert out["send_read_receipts"] is True


def test_validate_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="Invalid channel config"):
        coerce_and_validate_config(_SCHEMA, {"typpo_number": "123"})


def test_validate_rejects_uncoercible_type() -> None:
    # A non-numeric string can't coerce to bool → stays a string → rejected.
    with pytest.raises(ValueError, match="Invalid channel config"):
        coerce_and_validate_config(_SCHEMA, {"send_read_receipts": "definitely"})


def test_validate_accepts_partial_config() -> None:
    # No required fields (all have defaults) → a partial dict is valid.
    out = coerce_and_validate_config(_SCHEMA, {"allowed_senders": ["123", "456"]})
    assert out["allowed_senders"] == ["123", "456"]


def test_malformed_schema_does_not_hard_fail() -> None:
    # A broken declared schema should skip validation, not raise.
    out = coerce_and_validate_config({"type": "nonsense-type"}, {"x": 1})
    assert out == {"x": 1}


# --- secret fields (§5.6) ---------------------------------------------------

_SECRET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "bot_token": {"type": "string", "secret": True},
        "polling": {"type": "boolean"},
    },
}


def test_secret_keys_extracts_secret_marked_fields() -> None:
    assert secret_keys(_SECRET_SCHEMA) == {"bot_token"}
    assert secret_keys(_SCHEMA) == set()


def test_validation_skips_secret_field_marker() -> None:
    # bot_token holds a keyring marker (a dict), not a string; excluding it from
    # validation means the otherwise type-mismatched marker doesn't fail the write.
    out = coerce_and_validate_config(
        _SECRET_SCHEMA,
        {"bot_token": {"__secret__": True}, "polling": True},
        secret_keys={"bot_token"},
    )
    assert out["bot_token"] == {"__secret__": True}
    assert out["polling"] is True


def test_validation_still_catches_unknown_key_alongside_secret() -> None:
    with pytest.raises(ValueError, match="Invalid channel config"):
        coerce_and_validate_config(
            _SECRET_SCHEMA,
            {"bot_token": {"__secret__": True}, "bogus": 1},
            secret_keys={"bot_token"},
        )
