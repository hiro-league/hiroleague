# Traffic class — operational classification of comm-path log lines

> **No-backward-compatibility rule applies** — initial development, no migrations or wrappers. This doc describes the implementation as it stands; it is not a design memo with options.

## 1. Why this exists

Hiro Server emits comm-path log lines from three processes (`gateway`, `hirocli`, channel plugins) and many layers within hirocli (`INBOUND`, `MSG_FLOW`, `POST_ADAPT`, `AGENT`, `OUTBOUND`, `RELAY`, `CHANNEL_MAN`, `RESOURCE.CHA`, `STREAM_SEND`, …). Every line about a `UnifiedMessage` already carries a human-first first-arg in the shape `{arrow} {action} — {peer} · {kind}` (see `Human-first-structured-logging.mdc`), and every line is scoped on `device_id` / `msg_id` / `method` (see [`docs/log-scoping-and-filtering.md`](./log-scoping-and-filtering.md)).

That works well for two filter dimensions — *which device* and *which message* — but the third one we want is **what kind of hop is happening on this line**, and the existing `comm_kind` string alone can't answer it cleanly:

- `message_type=event` is used for three operationally distinct things: a delivery ack tied to an inbound message (`message.received`), a transcript mirror for an audio message (`message.transcribed`), an audio mirror of a text reply (`message.voiced`), and a free-standing broadcast (`resource.changed`). Direction + type alone cannot tell them apart.
- `message_type=message` outbound is always an agent reply, but inbound it's a user message — same type, very different operational meaning.
- `files.get` produces a request, an ack response, dozens of stream chunks, and a terminal response — all sharing `method=files.get`.
- Channel infrastructure events (`pairing_request`, `gateway_connected`, `device_connected`, …) and channel transport notices (`register`, `disconnect`, "not connected") are not `UnifiedMessage` at all but they appear on the same screen.

`traffic_class` is a stable, controlled-vocabulary string stamped on every comm-path log line — same plumbing as `device_id` / `msg_id` / `method`, with one new concept (producer-stamped routing metadata for outbound disambiguation).

## 2. The taxonomy

Two tiers. Tier-1 is a closed enum, used as a filter chip and a log column. Tier-2 is free-form detail, useful as a column tooltip / sub-filter.

### Tier 1 — `traffic_class` (closed enum)

Defined in `hiro_channel_sdk.log_scope_fields.TRAFFIC_CLASSES`:

| `traffic_class`        | Meaning                                                                                          | Typical Tier-2 (`traffic_subclass`) values         |
| ---------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| `inbound.message`      | Device → Server *user* message (`message_type=message`, inbound).                                | `text`, `audio`, `text,audio`, `image`              |
| `inbound.event`        | Device → Server application event (`message_type=event`, inbound, validated `UnifiedMessage`).   | the `event.type`                                    |
| `inbound.request`      | Device → Server JSON-RPC request (`message_type=request`).                                       | the JSON-RPC method (`channels.list`, `files.get`)  |
| `outbound.response`    | Server → Device JSON-RPC response (success or error).                                            | the JSON-RPC method, or `routing_error`             |
| `outbound.lifecycle`   | Server-originated event tied to an inbound message: `message.received`, `message.transcribed`, `message.voiced`. | the `event.type`                       |
| `outbound.broadcast`   | Server-originated event not tied to a specific inbound message: `resource.changed`.              | the `event.type`                                    |
| `outbound.reply`       | Agent reply for a user message (`message_type=message`, server → device).                        | content shape (`text`, …)                           |
| `stream.chunk`         | A `message_type=stream` frame (per-chunk; today only `files.get` download).                      | the JSON-RPC method                                 |
| `infra.event`          | Raw `channel.event` (no `UnifiedMessage`): `pairing_request`, `gateway_connected`, …             | the event name                                      |
| `infra.transport`      | Channel/plugin lifecycle: `register`, `disconnect`, `not_connected`, `unknown_method`, …         | the action name                                     |

Lines that are **not** comm-path traffic (server startup, cache warming, LangChain internals, STT/TTS service init, etc.) carry **no** `traffic_class`. They appear in the firehose only and are filtered out as soon as any traffic chip is selected.

### Tier 2 — `traffic_subclass`

A short, free-form detail string. Computed alongside Tier 1; same source. Used as the Class column tooltip in the admin logs UI and as a sub-filter once Tier 1 is selected.

## 3. How a line gets classified

There are exactly two paths.

### 3.1 Producer-stamped (outbound only)

