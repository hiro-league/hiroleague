# File Communication — implementation design

> Status: Draft · Audience: AI coding agent (and human reviewers) implementing
> the day-one server↔device file transfer substrate. Companion to
> `docs/file-communication.md` (the longer engineering note explaining the
> trade-offs) and `docs/resource-sync.md` (the events-are-hints / requests-are-truth
> substrate this layers on).

This document describes **what to build**, **where to build it**, and **how
each piece behaves on the wire**. It is the implementation-ready spec for
the day-one File Communication feature.

We follow workspace rules: **no backward compatibility, no migrations, no
wrappers**. Everything below describes the desired end state.

---

## 1. What this feature delivers

A single substrate that moves binary content between Hiro Server and
connected devices over the existing gateway WebSocket.

**Day-one applications (Phase 1 in §9):**

1. **Character photo on device.** A device pulls `characters.list`,
   sees a per-row photo reference, and downloads the bytes for any
   character whose photo it does not yet have cached.
2. **Channel photo on device.** A device pulls `channels.list`. Each
   channel row carries the `character_id` of the character associated
   with the channel; the device looks up the cached character photo by
   that id and renders it as the channel's photo. **No new bytes path
   is needed for channel photos** — the channel row references the
   character, and the character's photo flows through the same path
   as application 1.

Other applications (message-history attachments, user-attached files
in agent messages, etc.) are designed for and supported by the same
substrate, but their **device-side wiring is deferred** to future
phases (see §10). The wire shape, references, blob store, chunker,
and receiver are designed to handle them without protocol changes
when those phases land.

There is **no device-to-device transfer**. The server is always the
storage and authority point.

Out of scope on day one: per-chunk resume (only retry-on-failure),
per-session quotas, server-side compression negotiation, multi-resolution
photo profiles, true WebSocket binary frames. These are documented as
future options in `docs/file-communication.md` §4.3 and §7.

---

## 2. Topology constraints

```
device (Flutter)  ─ws─►  Hiro Gate (relay)  ─ws─►  Hiro Server (hirocli)
                  ◄───                       ◄───
```

Three properties from the live code that constrain the design — do not
fight them:

- The gateway relay (`hiroserver/gateway/src/hirogateway/relay.py:relay_message`)
  is a **stateless JSON forwarder**. It re-serializes every relayed frame
  and treats `payload` as opaque. It cannot route binary frames or peek
  inside non-JSON payloads.
- Both sides use the `websockets` library with **no `max_size` override**
  (`hiroserver/gateway/src/hirogateway/main.py:_serve` and
  `hiroserver/channels/hiro-channel-devices/src/hiro_channel_devices/plugin.py:_run_gateway_connection`).
  That pins the per-frame ceiling at the library default of **1 MiB**.
  A single JSON envelope must fit inside that.
- `MESSAGE_TYPE_STREAM` is **already reserved** in
  `hiroserver/hiro-channel-sdk/src/hiro_channel_sdk/constants.py:57` and
  `models.py:93,136`. The validator branch exists as a no-op. We are
  un-reserving it, not introducing it.

Day-one transport is therefore JSON over WebSocket with binary chunks
encoded as **base64 inside `ContentItem.body`**. A future upgrade to
true WS binary frames is documented elsewhere and is **not** part of
this design.

---

## 3. Concepts

| Concept | Definition |
|---|---|
| **Blob** | An immutable byte sequence identified by its `sha256`. Stored on the server under `<workspace>/data/blobs/<aa>/<sha256>`, where `<aa>` is the first two hex chars of the sha. |
| **Reference** | A typed string (e.g. `character_photo:hiro`) that the server resolves to a blob. The resolver is the single auth + lookup choke point. |
| **Manifest** | The metadata returned by `files.head`: `blob_id`, `size`, `media_type`, `chunk_size`, `chunk_count`. |
| **Stream session** | An ordered sequence of `MESSAGE_TYPE_STREAM` frames carrying chunks of one blob, correlated by the originating request's `request_id`. |
| **Chunk** | One slice of a blob. Default raw size is **48 KB** (`49152`). Advertised in `files.head` so the device never hard-codes it. |
| **Session lifecycle** | `request → ack response → N stream frames → terminal response`. Always exactly one ack and one terminal per session. |

---

## 4. Reference namespace

A reference is a typed string handed to `files.head`, `files.get`, or
embedded in stored message attachments. Resolved server-side; the
device never needs to know where bytes physically live.

