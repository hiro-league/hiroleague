# Refactor Review Map

This is not a completed code review. It is a preliminary design review map based
on a quick pass over representative files. Use it to decide where a deeper,
line-by-line review should start.

## Project Shape

The codebase is a Python `uv` workspace plus a Flutter client:

- Hiro server: desktop server, CLI, runtime, admin UI, tools, domain services.
- `gateway`: WebSocket relay with desktop/device authentication.
- `hiro-channel-sdk`: shared Python SDK and plugin contract.
- `hiro-commons`: shared crypto, logging, process, timestamp, and constants.
- `channels/*`: channel plugins.
- `device_apps`: Flutter client with Riverpod, Drift, WebSocket gateway, audio,
  pairing, and chat UI.

## Highest-Value Refactor Targets

### 1. Create a Real Cross-Language Protocol Contract

`UnifiedMessage`, events, content items, routing metadata, statuses, and protocol
versions exist in both Python and Dart by convention. This should become one
canonical contract with strict compatibility tests or generated models.

Review questions:

- Are event names centralized?
- Are content types centralized?
- Is protocol versioning explicit?
- Can Python add an event without silently breaking Flutter?
- Are unknown fields tolerated or rejected intentionally?
- Are request, response, event, and message schemas tested across languages?

### 2. Split the Runtime Message Pipeline Into Explicit Stages

`CommunicationManager` currently validates, routes, acks, adapts, persists,
dispatches requests/events, manages queues, and sends outbound messages.

Target shape:

```text
Channel input
-> Protocol validation
-> Permission/auth policy
-> Ack policy
-> Content adaptation
-> Persistence
-> Agent dispatch / request dispatch / event dispatch
-> Outbound delivery
```

Review questions:

- Can each stage be tested alone?
- Are side effects isolated?
- Is persistence before or after ack intentional?
- Are background tasks supervised?
- Are failed stages reported consistently?
- Can a new content type be added without editing the whole pipeline?

### 3. Introduce a Task/Lifecycle Supervisor

The server starts several infinite coroutines and creates many fire-and-forget
tasks. A shared runtime supervisor would make shutdown, cancellation, and error
handling more predictable.

Review questions:

- Are all tasks named?
- Are all task exceptions observed?
- Can shutdown wait for important tasks?
- Can non-critical tasks fail without killing the server?
- Can critical tasks trigger shutdown or restart?
- Are subprocesses and sockets closed in the right order?

### 4. Extract Message Persistence Into a Repository/Service Layer

`message_store.py` handles channel resolution, text extraction, metadata shaping,
media persistence, DB writes, and channel timestamp updates. Those concerns should
be separated.

Possible target split:

```text
MessageNormalizer
MessageRepository
MediaRepository
ConversationResolver
MessageIngestionService
```

Review questions:

- Is channel resolution duplicated between agent and persistence?
- Is metadata JSON typed anywhere?
- Are media and message DB writes transactionally coherent?
- Are duplicate external IDs idempotent or fatal?
- Can message ingestion be replayed safely?
- Is the Python DB model aligned with the Flutter Drift model?

### 5. Make Conversation/Channel Identity a First-Class Domain Concept

Several places infer a conversation using `channel:sender_id`. That is important
enough to centralize.

Review questions:

- Is "conversation channel" distinct from "transport channel"?
- Is sender, device, and channel identity normalized once?
- Can the system support group chats later?
- Can one device have multiple channels?
- Can one external channel map to multiple local conversations?
- Does the agent thread ID always match the persisted conversation ID?

### 6. Separate Agent Orchestration From Agent Implementation Details

`AgentManager` builds models, resolves preferences, manages memory/checkpointing,
normalizes inputs, invokes LLMs, saves replies, queues outbound messages, and
schedules TTS.

Possible target split:

```text
AgentRuntime
AgentFactory
AgentInputBuilder
AgentReplyService
AgentMemoryService
VoiceReplyService
```

Review questions:

- Can the agent be invoked in tests without running the server?
- Can model selection be changed without touching message handling?
- Is memory tied to the right conversation ID?
- Is TTS a post-processing concern instead of an agent concern?
- Are fallback replies policy-driven?
- Are tool lists injected rather than globally loaded?

### 7. Formalize the Admin Feature Architecture

The admin side has service modules behind the Svelte API.
The opportunity is to make that pattern explicit and avoid leaking CLI/tool
concerns into admin features.

Review questions:

- Do admin services call domain services or CLI tools?
- Are tools only CLI/API adapters, or are they business logic?
- Is each feature using the same state/result/error pattern?
- Are table, form, and dialog components reusable without becoming generic clutter?
- Can admin actions be tested without the browser UI?
- Is workspace selection handled once?

### 8. Unify Command/Tool/Domain Boundaries

There are `commands`, `tools`, `domain`, `runtime`, and `admin` layers. The main
design question is whether `tools` are domain APIs, CLI adapters, or LLM tools.

Review questions:

- Should admin call tools directly?
- Should runtime call tools directly?
- Should LLM tools wrap domain services instead?
- Is every tool safe to expose to an agent?
- Are side-effecting tools permissioned?
- Is there one domain service behind CLI, admin, HTTP, and agent access?

### 9. Move Logging Helpers Out of Runtime Managers

`AgentManager` and `ChannelManager` import logging helpers from
`CommunicationManager`, which couples unrelated managers.

Review questions:

- Are log labels protocol/domain utilities rather than manager internals?
- Are sensitive fields redacted centrally?
- Are message previews length-limited consistently?
- Are log event names structured enough for filtering?
- Can logs be consumed by the admin logs UI reliably?

### 10. Strengthen Gateway/Auth as an Isolated Security Boundary

Gateway auth is small, but the broader trust model should be isolated and heavily
tested.

Review questions:

- Is nonce generation and expiry owned by gateway only?
- Is attestation verification independent from transport code?
- Is revocation checked during active connections?
- Is device identity mapped once after auth?
- Are auth failures represented consistently as permanent or retryable?
- Are security tests separate from general runtime tests?

## Suggested Review Order

1. Define protocol, events, and content contracts.
2. Refactor message pipeline stages.
3. Introduce lifecycle/task supervision.
4. Extract persistence and message ingestion services.
5. Clarify tool, domain, admin, runtime, and CLI boundaries.
6. Clean up individual feature modules after the main shape is clearer.

This order focuses on the codebase shape first. Smaller cleanup should come
after the protocol and pipeline decisions, because those choices affect most
later refactors.