For outbound envelopes whose Tier-1 class cannot be inferred from `(direction, message_type, event.type)` alone — specifically, lifecycle vs broadcast vs reply — the **producer is the only one who knows**, so the producer stamps two routing-metadata keys at envelope-build time:

- `METADATA_LOG_TRAFFIC_CLASS = "hiro_traffic_class"`
- `METADATA_LOG_TRAFFIC_SUBCLASS = "hiro_traffic_subclass"`

These join the existing trio of correlation keys (`hiro_reply_to_msg_id`, `hiro_rpc_method`, `hiro_log_text_preview`) on `routing.metadata`. They flow with the envelope through the outbound pipeline, the channel manager, the channel plugin, the gateway relay, and the device — every log site downstream just reads them.

| Producer site                               | `traffic_class`        | `traffic_subclass`            |
| ------------------------------------------- | ---------------------- | ----------------------------- |
| `EnvelopeFactory.ack_event`                 | `outbound.lifecycle`   | `message.received`            |
| `EnvelopeFactory.transcript_event`          | `outbound.lifecycle`   | `message.transcribed`         |
| `EnvelopeFactory.resource_changed_event`    | `outbound.broadcast`   | `resource.changed`            |
| `EnvelopeFactory.response`                  | `outbound.response`    | the JSON-RPC method           |
| `EnvelopeFactory.routing_error_response`    | `outbound.response`    | `routing_error`               |
| `EnvelopeFactory.stream_chunk`              | `stream.chunk`         | the JSON-RPC method           |
| `AgentManager._make_reply`                  | `outbound.reply`       | content shape (`text`)        |
| `AgentManager` voiced event (TTS mirror)    | `outbound.lifecycle`   | `message.voiced`              |

### 3.2 Inferred (deterministic)

For inbound envelopes — and for outbound envelopes where the producer didn't stamp anything — `_classify_traffic()` in `hiro_channel_sdk/log_scope_fields.py` derives `(traffic_class, traffic_subclass)` purely from `(direction, message_type, event.type, content)`. The mapping is summarized in §2 above; see the function for the exact branching.