Day-one shape is colon-separated:

```
<kind>:<id>[:<sub>]
```

| Reference | Resolves to | Resolver behavior |
|---|---|---|
| `character_photo:<character_id>` | The canonical photo file for a character. | Wraps `hirocli/domain/character.py::resolve_character_photo_file_for_http`. Falls back to the packaged default avatar when no upload exists. Server enforces ≤ 2 MB at upload time (downscale, never refuse). |
| `message_attachment:<msg_id>:<idx>` | The N-th (0-indexed) attachment on a stored message. | Looks up the message row, returns the blob_id stored in the N-th attachment slot. Generalizes the existing `hirocli/domain/media_store.py` save path. |
| `blob:<sha256>` | A blob addressed directly by content hash. | Used immediately after upload, before any logical reference exists. The server returns it from `files.put.head`'s terminal response. |

The resolver is the **only** place that decides whether a given
authenticated device may fetch a given blob. Today the policy is "any
authenticated device, any blob." We add no other policy on day one,
but the choke point exists so per-user scoping (foreseen in
`DeviceTargeting`) drops in without protocol changes.

Adding a new reference kind later is a one-line registration in the
resolver plus a `ResourceRegistry` entry that bumps the relevant
resource version when the underlying artifact changes.

---

## 5. Wire shape

### 5.1 `files.head` — discover a blob

Caller asks: *"What does this reference point to?"* This call is
optional when the caller already has a `blob_id` from a previous
response (e.g. inline in a `messages.history` row).

```jsonc
// request — message_type:"request", content_type:"json"
{
  "method": "files.head",
  "params": { "ref": "character_photo:hiro" }
}

// response — message_type:"response"
{
  "status": "ok",
  "data": {
    "blob_id":     "sha256:9f3a...",
    "size":        524288,
    "media_type":  "image/png",
    "chunk_size":  49152,
    "chunk_count": 11
  }
}
```

Errors (non-exhaustive): `ref_not_found`, `ref_invalid`, `forbidden`.

### 5.2 `files.get` — download a blob

```jsonc
// request
{
  "method": "files.get",
  "params": { "blob_id": "sha256:9f3a..." }
}

// 1) ack response — fast, before any chunks
{
  "status": "ok",
  "data": {
    "session_id":  "<echo of the request's request_id>",
    "chunk_count": 11
  }
}

// 2) N stream frames (see §5.4), each with the same request_id

// 3) terminal response
{
  "status": "ok",
  "data": {
    "blob_id": "sha256:9f3a...",
    "size":    524288
  }
}
```

The receiver verifies that the sha of the assembled bytes equals the
sha portion of `blob_id` before accepting the file.

### 5.3 `files.put.head` — upload (device → server)

```jsonc
// request
{
  "method": "files.put.head",
  "params": {
    "size":       384210,
    "sha256":     "ab12...",
    "media_type": "image/jpeg",
    "ref_hint":   "message_attachment:<msg_id>:0"   // optional
  }
}

// 1) ack response
{
  "status": "ok",
  "data": {
    "session_id":  "<echo of the request's request_id>",
    "chunk_size":  49152,
    "chunk_count": 8
  }
}

// 2) device sends 8 stream frames with request_id == session_id

// 3) terminal response from the server
{
  "status": "ok",
  "data": {
    "blob_id": "sha256:ab12...",
    "ref":     "blob:ab12..."
  }
}
```

`ref_hint` is advisory — the server returns the canonical reference it
actually assigned (almost always `blob:<sha>` on day one), which the
caller uses afterwards (e.g. embedding it in the chat message it is
about to send).

### 5.4 Stream frame

A stream frame is a `UnifiedMessage` with `message_type: "stream"`,
exactly one `ContentItem` of `content_type: "file"`, and the chunk
metadata in `ContentItem.metadata`:

```jsonc
{
  "version":      "0.1",
  "message_type": "stream",
  "request_id":   "<session_id from the ack>",
  "routing":      { /* normal MessageRouting fields */ },
  "content": [
    {
      "content_type": "file",
      "body": "<base64 of one chunk>",
      "metadata": {
        "blob_id": "sha256:9f3a...",
        "seq":     3,
        "final":   false
      }
    }
  ]
}
```

Required `metadata` keys: `blob_id` (string), `seq` (int ≥ 0), `final`
(bool). The frame with `final: true` is the last one of the session;
the terminal `response` frame follows immediately.

