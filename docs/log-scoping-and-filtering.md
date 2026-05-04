# Log scoping and filtering — by device, message, and request method

> **No-backward-compatibility rule applies** — this is initial development. We are not preserving any prior log filter shape; we change call sites freely. No migration, no wrappers, no compatibility shims.

## 1. Problem statement

The Hiro server emits a large volume of log lines from many layers — `INBOUND`, `MSG_FLOW`, `POST_ADAPT`, `AGENT`, `OUTBOUND`, `RELAY`, `DEVICES` (channel plugin), plus deep internals (STT, TTS, persistence, LangChain). When something interesting happens — a user sends a voice message and gets back a spoken reply — the relevant lines are scattered across all these layers and across multiple processes (gateway, hirocli, channel plugins each have their own `*.log` file).

We want three orthogonal ways to slice the firehose into a calm, focused stream:

1. **By device** — every line of activity related to a single paired device (e.g. "show me everything that happened with `Phone-Sami`").
2. **By message** — every line in the lifecycle of one user message (text or audio in → STT → agent → TTS → reply out → ack/transcript/voiced events).
3. **By request method** — every line for a class of RPC traffic (e.g. every `channels.list`, every `policy.get`), across all devices and all time, useful for debugging the protocol layer itself.

Regular communication that is not part of any of these (e.g. gateway connect/disconnect signals, server startup, cache warming) stays out of those filtered views — it appears only in the unfiltered firehose.

## 2. Design — propagate scoped fields through `contextvars`, render via one structlog processor

The implementation rests on a single primitive: `device_id`, `msg_id`, `method`, and `text_preview` `contextvars.ContextVar` slots populated by a `log_scope(...)` context manager and stamped onto every log event by a structlog processor that already runs as part of the global pipeline.

`contextvars` propagate automatically across `await`, `asyncio.create_task`, and `asyncio.gather`. So once a scope is opened at the natural lifecycle boundary of a message (or request, or device interaction), every log line emitted anywhere downstream — including inside agents, tool calls, persistence, third-party libraries routed through `_StdlibCatchAll` — is stamped with the scope fields, with **zero per-call edits** at those sites.

### 2.1 The scope fields

| Field           | Type       | Set when                                                                                                | Meaning                                                                                                                          |
| --------------- | ---------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `device_id`     | UUID hex   | Inside any device-scoped activity                                                                       | The device this line is *about*. Inbound: `routing.sender_id`. Outbound: `routing.recipient_id`. The non-server end of the hop. |
| `msg_id`        | UUID hex   | `message_type == "message"`, OR `message_type == "event"` with `event.ref_id` set                       | The `routing.id` of the user message (or the `ref_id` it refers to). Stays empty for ambient events with no message context.    |
| `method`        | dotted str | Inbound: JSON-RPC request body `method`. Outbound responses: `routing.metadata["hiro_rpc_method"]` stamped by `EnvelopeFactory`. | The JSON-RPC method, e.g. `"channels.list"`, `"policy.get"`. |
| `text_preview`  | str        | Derive from chat `text` / post-STT `audio` bodies, or ``routing.metadata["hiro_log_text_preview"]`` on correlated outbound envelopes | Single-line truncated user-visible snippet for search and admin UI anchors. **Not** derived from raw JSON-RPC payloads. |

Each field is **independent**. Structured log filters still use `device_id` / `msg_id` / `method` only; `text_preview` is carried in CSV `extras` like the other scope keys.

### 2.1.1 Routing metadata keys (outbound correlation)

Runtime envelopes stamp optional keys on `routing.metadata` so outbound logs match inbound correlation:

- **`hiro_reply_to_msg_id`** (`METADATA_LOG_REPLY_TO_MSG_ID` in `hiro_channel_sdk.log_scope_fields`) — set on agent text replies and voiced-audio events so outbound `msg_id` scope follows the **original user message** (`routing.id`), not only the reply envelope id.
- **`hiro_rpc_method`** (`METADATA_LOG_RPC_METHOD`) — set on JSON-RPC responses by `EnvelopeFactory.response` / `routing_error_response`, because response bodies do not repeat the `method` field.
- **`hiro_log_text_preview`** (`METADATA_LOG_TEXT_PREVIEW`) — set on correlated outbound chat envelopes (`message.received`, `message.transcribed`, voiced replies) so gateway relay logs reuse the same user-visible snippet as hirocli.

Canonical `(device_id, msg_id, method, text_preview)` derivation for both directions lives in **`hiro_channel_sdk.log_scope_fields.unified_message_log_scope`** (single source of truth for pipelines and the channel-devices plugin).