The fallback for unstamped outbound events uses `event.ref_id` as a strong-but-imperfect proxy: lifecycle events always carry a `ref_id` to the original message, while `resource.changed` does not. This keeps gateway-only views (where there's no producer to stamp) sensible, but production code paths always go through the producer-stamp path so the result is exact.

## 4. Where it's plumbed

`unified_message_log_scope()` returns a 6-tuple:

```python
(device_id, msg_id, method, text_preview, traffic_class, traffic_subclass)
```

Every place that already opens a `log_scope(...)` for a `UnifiedMessage` was updated to thread the two new fields through. These are the same five sites listed in [`docs/log-scoping-and-filtering.md`](./log-scoping-and-filtering.md) §2.2:

- `hirocli/runtime/inbound_pipeline.py` — `receive()`
- `hirocli/runtime/outbound_pipeline.py` — `enqueue()` and worker `run()`
- `hirocli/runtime/channel_manager.py` — `METHOD_RECEIVE` branch and `send_to_channel`
- `hirocli/runtime/agent_manager.py` — per-message scope inside the agent loop
- `gateway/src/hirogateway/relay.py` — `relay_message`
- `channels/hiro-channel-devices/src/hiro_channel_devices/plugin.py` — gateway-side log_scope

`contextvars` propagate the scope across `await` / `asyncio.create_task` / `asyncio.gather`, so every downstream log line — including ones in deep internals, third-party libraries, persistence hooks — inherits `traffic_class` for free.

### Infra log sites (no `UnifiedMessage`)

Infra lines don't have a `UnifiedMessage` to derive from, so we open small explicit scopes at the call sites in `ChannelManager` and `ChannelEventHandler` dispatch:

- `METHOD_EVENT` notification → `infra.event` / `traffic_subclass=event_name`
- channel `register` → `infra.transport` / `register`
- channel `disconnect` → `infra.transport` / `disconnect`
- `connection_closed`, `connection_error` → `infra.transport` / matching subclass
- `unknown_method` from a channel → `infra.transport` / `unknown_method`
- `Cannot send to (...) — not connected` → `infra.transport` / `not_connected`

The `infra.event` scope wraps the dispatch *and* the registered handler call, so the downstream log lines from `InfraEventHandlers` (gateway-connected/disconnected, device-connected/disconnected, pairing) inherit the chip.

## 5. CSV / log-row schema

Two new keys appear in the `extra` column of every comm-path log line: `traffic_class=...` and `traffic_subclass=...`. They join the existing `device_id`, `msg_id`, `method`, `text_preview` keys.

`hirocli/tools/logs.py` parses them out into row fields:

- `scope_traffic_class` — exact-match filterable
- `scope_traffic_subclass` — informational

`LogSearchTool.execute` accepts `traffic_class: str | list[str]` (comma-separated string or list); the filter is OR-within (any-of), AND with the other scope filters.

## 6. Admin API

| Endpoint                       | What it returns                                                                                       |
| ------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `GET /logs/traffic-classes`    | Static enum: the 10-value `TRAFFIC_CLASSES` tuple. No log-tail scan; the enum is closed.              |
| `GET /logs/search`             | New optional `traffic_class` query param (comma-separated). AND'd with `device_id`/`msg_id`/`method`. |
| `GET /logs/methods`            | Unchanged. Still returns RPC method names; methods are now a sub-cut under `inbound.request` / `outbound.response` / `stream.chunk`. |

## 7. Admin UI

`admin_frontend/src/lib/features/logs`:

- `LogsFiltersPanel.svelte` — new **Traffic** chip group spanning the full row, multi-select, with a clear-x button.
- `LogsTablePanel.svelte` — new **Class** column between Source and Module. Renders `scope_traffic_class` as a colored pill (cool=in, warm=out, violet=stream, neutral=infra) with `{class} · {subclass}` in the tooltip.
- `state/logs-preferences.svelte.ts` — `trafficClassFilter: TrafficClass[]` is session-persisted next to the existing scope prefs.
- `state/logs-controller.svelte.ts` — included in `hasScopeFilters`, blocks live tail when active, passed into `searchLogs`.
- `lib/api/logs.ts` — `TRAFFIC_CLASSES` enum + `TrafficClass` type mirror the backend.
- `lib/features/logs/shared/logs-ui.ts` — `TRAFFIC_CLASS_LABELS` (short chip labels) and `trafficClassChipClass(tc)` (color rule).

## 8. Adding a new traffic class

If you genuinely need a new Tier-1 class (the existing 10 cover today's runtime — adding one is rare), do exactly this:

1. Add a `TRAFFIC_CLASS_FOO` constant to `hiro_channel_sdk/log_scope_fields.py` and append it to the `TRAFFIC_CLASSES` tuple. Export it from `__all__`.
2. Stamp it at the **producer site** via `routing.metadata[METADATA_LOG_TRAFFIC_CLASS] = TRAFFIC_CLASS_FOO` (and a Tier-2 subclass if useful), or — for non-`UnifiedMessage` infra paths — open a small `log_scope(traffic_class=TRAFFIC_CLASS_FOO, traffic_subclass=...)` block at the log site.
3. If the inference path matters (e.g. for gateway-only views where producer stamping isn't available), update `_classify_traffic()` in the same file. Otherwise leave the inference fallback alone — the producer stamp wins.
4. Add the chip color rule for the new class in `admin_frontend/src/lib/features/logs/shared/logs-ui.ts::trafficClassChipClass`, and a label in `TRAFFIC_CLASS_LABELS`. Mirror the new value in `admin_frontend/src/lib/api/logs.ts::TRAFFIC_CLASSES`.
5. Add a unit test in `hiro-channel-sdk/tests/test_log_scope_fields.py` asserting both the producer-stamp path and the inference fallback for the new class.

You do **not** need to touch `LogSearchTool`, the API endpoint, the filter chip group, the table column, or any of the five comm-path log_scope call sites — those are all class-agnostic.

## 9. What this is *not*

- It is not a replacement for `method`. The JSON-RPC method filter is still the right tool for "show me all `policy.get` traffic regardless of which hop"; `traffic_class` says *which kind of hop*.
- It is not a replacement for `device_id` or `msg_id`. Those answer "who" and "which user message"; `traffic_class` answers "what kind of step in the protocol".
- It does not change the human-first first-arg of any log line. The chip lives in `extras` / the table column only — the operator-readable message string is unchanged.
- It does not introduce a new transport key. `routing.metadata.hiro_traffic_class` is for log scoping, mirroring `hiro_rpc_method` and `hiro_log_text_preview`. It is not part of the wire contract for application semantics.

## 10. See also

- [`docs/log-scoping-and-filtering.md`](./log-scoping-and-filtering.md) — the device / message / method scoping primitives this builds on.
- `hiro_channel_sdk/log_scope_fields.py` — single source of truth for derivation.
- `hirocli/runtime/envelope_factory.py` — every server-originated stamp lives here (plus the two `AgentManager` builders for reply / voiced).
- `hiro-channel-sdk/tests/test_log_scope_fields.py` — golden cases for both inference and producer-stamp paths.