### 5.5 Chunk sizing budget

- Default raw chunk size: **48 KB (49152 bytes)**. After base64
  inflation that is ~64 KB; with the JSON envelope the wire frame is
  ~64–65 KB. ~16× headroom under the 1 MiB WS cap.
- The chunker **must** respect the `chunk_size` advertised in the ack
  response. The receiver **may** pre-allocate buffers using
  `chunk_count × chunk_size`.
- Maximum encoded WS frame budget: **256 KB**. Fail loudly if anything
  in the pipeline tries to emit a larger one.

---

## 6. Failure handling

Day-one policy is **retry on failure, no resume**.

| Failure | Behavior |
|---|---|
| WebSocket disconnects mid-session (either direction) | The originating request (`files.get` / `files.put.head`) is treated as idempotent. After the gateway client reconnects, the device re-issues it from `seq = 0`. Any `<sha>.partial` file from the previous attempt is discarded. |
| Final sha mismatch | Receiver discards the assembled bytes and reports the request as failed. Caller surfaces a retryable error. |
| Per-chunk decode error (bad base64, missing metadata) | Receiver aborts the session, logs the offending `seq`, and treats it as a transient failure. |
| Frame > 1 MiB | Sender bug; `websockets` will close the socket with code 1009 on the receiver side. The chunker must respect `chunk_size` to make this impossible in practice. Log loudly if it ever triggers. |
| `ref_not_found` / `ref_invalid` / `forbidden` on `files.head` | Error response; no session opened. UI surfaces the error; no retry. |
| Server out of disk on upload | Terminal response carries `status: "error"`; the `.partial` file is removed. Caller treats as retryable later (on the user's action), not automatically. |

Server-side rule for uploads: bytes are written to
`<workspace>/data/blobs/<aa>/<sha>.partial` as they arrive and only
**atomically renamed** to `<workspace>/data/blobs/<aa>/<sha>` after the
final sha matches. Half-finished uploads leave no entry in the blob
directory.

The wire shape is intentionally compatible with a future resume
(`offset` parameter on `files.get`, persisted highest-contiguous `seq`
on the device). That work is deferred until real usage shows it is
worth the complexity.

---

## 7. Day-one scenarios — end-to-end flows

### 7.1 Character photo on device

Trigger: device pulls `characters.list` on initial sync or after a
`resource.changed` hint for the `characters` resource.

```
device                         server
  │                               │
  │── characters.list ───────────►│
  │◄── { rows: [
  │       { id:"hiro",
  │         photo_ref:"character_photo:hiro",
  │         photo_blob_id:"sha256:9f3a...",
  │         ... }, ... ] } ──────│
  │                               │
  │  (for each row whose photo_blob_id changed vs. cache)
  │── files.get(blob_id) ────────►│
  │◄── ack { session_id, chunk_count:1 } ─│
  │◄── stream(seq:0, final:true) ─│
  │◄── terminal response ─────────│
  │   verify sha; write atomically │
  │   to app-docs/character_photos/hiro.png
```

Notes:

- `characters.list` returns both `photo_ref` and `photo_blob_id` so the
  device can short-circuit `files.head`. Devices cache
  `(photo_blob_id → bytes)`; comparing blob_ids is the etag check.
- For ≤ 2 MB photos, this is a single-chunk transfer. No special
  single-shot RPC; the chunked path handles it cleanly.
- No event-driven push. Photos refresh when `resource.changed` for the
  `characters` resource arrives, the device re-pulls the list, and the
  blob_id diff drives the fetch.

### 7.2 Channel photo on device

Trigger: device pulls `channels.list` on initial sync or after a
`resource.changed` hint for the `channels` resource.

```
device                         server
  │                               │
  │── channels.list ─────────────►│
  │◄── { rows: [
  │       { id:42,
  │         name:"#general",
  │         character_id:"hiro",
  │         ... }, ... ] } ───────│
  │                               │
  │  (no extra fetch — the device looks up
  │   the cached character photo by character_id
  │   from scenario 7.1 and renders it as the
  │   channel's photo. If the character photo
  │   is not yet cached, scenario 7.1 will
  │   trigger it on the next characters.list
  │   refresh.)
```

Notes:

- `channels.list` carries **`character_id` only** — no photo bytes,
  no blob_id, no `photo_ref`. The channel row is a thin reference;
  photo metadata lives on the character row.
- This keeps `channels.list` small and avoids duplicating photo
  invalidation logic. When a character's photo changes, only the
  `characters` resource version bumps; channel rendering picks up
  the new bytes the next time the device's render path reads from
  the character cache.
- If a channel needs a photo **independent** of any character (e.g.
  a custom channel icon uploaded without an associated character),
  add a `channel_photo:<channel_id>` reference kind in a future
  phase. Day one does not do this.

### 7.3 Future scenario — message history reload with attachments

> **Future phase, not day one.** Wire shape and references are
> already defined; only the `messages.history` response shape and
> device-side fetch queue are deferred.

Trigger: device opens a channel and calls `messages.history(channel_id)`.

```
device                         server
  │                               │
  │── messages.history(ch_id) ───►│
  │◄── { messages: [
  │       { id:"m1", content:[
  │           { content_type:"text", body:"see attached" },
  │           { content_type:"image",
  │             body:"message_attachment:m1:0",
  │             metadata:{
  │               blob_id:"sha256:ab12...",
  │               size:384210,
  │               media_type:"image/jpeg",
  │               chunk_count:8,
  │               filename:"photo.jpg"
  │             } }
  │         ] }, ... ] } ─────────│
  │                               │
  │  (device deduplicates blob_ids across messages,
  │   queues fetches with bounded concurrency)
  │── files.get(sha256:ab12...) ─►│
  │◄── ack ───────────────────────│
  │◄── stream × 8 ────────────────│
  │◄── terminal ──────────────────│
  │   write atomically to
  │   app-docs/blobs/ab/ab12.../jpeg
  │   message m1's attachment 0 now renders
```

Notes (apply when this phase lands):

- `messages.history` returns blob metadata **inline** so the device
  doesn't need a `files.head` round-trip per attachment. This is the
  one place we cheat slightly on substrate purity for latency reasons.
- Device-side concurrency is bounded (suggested: 3 parallel
  `files.get` per channel) to keep the gateway unsaturated.
- Aggregate progress UI is the device's responsibility — count
  completed-vs-pending blob fetches from the queue, not from inside
  any individual session.

### 7.4 Future scenario — user sends an agent message with attachments

> **Future phase, not day one.** Wire shape and references are
> already defined; only `files.put.head`, the device-side stream
> sender, and the composer flow are deferred.

Trigger: user composes a message in the device app and adds N files.

```
device                         server
  │                               │
  │  for each attachment:         │
  │── files.put.head(size, sha,   │
  │                  media_type) ►│
  │◄── ack { session_id,          │
  │           chunk_size,         │
  │           chunk_count } ──────│
  │── stream × chunk_count ──────►│
  │◄── terminal { blob_id, ref } ─│
  │                               │
  │  collect refs[];              │
  │  build UnifiedMessage:        │
  │    content = [
  │      { content_type:"text",
  │        body: user_text },
  │      { content_type:"image",
  │        body: ref0,
  │        metadata:{
  │          filename, media_type } },
  │      { content_type:"file",
  │        body: ref1,
  │        metadata:{ ... } },
  │      ...
  │    ]
  │── send message ──────────────►│
  │                               │  (Communication Manager
  │                               │   stores message + refs;
  │                               │   agent reads attachments
  │                               │   via files.get on the same
  │                               │   in-process resolver)
```

Notes (apply when this phase lands):

- The chat message is sent **only after all uploads succeed**. Failed
  uploads are surfaced in the composer; the message is not sent until
  the user resolves them or removes the failing attachments.
- `ContentItem.body` carries the **reference string**, not bytes. This
  keeps stored messages small and makes re-fetch from another device
  trivial (scenario 7.3).
- The agent reads attachments through the same `files_resolver` that
  serves `files.get`. No special in-process bypass; one path for
  bytes.

---

## 8. Where the code lives

### 8.1 Server (Python — `hiroserver/hirocli/`)

| Concern | Module |
|---|---|
| RPC entry points | `hirocli/runtime/request_methods.py` — register `files.head`, `files.get`, `files.put.head` alongside the existing `channels.list`, `messages.history`, `policy.get`. |
| Tools (per `consider-creating-tools-first.mdc`) | New `hirocli/tools/files.py` — `FilesHeadTool`, `FilesGetTool`, `FilesPutHeadTool`. Same pattern as `ConversationChannelListTool`. |
| Reference resolver | New `hirocli/domain/files_resolver.py` — `resolve(ref) → BlobHandle`. One dispatch table keyed by `<kind>`. |
| Blob store on disk | New `hirocli/domain/blob_store.py` — `read(blob_id)`, `open_writer(expected_sha) → BlobWriter`, `finalize(writer) → blob_id`. Generalizes the existing `hirocli/domain/media_store.py`. Path layout: `<workspace>/data/blobs/<aa>/<sha>` and `<sha>.partial` during writes. |
| Outbound chunker | New `hirocli/runtime/stream_sender.py` — `async def send_blob(handle, request_id, routing) -> None`. Reads the file in `chunk_size` slices, base64-encodes, builds a `UnifiedMessage` per chunk via `EnvelopeFactory.stream_chunk(...)` (also new), pushes through the existing outbound channel. |
| Inbound chunker | New `hirocli/runtime/stream_receiver.py` — keyed by `request_id`. Routes incoming `message_type: "stream"` frames to the active session, persists each chunk to `<sha>.partial`, finalizes on `final: true`. |
| Wiring into Communication Manager | The inbound pipeline gains a small dispatcher: if `message_type == "stream"`, route to `stream_receiver` instead of the normal message-handling path. |

### 8.2 Device (Dart — `device_apps/`)

| Concern | Module |
|---|---|
| RPC client calls | `data/remote/gateway/gateway_request_client.dart` — add `filesHead`, `filesGet`, `filesPutHead` methods. |
| Stream frame plumbing | The existing inbound dispatcher in the gateway notifier learns to route `message_type: "stream"` frames to a `StreamReceiver` keyed by `request_id`. |
| Stream sender | New `application/files/stream_sender.dart` — chunks a local file into `chunk_size` slices, base64-encodes, sends one `UnifiedMessage` per chunk. |
| Stream receiver | New `application/files/stream_receiver.dart` — accepts frames by `request_id`, writes to `<app-docs>/blobs/<aa>/<sha>.partial`, verifies sha on `final`, atomic rename. |
| Blob cache on disk | New `application/files/blob_cache.dart` — wraps `<app-docs>/blobs/<aa>/<sha>` storage. Provides `path(blob_id) → File`. Per-feature index files (e.g. `character_photos/<id>` symlink or table row) live in their own modules. |
| Aggregate progress UI | Inside whatever feature triggers a multi-blob pull (e.g. message history reload). The substrate does not aggregate; it exposes per-session events the feature subscribes to. |

### 8.3 Protocol surface (`hiroserver/hiro-channel-sdk/`)

The `UnifiedMessage` validator in `models.py` currently has a no-op
branch for `MESSAGE_TYPE_STREAM` (line 136-137). Replace it with:

- `request_id` is required and non-empty.
- `event` must be `None`.
- `content` must contain exactly one `ContentItem`.
- That item's `content_type` must be `"file"`.
- That item's `metadata` must contain `blob_id` (str), `seq` (int ≥ 0),
  `final` (bool).

Mirror these constraints in the Dart `UnifiedMessage` model so both
sides reject the same invalid fixtures.

No new event types. `resource.changed` already covers cache
invalidation for the resources whose photos / attachments live behind
references.

### 8.4 Logging — visibility, levels, and what to log

Visibility is a first-class feature for File Communication.
Transferring bytes between server and device is one of the few
operations that can fail in many small ways (mid-transfer
disconnect, sha mismatch, partial write, missing reference, blob
too large), and operators need to be able to see what happened
without fishing for it. At the same time, a single transfer can
produce **hundreds of stream frames**, and per-chunk noise at INFO
would drown the unfiltered firehose described in
`docs/log-scoping-and-filtering.md`.

The rule, applied across all File Communication code:

> **INFO logs the milestones (one line per session boundary).
> DEBUG logs the chunks. WARNING/ERROR logs the failures.**

This rule applies to any future feature in this codebase as well —
file communication is the canonical example, not a special case.

#### 8.4.1 Log levels — one table

| Event | Level | Where it logs | Example message string |
|---|---|---|---|
| Inbound `files.head` / `files.get` / `files.put.head` request received | `INFO` | `request_methods.py` (`REQUEST` module) | `⬇️ Resource served — request:files.get` |
| Outbound session opened (chunker about to start) | `INFO` | `stream_sender.py` (`STREAM_SEND` module) | `⬆️ Stream session opened — device:abc123 · files.get` |
| Per-chunk send | `DEBUG` | `stream_sender.py` | `⬆️ Stream chunk sent — device:abc123 · seq=3/11` |
| Per-chunk receive | `DEBUG` | `stream_receiver.py` (`STREAM_RECV` module) | `⬇️ Stream chunk received — HiroServer · seq=3/11` |
| Outbound session completed (terminal response sent) | `INFO` | `stream_sender.py` | `✅ Stream session completed — device:abc123 · files.get` |
| Inbound session completed (sha verified, file finalized) | `INFO` | `stream_receiver.py` | `✅ Stream session completed — HiroServer · files.get` |
| Sha mismatch on finalize | `ERROR` | `stream_receiver.py` | `❌ Stream sha mismatch — HiroServer · files.get` |
| Disconnect mid-session (sender side) | `WARNING` | `stream_sender.py` | `⚠️ Stream session aborted — device:abc123 · files.get` |
| Disconnect mid-session (receiver side, partial discarded) | `WARNING` | `stream_receiver.py` | `⚠️ Stream session aborted — HiroServer · files.get` |
| Reference resolution failure (`ref_not_found`, `forbidden`) | `WARNING` | `files_resolver.py` (`FILES` module) | `⚠️ Reference rejected — character_photo:hiro · forbidden` |
| Blob writer atomic rename | `DEBUG` | `blob_store.py` (`BLOBS` module) | `Blob finalized — sha256:ab12...` |

All of the above lines automatically inherit the
`(device_id, msg_id, method, text_preview)` scope established by
the inbound / outbound pipelines (see
`docs/log-scoping-and-filtering.md` §2.2). Concretely: every line
emitted during a `files.get` session — including the per-chunk
DEBUG lines — carries `method=files.get` and the device's
`device_id`. That is what makes "show me everything that happened
during this transfer" a one-click filter in the admin Logs UI.

#### 8.4.2 Required structured extras

Per `Human-first-structured-logging.mdc`: the **first argument** is
the human-readable summary; **structured extras** carry the
machine-readable fields, readable first then opaque. For File
Communication:

| Log site | Structured extras (in order) |
|---|---|
| Session-open / -complete (INFO) | `chunk_count`, `size`, `media_type`, `elapsed_ms` (on complete), `blob_id` |
| Per-chunk (DEBUG) | `seq`, `final`, `chunk_bytes`, `blob_id` |
| Sha mismatch (ERROR) | `expected_sha`, `actual_sha`, `bytes_received`, `blob_id` |
| Disconnect (WARNING) | `seq_last_seen`, `chunk_count`, `error`, `blob_id` |
| Reference failure (WARNING) | `ref`, `reason` (and `error` if exception) |

`elapsed_ms` is required on every session-complete and every
external-call wrapping log (sha computation over a large blob, file
writes that hit slow disks, etc.) per the workspace rule.

#### 8.4.3 Relay logging

The gateway relay's existing `_relay_kind` already produces
`"stream"` from `message_type`. Extend `_relay_content_hint` (in
`hiroserver/gateway/src/hirogateway/relay.py`) so stream frames
surface their `seq` / `final` from the first content item's
metadata:

```
⬇️  Message relayed — device:abc123 → HiroServer · stream  (seq=3 final=false blob=ab12…)
```

The relay logs **every** relayed frame at its existing default
level. To avoid drowning the relay log during a large transfer,
move stream-frame relay lines to `DEBUG`. Session boundaries are
already visible at INFO via the `request` and `response` lines on
the same `request_id`.

#### 8.4.4 Why this matters beyond File Communication

The same rule — **milestones at INFO, internal events at DEBUG,
anomalies at WARNING/ERROR, with `elapsed_ms` on completed
operations** — applies to every feature in this codebase. The UI
must stay scannable at INFO; DEBUG is where the per-chunk,
per-token, per-iteration detail lives. Operators turn DEBUG on for
a single module when they need it; the unfiltered INFO firehose
must remain calm.

---

## 9. Day-one phase

The day-one scope is the **server-to-device download substrate**
plus the **character / channel photo wiring** that consumes it.
Everything in §10 is deferred.

### Phase 1 — Server-to-device download + character / channel photos

Goal: scenarios 7.1 and 7.2 work end-to-end. A device opening the
app sees character and channel photos that were uploaded on the
desktop, and they refresh when changed.

Implements:

- **Protocol surface:** `MESSAGE_TYPE_STREAM` validator constraints
  in both the Python `UnifiedMessage` (`hiro-channel-sdk/.../models.py`)
  and the Dart `UnifiedMessage` model. No new event types.
- **Server substrate:**
  - `hirocli/domain/blob_store.py` (read path only; no writer yet).
  - `hirocli/domain/files_resolver.py` with the `character_photo:`
    resolver entry, wrapping the existing
    `hirocli/domain/character.py::resolve_character_photo_file_for_http`.
  - `hirocli/tools/files.py` — `FilesHeadTool`, `FilesGetTool`.
  - `files.head` and `files.get` request methods registered in
    `hirocli/runtime/request_methods.py` alongside the existing
    `channels.list`, `messages.history`, `policy.get`.
  - `hirocli/runtime/stream_sender.py` — outbound chunker.
  - `EnvelopeFactory.stream_chunk(...)` helper.
  - Inbound-pipeline branch in Communication Manager: if
    `message_type == "stream"`, route to a (placeholder) handler
    that simply rejects with a clear log line — the receive path
    is not exercised in Phase 1, but the dispatcher is in place so
    Phase F2 can land without re-touching Communication Manager.
- **Server resource integration:**
  - `characters.list` response includes `photo_ref` and
    `photo_blob_id` per row.
  - `channels.list` response includes `character_id` per row (no
    photo bytes — channels reuse the character photo by id).
  - `ResourceRegistry` entry that bumps the `characters` resource
    version when a character photo changes; the existing `channels`
    version is not affected by photo changes.
- **Device substrate:**
  - Dart-side `StreamReceiver` and gateway-notifier dispatch for
    `message_type: "stream"`.
  - Dart-side `BlobCache` under `<app-docs>/blobs/<aa>/<sha>`.
  - Dart-side `gatewayRequestClient.filesHead` / `filesGet`.
  - Cache logic that diffs `photo_blob_id` per character row and
    triggers `files.get` for changed rows; writes to
    `app-docs/character_photos/<id>.<ext>`.
  - Channel render path looks up the cached character photo by
    `character_id` from `channels.list` rows.
- **Logging** — see §8.4. INFO at session boundaries, DEBUG per
  chunk, WARNING/ERROR on failures, all sites stamped with
  `(device_id, method)` scope automatically.

Architecture-tab documentation updates (land **with** this phase,
not after):

- `mintdocs/architecture/protocol/protocol-contract.mdx` — replace
  the "Reserved for future streaming chunks" line in the
  message-type rules table with the actual `stream` shape; add a
  short subsection covering the `request → ack response → N stream
  frames → terminal response` pattern (new in the contract, since
  every prior request had exactly one response).
- `mintdocs/architecture/protocol/unified-message.mdx` — document
  the validator constraints for `message_type: "stream"`.
- `mintdocs/architecture/concepts/communication-manager.mdx` —
  note the new inbound-dispatcher branch that routes
  `message_type: "stream"` frames to the stream receiver instead
  of the normal message-handling path.

No other architecture-tab page (channel-manager, channel-plugins,
agent-manager, http-server, network-topology, hiro-server-components)
needs an update for Phase 1.

Acceptance criteria:

- A unit test on the server emits a known PNG via `files.get` and
  verifies the sequence of frames matches the spec (ack, N stream
  frames with correct `seq` / `final`, terminal response).
- A device end-to-end test fetches a character photo and renders it.
- A disconnect mid-transfer (kill the WS during a chunk) results in
  a retried fetch from `seq = 0` after reconnect, with the resulting
  file matching the source sha.
- Editing a character photo in the admin UI triggers a
  `resource.changed("characters")` event; the device re-pulls
  `characters.list`, sees the new `photo_blob_id`, fetches the
  bytes, and **both the character profile and the channels list
  using that character** update without an app restart.
- The admin Logs UI, filtered by `method = files.get`, shows the
  full session lifecycle at INFO with no per-chunk DEBUG noise
  unless DEBUG is explicitly enabled.

---

## 10. Future phases

These are designed and have a defined wire shape, but their
device-side wiring (and in some cases small server-side
extensions) is **deferred**. They are documented here so the
day-one substrate is built with them in mind and lands without
shape changes when picked up.

### Phase F1 — Message history with inline attachment metadata

Goal: scenario 7.3 works.

Adds:

- `messages.history` response includes inline blob metadata for any
  attachment-bearing content items (`content_type` in `image`,
  `audio`, `file`, etc., where `body` is a reference string).
- `message_attachment:<msg_id>:<idx>` resolver entry.
- Device-side dedupe + bounded-concurrency fetch queue.
- Aggregate progress UI inside the message-history reload flow.

Acceptance criteria (when this phase lands):

- Reloading a channel with N messages each carrying an attachment
  results in **at most N unique** `files.get` calls (deduped by
  blob_id) and a visible progress indicator.

Architecture-tab documentation updates (with this phase): none
beyond what Phase 1 already lands — the wire shape does not change.

### Phase F2 — Device-to-server upload (user-attached files)

Goal: scenario 7.4 works.

Adds:

- `BlobStore` writer path (`open_writer(expected_sha) → BlobWriter`,
  `finalize`), with `<sha>.partial` + atomic rename.
- `hirocli/tools/files.py:FilesPutHeadTool`.
- `files.put.head` request method.
- Server-side `StreamReceiver` for inbound stream frames keyed by
  `request_id` (replaces the placeholder rejecting handler from
  Phase 1).
- Dart-side `StreamSender` and `gatewayRequestClient.filesPutHead`.
- Composer flow: upload first, collect refs, then send the chat
  message with reference-bearing `ContentItem`s.

Acceptance criteria (when this phase lands):

- A user attaches a photo and a PDF to a chat message; both upload
  successfully; the message arrives at the agent with both
  attachments resolvable via `files.get`.
- An interrupted upload (kill WS mid-transfer) re-uploads from
  `seq = 0` on retry; final sha matches; `<sha>.partial` is cleaned
  up; the destination `<sha>` file is intact and one file only.

Architecture-tab documentation updates (with this phase):

- `mintdocs/architecture/protocol/protocol-contract.mdx` — list
  `files.put.head` alongside the other request methods.
- `mintdocs/architecture/concepts/agent-manager.mdx` — note that
  agent input may contain attachment references that resolve via
  `files.get` through the same in-process `files_resolver`.

---

## 11. Open questions to confirm before coding

These are answered with the simpler choice in this doc, but flag if a
different answer is wanted.

1. **Reference shape.** Colon-separated `<kind>:<id>[:<sub>]`. Pick
   once now; hard to change later because it bakes into stored
   message rows.
2. **Attachment-message ordering.** Send the chat message **only after
   all uploads succeed**. Alternative is "send immediately with
   pending blob ids, fill in later." Simpler path chosen.
3. **`files.head` vs. inline metadata.** For `messages.history`, blob
   metadata is **inlined** in the response (saves a round-trip per
   attachment). For `characters.list`, photo metadata (`photo_ref`,
   `photo_blob_id`) is also inlined. Other resources may differ on
   their own merits.
4. **Single-shot fast path.** None. Even ≤ 2 MB character photos go
   through `files.get` + one stream frame. Strictly one path simplifies
   testing and devops.

---

## 12. Non-goals

- **Generic CDN.** Devices fetch only blobs they have a reference to.
- **Sync engine.** Deciding *which* references a device should fetch is
  a Resource Sync concern (`docs/resource-sync.md`). File Communication
  only moves bytes once a reference is in hand.
- **Real-time media.** This is a file transfer substrate, not a
  streaming codec. Live audio/video would negotiate a separate path.
- **Server-to-server transfer.** Only server↔device.

---

## 13. Cross-references

- `docs/file-communication.md` — engineering note with deeper
  rationale, the binary-frames future option, and the alternate
  Section 3 single-shot pattern (not used on day one).
- `docs/resource-sync.md` — the events-are-hints / requests-are-truth
  substrate that drives *when* devices fetch.
- `hiroserver/hiro-channel-sdk/src/hiro_channel_sdk/models.py` —
  `UnifiedMessage` and `MESSAGE_TYPE_STREAM` validator branch.
- `hiroserver/gateway/src/hirogateway/relay.py` — the relay; verifies
  why we cannot route binary frames or peek inside non-JSON payloads.
- `hiroserver/hirocli/src/hirocli/runtime/request_methods.py` — where
  the new request methods register.
- `hiroserver/hirocli/src/hirocli/domain/character.py` — existing
  character photo resolver to wrap.
- `hiroserver/hirocli/src/hirocli/domain/media_store.py` — existing
  message media store to generalize into `blob_store.py`.