### 2.2 Where the scope is opened

There are four asyncio "task boundaries" the system crosses, and each one re-opens the scope from `routing` because `contextvars` do **not** survive a queue hand-off between tasks. These boundaries are the only places that need a `with log_scope(...)` block:

| Layer                      | File                                                  | Trigger                                               | Scope opened with                                                                                                  |
| -------------------------- | ----------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Inbound dispatch           | `hirocli/runtime/inbound_pipeline.py`                 | every `receive()` call                                | `unified_message_log_scope(msg, direction="inbound")` → `log_scope`                                                                 |
| Channel-devices plugin     | `channels/hiro-channel-devices/.../plugin.py`         | `_handle_gateway_message` after parsing UnifiedMessage | Same inbound derivation as the server — message / `event.ref_id` / RPC method only                                                                 |
| Agent worker               | `hirocli/runtime/agent_manager.py`                    | each loop iteration of `run()` after `inbound_queue.get()` | Same as inbound pipeline for the queued message                                                                                     |
| Outbound dispatch          | `hirocli/runtime/outbound_pipeline.py`                | `enqueue()` and each iteration of worker `run()`     | `unified_message_log_scope(msg, direction="outbound")` — includes queued-line logs and RPC method on responses                         |
| Gateway relay              | `gateway/.../relay.py` `relay_message`                | every relayed envelope                                | Parses payload as ``UnifiedMessage`` when valid → **`unified_message_log_scope(...)`** (inbound/outbound by Hiro desktop sender role); else fallback ids                                                                                                  |

These five sites are the **only** places that touch `log_scope` directly. Every other layer — STT, TTS, persistence hook, tool execution, agent invocation, LangChain internals — is unchanged and inherits the scope automatically because it runs inside an asyncio task spawned within one of the five scopes above.

### 2.3 Why `msg_id` for events also uses `event.ref_id`

`UnifiedMessage` events have an `event.ref_id` field. By convention, when an event is *about* a specific message (`message.received` ack, `message.transcribed` STT mirror, `message.voiced` TTS mirror), the `ref_id` is set to that message's `routing.id`. This is the contract that lets the message-filter view stay calm while still capturing the entire side-effect chain of one message.

Generic events that are not tied to a message (`gateway_connected`, `device_connected`, `pairing_request`, `auth_ok`) leave `ref_id` empty and so do **not** get a `msg_id` scope — they appear under the device filter (since they have a `device_id`) but not under any message filter. That is the intended behavior.

### 2.4 Why three filters, not one combined ID

Each ID answers a different question and has very different cardinality:

- `msg_id` — thousands of distinct values per day, each useful for "show me this single conversation turn"
- `device_id` — handful of values, useful for "show me this user's session"
- `method` — ~5–10 values, useful for "show me this RPC pattern across the whole log"

A single combined "ID" filter would be ambiguous and impossible to populate as a dropdown. Three separate fields are conceptually cleaner and trivially AND-combinable.

## 3. Reading side — what filters look like over CSV logs

The CSV log format (`timestamp,level,module,message,extra`) is unchanged. Scope fields land in the `extra` column as ordinary `key=value` segments alongside whatever the call site explicitly passed. A log line for "agent processing" in the message scope looks like:

```
1742312005.437821,INFO,AGENT,⬇️ Agent processing — Phone-Sami · message[text],device_id=abc... msg_id=def... thread_id=42 character_id=hiro text_preview=hello body_length=5
```

Filtering is implemented in `hirocli/tools/logs.py` as `_apply_scope_filter`, which reads the parsed-row helpers `scope_device_id`, `scope_msg_id`, `scope_method` (populated once per row by `_parse_csv_row`) and AND-combines exact matches.

`LogSearchTool` exposes three optional `device_id`, `msg_id`, `method` parameters that map straight onto this filter. The admin service layer at `hirocli/admin/features/logs/service.py` adds two thin wrappers:

- `LogsService.filter_by_scope(workspace, device_id=…, msg_id=…, method=…)` — runs the search across all sources
- `LogsService.discover_methods(workspace)` — union of **registered** JSON-RPC method names (`REGISTERED_REQUEST_METHOD_NAMES` from `request_methods.py`) and distinct `scope_method` values from the recent tail window (sorted), for dropdown population

## 4. UI requirements (front-end)

The admin Logs page renders a CSV-row table. The new scope-based affordances are:

### 4.1 Filter chips at the top

A horizontal chip strip showing the currently-active filters, each with an `×` to remove. Multiple chips AND-combine. Examples:

