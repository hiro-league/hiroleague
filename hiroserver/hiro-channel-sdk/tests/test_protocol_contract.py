from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

from hiro_channel_sdk.models import UnifiedMessage


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_DIR = REPO_ROOT / "protocol"
FIXTURES_DIR = PROTOCOL_DIR / "fixtures"

VALID_FIXTURES = [
    "valid-text-message.json",
    "valid-audio-message.json",
    "valid-message-received-event.json",
    "valid-message-transcribed-event.json",
    "valid-message-voiced-event.json",
    "valid-request.json",
    "valid-response-ok.json",
    "valid-response-error.json",
]

INVALID_FIXTURES = [
    "invalid-event-with-content.json",
    "invalid-message-without-content.json",
    "invalid-unsupported-version.json",
]

REQUEST_RESPONSE_FIXTURES = [
    "valid-request.json",
    "valid-response-ok.json",
    "valid-response-error.json",
]

GATEWAY_ENVELOPE_FIXTURES = [
    "valid-gateway-inbound-envelope.json",
    "valid-gateway-outbound-envelope.json",
]

AUTH_FRAME_FIXTURES = [
    "valid-auth-challenge.json",
    "valid-auth-response-device.json",
    "valid-auth-ok.json",
]

PAIRING_FRAME_FIXTURES = [
    "valid-pairing-request.json",
    "valid-pairing-pending.json",
    "valid-pairing-response-approved.json",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def unified_message_validator() -> Draft202012Validator:
    schema = _load_json(PROTOCOL_DIR / "unified-message.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture(scope="module")
def request_response_validator() -> Draft202012Validator:
    schema = _load_json(PROTOCOL_DIR / "request-response.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_validator(schema_name: str) -> Draft202012Validator:
    schema = _load_json(PROTOCOL_DIR / schema_name)
    Draft202012Validator.check_schema(schema)
    unified_schema = _load_json(PROTOCOL_DIR / "unified-message.schema.json")
    registry = Registry().with_resource(
        "https://hiroleague.local/protocol/unified-message.schema.json",
        Resource.from_contents(unified_schema),
    )
    return Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    )


@pytest.mark.parametrize("fixture_name", VALID_FIXTURES)
def test_valid_fixtures_match_schema_and_pydantic(
    fixture_name: str,
    unified_message_validator: Draft202012Validator,
) -> None:
    payload = _load_json(FIXTURES_DIR / fixture_name)

    unified_message_validator.validate(payload)
    UnifiedMessage.model_validate(payload)


@pytest.mark.parametrize("fixture_name", INVALID_FIXTURES)
def test_invalid_fixtures_fail_schema_and_pydantic(
    fixture_name: str,
    unified_message_validator: Draft202012Validator,
) -> None:
    payload = _load_json(FIXTURES_DIR / fixture_name)

    with pytest.raises(Exception):
        unified_message_validator.validate(payload)
    with pytest.raises(ValidationError):
        UnifiedMessage.model_validate(payload)


@pytest.mark.parametrize("fixture_name", REQUEST_RESPONSE_FIXTURES)
def test_request_response_json_body_matches_schema(
    fixture_name: str,
    request_response_validator: Draft202012Validator,
) -> None:
    payload = _load_json(FIXTURES_DIR / fixture_name)
    body = json.loads(payload["content"][0]["body"])

    request_response_validator.validate(body)


@pytest.mark.parametrize("fixture_name", GATEWAY_ENVELOPE_FIXTURES)
def test_gateway_envelope_fixtures_match_schema(fixture_name: str) -> None:
    validator = _schema_validator("gateway-envelope.schema.json")

    validator.validate(_load_json(FIXTURES_DIR / fixture_name))


@pytest.mark.parametrize("fixture_name", AUTH_FRAME_FIXTURES)
def test_auth_frame_fixtures_match_schema(fixture_name: str) -> None:
    validator = _schema_validator("auth-frames.schema.json")

    validator.validate(_load_json(FIXTURES_DIR / fixture_name))


@pytest.mark.parametrize("fixture_name", PAIRING_FRAME_FIXTURES)
def test_pairing_frame_fixtures_match_schema(fixture_name: str) -> None:
    validator = _schema_validator("pairing-frames.schema.json")

    validator.validate(_load_json(FIXTURES_DIR / fixture_name))
