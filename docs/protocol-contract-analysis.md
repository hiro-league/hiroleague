# Protocol Contract Analysis

This document analyzes refactor target #1 from `refactor-review-map.md`: creating
a real cross-language protocol contract between the Python server/channel system
and the Flutter client.

## Summary

This is a high-priority refactor target. The protocol is central to Hiro, but it
currently lives in several places:

- Python Pydantic models in `hiro-channel-sdk`.
- Dart mirror classes in `device_apps`.
- Raw gateway relay envelopes.
- Raw auth and pairing frames.
- Hardcoded event, content, and message type strings.
- Metadata conventions such as `channel_id`, `device_name`, and
  `sender_device_id`.

The current code is workable, but the next protocol change can silently break one
side unless both Python and Dart are kept in sync manually.

## Current Protocol Surfaces

### UnifiedMessage

Python defines the main model in:

- `hiroserver/hiro-channel-sdk/src/hiro_channel_sdk/models.py`

Dart manually mirrors it in:

- `device_apps/lib/data/remote/gateway/unified_message.dart`

The shape includes:

- `version`
- `message_type`
- `request_id`
- `routing`
- `content`
- `event`

### Gateway Relay Envelope

Gateway relay frames use an outer envelope:

```json
{
  "sender_device_id": "device-id",
  "target_device_id": "optional-target-device-id",
  "payload": {}
}
```

This is handled with raw maps in both Python and Dart.

### Auth And Pairing Frames

Gateway auth and pairing also use raw `type`-discriminated maps:

- `auth_challenge`
- `auth_response`
- `auth_ok`
- `pairing_request`
- `pairing_pending`
- `pairing_response`

These are protocol messages, but they are not modeled as shared contracts.

### Request/Response Body

Request and response messages are represented as `UnifiedMessage` values with
`content_type: "json"`, where the body contains another JSON object:

Request body:

```json
{
  "method": "channels.list",
  "params": {}
}
```

Response body:

```json
{
  "status": "ok",
  "data": {}
}
```

or:

```json
{
  "status": "error",
  "error": {
    "code": "method_not_found",
    "message": "Unknown method"
  }
}
```

This should be treated as part of the protocol, not just an implementation detail.

## Findings

### 1. UnifiedMessage Has Two Manual Definitions

Python and Dart define the same wire shape separately. There is no shared schema,
generated model, or compatibility test proving the two definitions match.

Risk:

- Python can add or change a field while Dart still compiles.
- Dart can emit a shape Python rejects.
- Comments and behavior can drift.

### 2. Validation Rules Differ Between Python And Dart

Python validates some semantic constraints:

- `message_type: "message"` requires at least one content item.
- `message_type: "message"` must not include an event payload.
- `message_type: "event"` requires an event payload.
- `message_type: "event"` must not include content.

Dart validates field structure but does not enforce equivalent semantic rules.

Risk:

- Dart can construct invalid protocol objects.
- Some invalid frames only fail after they reach Python.

### 3. Request/Response Is Used But Still Described As Reserved

Python constants still describe `request` and `response` as reserved, but the
code already uses them:

- Flutter sends request messages through `GatewayRequestClient`.
- Python handles them through `RequestHandler`.

Risk:

- The documented contract is behind the actual contract.
- Future contributors may treat request/response as unstable or unused.

### 4. Direction Semantics Are Ambiguous

The model comments say `direction` is from the Hiro server's perspective:

- `inbound`: arriving into Hiro
- `outbound`: leaving Hiro

But Flutter sends normal user messages with `direction: "outbound"` before the
devices channel rewrites them to `inbound`.

Risk:

- The same field means different things at different protocol layers.
- New channels or clients may choose different conventions.

### 5. Important Constants Are Repeated In Dart

Python centralizes constants for message types, event types, and content types.
Dart repeats strings such as:

- `0.1`
- `message`
- `event`
- `request`
- `response`
- `text`
- `audio`
- `json`
- `message.received`
- `message.transcribed`
- `message.voiced`

Risk:

- Typos are not caught centrally.
- Adding an event requires manual updates across files.

### 6. Metadata Keys Are Informal Contract

Several routing metadata keys are significant:

- `channel_id`
- `device_name`
- `sender_device_id`
- `friendly_name`
- `request_voice_reply`

These are not modeled or documented as part of the protocol.

Risk:

- Metadata can become a hidden second protocol.
- Client/server behavior can depend on undocumented keys.

## Proposed Design

### Step 1: Create A Protocol Contract Folder

Add a dedicated protocol contract area, for example:

```text
protocol/
  unified-message.schema.json
  gateway-envelope.schema.json
  auth-frames.schema.json
  pairing-frames.schema.json
  request-response.schema.json
  fixtures/
```

Keep explanatory documentation under:

```text
docs/protocol/
  events.md
  metadata.md
```

The repo-level `protocol/` folder should be treated as the source of truth for
the machine-readable wire contract.

### Step 2: Start With JSON Schema

Use JSON Schema first because it is language-neutral, easy to review, and easy
to test from both Python and Dart.

Example:

```json
{
  "type": "object",
  "required": ["version", "message_type", "routing", "content"],
  "properties": {
    "version": { "const": "0.1" },
    "message_type": {
      "enum": ["message", "event", "request", "response", "stream"]
    },
    "request_id": {
      "type": ["string", "null"]
    },
    "routing": {
      "$ref": "#/$defs/MessageRouting"
    },
    "content": {
      "type": "array",
      "items": { "$ref": "#/$defs/ContentItem" }
    },
    "event": {
      "anyOf": [
        { "$ref": "#/$defs/EventPayload" },
        { "type": "null" }
      ]
    }
  }
}
```

### Step 3: Add Golden Fixtures

Add shared JSON examples that both Python and Dart tests parse:

```text
protocol/fixtures/
  valid-text-message.json
  valid-audio-message.json
  valid-message-received-event.json
  valid-message-transcribed-event.json
  valid-message-voiced-event.json
  valid-request.json
  valid-response-ok.json
  valid-response-error.json
  invalid-event-with-content.json
  invalid-message-without-content.json
  invalid-unsupported-version.json
```

These fixtures should become the first compatibility tests.

### Step 4: Add Contract Tests Before Refactoring Models

Python tests should verify:

- The JSON Schema accepts valid fixtures and rejects invalid fixtures.
- `UnifiedMessage.model_validate()` accepts valid fixtures and rejects invalid
  fixtures consistently.

Dart tests should verify:

- `UnifiedMessage.fromJson()` accepts valid fixtures and rejects invalid
  fixtures consistently.
- Dart serialization of outbound messages matches the fixture shape.

### Step 5: Centralize Dart Constants

Before introducing generation, add Dart constants for:

- protocol version
- message types
- content types
- event types
- gateway envelope keys
- auth frame types
- pairing frame types
- metadata keys

This is a low-risk step that immediately reduces drift.

### Step 6: Decide Direction Semantics

Make one explicit decision:

Option A:

- `direction` is always from the Hiro server's perspective.
- Clients should not set final server-facing direction.
- The devices channel normalizes external client messages before emitting them
  to Hiro.

Option B:

- `direction` is from the sender's perspective on the external wire.
- Server-internal messages use a normalized internal model.

Current behavior is closest to Option A, but the external Flutter usage makes
that unclear. The simplest near-term fix is to document that device-originated
messages are normalized by the devices channel before entering Hiro.

### Step 7: Consider Generated Models Later

After schemas and tests exist, decide whether to generate:

- Python models from schema.
- Dart models from schema.
- TypeScript or other future client models.

Generation is optional at first. The immediate value comes from one reviewed
schema plus compatibility tests.

## Implementation Order

1. Add protocol docs and JSON schemas.
2. Add golden fixtures.
3. Add Python contract tests.
4. Add Dart contract tests.
5. Add Dart protocol constants.
6. Tighten Dart semantic validation to match Python.
7. Update comments/docs for request/response and direction semantics.

## Acceptance Criteria

This refactor is successful when:

- There is one reviewed contract for the message and gateway wire format.
- Python and Dart parse the same valid fixtures.
- Python and Dart reject the same invalid fixtures.
- Protocol constants are not repeated as random strings across Dart code.
- Request/response is documented as implemented, not reserved.
- Direction semantics are documented clearly.
- Metadata keys used across layers are documented or modeled.