- `device: Phone-Sami` (×) `method: channels.list` (×)
- `msg_id: def…` (×)

Adding a chip is done by:

- the device dropdown
- the request-method dropdown
- the per-row message icon (see 4.3)

### 4.2 Two dropdowns

| Dropdown      | Source                                                          | Behavior                                                                  |
| ------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Device        | `DeviceService.list_devices(workspace_id)` (admin/features/devices/service.py) | Lists **approved** devices (workspace-local SQLite, no relay dependency). Each entry shows `device_name`, filters by `device_id`. |
| Request type  | `LogsService.discover_methods(workspace)`                        | Auto-populates from distinct `method` values seen in the recent tail. Sorted alphabetically. |

The device dropdown deliberately uses `DeviceListTool`, **not** `relay.get_connected_devices()`, so the dropdown works in remote-gateway deployments where the gateway is on another machine and hirocli has no relay access. It also includes paired devices that are currently offline.

### 4.3 Per-row message icon column

Add a leftmost narrow gutter column (~24px). For each row, render a chat-bubble icon **only when the row's `scope_msg_id` is non-empty**. Clicking the icon adds a `msg_id: <value>` filter chip (and removes any previous `msg_id` chip).

Rows with no `scope_msg_id` get no icon — keeping the visual scan fast: icon = part of a message lifecycle, no icon = ambient/system traffic.

Hover tooltip on the icon: `Filter to this message`.

### 4.4 No icon for `device_id` or `method`

We deliberately don't add per-row icons for those. The dropdown is the right affordance because:

- `device_id` is a UUID — clicking a UUID cell is a worse UX than picking the friendly name from a dropdown.
- `method` has very low cardinality — the dropdown is ergonomic; a per-row icon would be redundant noise on every RPC line.

If a power-user wants to filter by an arbitrary `device_id` shown in extras, the `extras` panel already supports free-text search via the existing `query` filter.

## 5. Friendly device names — kept where humans read them, not used for filtering

`device_name` (from `ApprovedDevice` and `routing.metadata.device_name`) continues to appear in the **message text** of log lines (e.g. `"⬇️ Message acked, adapter spawned — Phone-Sami"`) via `comm_peer_label()`. This is human-facing only.

Filtering and machine-readable identity always uses `device_id`. Names can collide, change, and are only suggestions; the UUID is the source of truth. The two coexist on the same line: humans read the name, filters use the id.

The relay's `_device_label()` (which produces `"device:abc12345"` when no name is cached) similarly stays in the message text only — the full UUID always appears in `extras` under `device_id` for filtering.

## 6. Cleanup pass — remove redundant scope-duplicating `extras`

Once `_inject_scope` stamps `device_id` / `msg_id` / `method`, repeating those ids as structured-log kwargs becomes noisy duplication.

Implemented removals:

- `comm_extras(..., msg_id=…)` everywhere scope already applies — including **`channel_manager` METHOD_RECEIVE / Sent**, where brief **`log_scope(unified_message_log_scope(...))`** wraps the line when validation succeeds so `_inject_scope` can stamp IDs before inbound/outbound pipelines open their outer scopes.
- In **`gateway/relay.py`** `relay_message`: dropped explicit `sender_id=`, `target_id=`, `recipient_id=`, `msg_id=` extras on relay lines; correlation stays on structured scope keys plus human-readable message text (`sender_label → recipient_label`).
- **`DevicesChannel.send`**: dropped `msg_id` / `recipient` extras after stamping outbound scope around the forward log.

**Still intentional**:

- The friendly `device_name` substring inside the message text (e.g. `comm_peer_label`) — human readability.
- Any `error=`, `elapsed_ms=`, `text_preview=`, `model=`, `voice=`, `count=`, `version=` etc.
- **`channel_manager` Sent / Received** fallbacks when `UnifiedMessage.model_validate` fails — still pass **`msg_id=`-style routing crumbs** because scope cannot be derived reliably.

Previously this sweep was deferred for regression observation; it now lands together with gateway **`unified_message_log_scope`** alignment.

## 7. Files touched / status (initial implementation)

| File                                                     | What it adds                                                            | Status           |
| -------------------------------------------------------- | ----------------------------------------------------------------------- | ---------------- |
| `hiroserver/hiro-commons/src/hiro_commons/log.py`        | `_DEVICE_ID` / `_MSG_ID` / `_METHOD` ContextVars, `_inject_scope` processor in the pipeline, `log_scope()` context manager, `__all__` export | **Done**         |
| `hiroserver/hirocli/src/hirocli/runtime/inbound_pipeline.py` | Wraps `receive()` dispatch in `log_scope(device_id=…, msg_id=…, method=…)` | **Done**         |
| `hiroserver/hirocli/src/hirocli/runtime/agent_manager.py` | Wraps each loop body of `run()` in `log_scope(device_id=…, msg_id=…)`    | **Done**         |
| `hiroserver/hirocli/src/hirocli/runtime/outbound_pipeline.py` | Wraps each iteration of `run()` in `log_scope(device_id=…, msg_id=…)` (handles outbound direction and ref-id-bearing events) | **Done**         |
| `hiroserver/channels/hiro-channel-devices/.../plugin.py` | Wraps `_handle_gateway_message` post-parse in `log_scope(...)` so plugin-process logs share the same fields | **Done**         |
| `hiroserver/gateway/src/hirogateway/relay.py`            | `relay_message`: `log_scope` via **`unified_message_log_scope`** on validated payloads (+ fallback); relay logs omit redundant id extras | **Done**         |
| `hiroserver/hirocli/src/hirocli/tools/logs.py`           | `_extract_scope_fields`, `_apply_scope_filter`, `device_id` / `msg_id` / `method` params on `LogSearchTool`, parsed `scope_*` keys on each row dict | **Done**         |
| `hiroserver/hirocli/src/hirocli/admin/features/logs/service.py` | `LogsService.filter_by_scope`, `LogsService.discover_methods`, `LogsService.search_filtered` (query ∪ scopes → `LogSearchTool`) | **Done**         |
| `hiroserver/hirocli/src/hirocli/admin_svelte/api.py`    | `GET /logs/search` optional `device_id`, `msg_id`, `method`; `GET /logs/methods` → `discover_methods` | **Done**         |
| `hiroleague/admin_frontend` — Logs UI (`LogsPage.svelte`, `api/logs.ts`) | Chips + device/method dropdowns (`listDevices`, `discoverLogMethods`), message icon column → `scope_msg_id`, combined search via extended `/logs/search` | **Done**         |
| Cleanup pass on redundant `extras` (see §6)              | Drop duplicated `msg_id=` / relay device extras — **`channel_manager`/`devices`** scopes wrapped around wired Receive/Send logs where feasible | **Done**         |

## 8. Out of scope (by explicit decision)

- **Per-row clickable icon for `device_id` or `method`.** Rejected — dropdowns are the right affordance for these fields.
- **Cross-device correlation by friendly name.** Friendly names are not unique enough; filter only by `device_id`.
- **Persistent indexes.** All filters are substring/exact-match scans of the existing CSV `extra` column — no separate index needed at current log volumes. Revisit only if scan latency becomes a problem.
- **Tracking of individual request instances by `req_id`.** The current decision is to filter by request *type* (`method`) only. If per-instance request correlation becomes useful later, the same pattern adds a fourth `req_id` ContextVar at minimal cost.

## 9. Verification checklist

After the front-end work (last TODO row) is done, the following should be true end-to-end:

- [ ] Sending a text message from a paired device produces a sequence of log lines all carrying the same `device_id` and `msg_id` across `RELAY`, `DEVICES`, `INBOUND`, `MSG_FLOW`, `POST_ADAPT`, `AGENT`, `OUTBOUND`.
- [ ] Sending an audio message also stamps `device_id` / `msg_id` on the STT layer's lines (verify by looking for the `STT` module entries inside the same message scope).
- [ ] A TTS voiced reply emits a `message.voiced` event whose log lines carry the **original** message's `msg_id` (via `event.ref_id` resolution in the outbound scope).
- [ ] A `channels.list` call from a device produces lines across `RELAY`, `INBOUND`, `REQUEST`, the underlying tool, and `OUTBOUND`, all carrying `method=channels.list`.
- [ ] The admin Logs page device dropdown lists all approved devices regardless of whether the gateway is local or remote (no relay dependency).
- [ ] Clicking the chat-bubble icon on a row pushes a `msg_id` filter and the visible rows immediately collapse to that message's lifecycle only.
- [ ] Removing a filter chip restores the unfiltered view.
- [ ] Selecting `device: X` AND `method: channels.list` shows only that device's `channels.list` round-trips.

## 10. Reflecting build updates

No special steps are required to pick up the back-end changes — they are pure code in `hiro_commons`, `hirocli`, the channels package, and the gateway. A normal `./dev-sync-fast.sh` (or equivalent) is enough. There are no new config files, no schema changes, no workspace migration. The existing `*.log` CSV format is unchanged; old log lines simply lack the new `device_id` / `msg_id` / `method` columns and will not match any of the new filters (which is the correct behavior).
