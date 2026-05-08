# Message Audio History Storage - requirements/design

> Status: Proposal. Audience: AI coding agent and human reviewers implementing
> durable audio message storage, history reload, and device playback.
>
> This document is the concrete realization of **Phase F1 — Message history
> with inline attachment metadata** as scoped in
> `docs/file-communication-implementation.md` §10. Where F1 only sketches the
> wire shape and acceptance criteria, this doc fills in the server data
> model, write paths, resolver entry, and the device-side cache + reload
> behavior.
>
> Related docs: `docs/file-communication-implementation.md` (the substrate
> this layers on, esp. §3 concepts, §4 reference namespace, §10 F1) and
> `docs/resource-sync.md` (the events-are-hints / requests-are-truth
> substrate that drives *when* devices reload).

This document defines the small foundation needed before message-history
attachment sync: both user voice input and character TTS voice replies must be
stored as first-class message attachments on the server, returned by
`messages.history`, and fetchable by Flutter devices through the existing
`files.get` stream path.

We follow workspace rules: **no backward compatibility, no migrations, no
wrappers**. The shapes below describe the desired end state; existing
workspaces should be reset (delete `<workspace>/data/data.db` and
`<workspace>/data/media/`) before testing the new schema.

## 1. Goal

When a device reloads a conversation from the server:

- user audio messages can play again;
- character TTS voice replies can play again;
- the same message id links the server row, server attachment refs, and local
  Flutter rows;
- audio bytes are not embedded in `messages.history`;
- devices fetch missing audio blobs on demand and cache them locally.

### 1.1 Conversation identity (WhatsApp-style)

There is **one conversation per user**, regardless of how many devices the user
has paired. All paired devices read from and write into the same channel.
Concretely:

- Server **never** keys a channel by `routing.sender_id` — that field carries
  the *device id* and is a property of the originating endpoint, not of the
  conversation. Channels are scoped solely by `(workspace_owner_user, channel_name)`.
- `persist_inbound` (`domain/message_store.py`) and the agent thread resolver
  (`runtime/agent_manager.py:_resolve_thread_character`) both resolve to the
  user's seeded `General` channel, so a message from device A and a message from
  device B land on the same `channels` row, with the same `messages.history`
  stream and the same LangGraph memory thread.
- Server-originated text replies (`_make_reply`), TTS voiced events
  (`_synthesize_and_send`), and transcript events
  (`EnvelopeFactory.transcript_event`) are emitted with **no `recipient_id`** so
  the gateway broadcasts them to every paired device. Request/response correlation
  envelopes (`response`, `routing_error_response`, `stream_chunk` for `files.get`)
  keep `recipient_id = origin.routing.sender_id` because they are answers to a
  specific request from a specific device.
- `message.received` delivery acks remain unicast to the originating device — they
  are status feedback for that device's UI (✓✓), not shared conversation content.

This was the historical contract. It drifted between commits `0173f1f`
(2026-03-10, introducing `channel_name = f"{msg.channel}:{msg.sender_id}"`) and
`78210b8` (2026-03-24, adding user-scoping to the schema but leaving the device
key in the name). The audio-history work inherited that drift; this section is
the canonical statement of intent so the next refactor cannot quietly re-introduce
per-device channels.

### 1.2 Non-goals

The following are explicitly out of scope for this design and must not be
addressed by the same change:

- image, video, or document attachments — only audio is wired here;
- multi-audio messages (more than one `audio` content item per message) —
  the schema supports it via `slot_index`, but neither producer creates them
  today;
- device-originated attachment uploads — bytes still flow only server →
  device;
- per-chunk resume on `files.get` retries — devices retry from chunk 0 (per
  `docs/file-communication-implementation.md` §1);
- backfill of attachment rows for historical messages stored before this
  change lands — workspaces are reset per the no-migration rule.

## 2. Current state

| Area | Current behavior | File |
|---|---|---|
| User audio input | `persist_inbound()` saves inbound audio bytes to `data/media/<channel_id>/<message_pk>.<ext>` and sets `messages.media_path`. | `hiroserver/hirocli/src/hirocli/domain/message_store.py` |
| User audio transcript | The audio adapter writes the transcript into `ContentItem.metadata.description`; the persisted message body picks that up via the `description` branch in `persist_inbound`. | `hiroserver/hirocli/src/hirocli/domain/message_store.py` |
| Agent text reply | Saved as a `messages` row with `sender_type="agent"`, `sender_id="server"`, `content_type="text"`. | `hiroserver/hirocli/src/hirocli/runtime/agent_manager.py` |
| Character TTS reply | Sent live as `message.voiced` event with base64 audio. Also written to `tts_debug/<reply_message_id>.mp3`, but that file is not tracked by `messages` and is not history-reloadable. | `hiroserver/hirocli/src/hirocli/runtime/agent_manager.py` |
| Message id | Server stores `UnifiedMessage.routing.id` in `messages.external_id` (already `UNIQUE`). This is promoted to the canonical API id returned to devices. | `hiroserver/hirocli/src/hirocli/domain/data_store.py` |
| `messages.history` shape | Returns raw row dicts (integer `id`, `media_path`, etc.) — replaced by the normalized contract in §6. | `hiroserver/hirocli/src/hirocli/runtime/request_methods.py` |
| File transfer | `files.get` can stream bytes to the device. The resolver currently only covers `character_photo:` lookup and scans character dirs by sha for `blob_id` lookup. | `hiroserver/hirocli/src/hirocli/domain/files_resolver.py` |

## 3. Requirements

| Requirement | Design decision |
|---|---|
| Canonical id | `messages.external_id` is the public `message.id`. Server integer `messages.id` stays internal. |
| Audio as attachments | Every saved audio asset is represented as a message attachment row, including user voice input and character TTS output. |
| No bytes in history | `messages.history` returns references and blob metadata, never base64 audio. |
| Fetch by content hash | Each attachment exposes `blob_id = sha256:<hex>`, `size`, `media_type`, `chunk_size`, and `chunk_count` — same fields as `files.head`. |
| Fetch by logical ref | Each attachment also exposes `body = message_attachment:<message_id>:<idx>` for resolver-based lookup. |
| Idempotent device sync | Flutter upserts messages by canonical message id and dedupes audio fetches by `blob_id`. |
| Live path still works | `message.transcribed` and `message.voiced` events remain for live UX, but history reload must not depend on receiving those events. |
| Single source of truth | Audio bytes are tracked **only** through `message_attachments`. The legacy `messages.media_path` column is removed (no wrappers per workspace rules). |

## 4. Server data model

Add a first-class message attachment index. Prefer a table over burying this in
`messages.metadata` because it is easier to inspect, query, and resolve.

The `messages.media_path` column is **dropped** — bytes are tracked exclusively
through `message_attachments.media_path`. Any code path that updated
`messages.media_path` (e.g. `update_media_path` in `domain/message_store.py`)
is removed.

```sql
CREATE TABLE message_attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_pk      INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    slot_index      INTEGER NOT NULL,
    content_type    TEXT NOT NULL,
    blob_id         TEXT NOT NULL,
    media_type      TEXT NOT NULL,
    size            INTEGER NOT NULL,
    media_path      TEXT NOT NULL,
    filename        TEXT,
    duration_ms     INTEGER,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    UNIQUE(message_pk, slot_index)
);

CREATE INDEX IF NOT EXISTS idx_message_attachments_blob
    ON message_attachments(blob_id);
CREATE INDEX IF NOT EXISTS idx_message_attachments_message
    ON message_attachments(message_pk);
```

Field notes:

- `slot_index` — position of the attachment within the owning message. For
  user audio this is the index of the audio item inside `UnifiedMessage.content`
  (typically `0` since multi-audio messages are not produced today). For TTS
  replies it is always `0`.
- `blob_id` — `sha256:<hex>` of the on-disk bytes; computed once at insert and
  not recomputed by the resolver.
- `media_path` — relative to `<workspace>/data`, matching the existing media
  store convention used by `domain/media_store.py`.
- The logical `ref` is **not stored** — it is `message_attachment:<external_id>:<slot_index>`,
  a deterministic function of `messages.external_id` and `slot_index`, and is
  reconstructed when serializing the history response.

Reference shape:

```text
message_attachment:<message_external_id>:<slot_index>
```

## 5. Server write paths

### 5.1 User audio input

When an inbound message contains an audio content item, `persist_inbound()`
in `domain/message_store.py`:

0. resolves the conversation channel by **`(workspace_owner_user, "General")`**
   only — `routing.sender_id` (the originating device id) is **never** part of
   the channel key (see §1.1);
1. inserts the message row (`sender_type="user"`);
2. for each audio `ContentItem` at position `i`:
   - decodes and saves the bytes under `data/media/<channel_id>/<message_pk>.<ext>`;
   - computes `blob_id` and `size` from the saved file;
   - inserts a `message_attachments` row with `slot_index=i`,
     `content_type="audio"`, and the metadata shown below.

Attachment `metadata`:

```json
{
  "transcript": "user words",
  "source": "user_audio"
}
```

The message row remains useful for text search by storing the transcript in
`messages.body` (existing behavior — the audio adapter writes the transcript
into `ContentItem.metadata.description` and `persist_inbound()` already picks
it up). The audio file is tracked **only** through `message_attachments`.

### 5.2 Character TTS voice reply

The current flow saves an agent text reply (`sender_type="agent"`,
`sender_id="server"`) via `save_message()` in `runtime/agent_manager.py`, then
runs `_synthesize_and_send()` as a fire-and-forget task. The new flow extends
**only** the synthesize step:

1. resolve the agent reply's `message_pk` from `external_id = text_reply.routing.id`;
2. save the generated audio bytes under `data/media/<channel_id>/<reply_message_pk>.<ext>`
   (replacing the current `tts_debug/<reply_message_id>.mp3` write — the
   `tts_debug/` directory is retired);
3. compute `blob_id` and `size`;
4. insert a `message_attachments` row with `slot_index=0`,
   `content_type="audio"`, and the metadata shown below;
5. emit the existing `message.voiced` event with the audio for live playback,
   **plus** the new attachment fields so a device that is online can skip the
   `files.get` round-trip.

Attachment `metadata`:

```json
{
  "source": "character_tts",
  "reply_to_message_id": "<user_message_id>",
  "model": "<tts model>",
  "voice": "<voice id>"
}
```

Extended `message.voiced` event payload:

```json
{
  "type": "message.voiced",
  "ref_id": "<reply_message_external_id>",
  "data": {
    "audio": "<base64>",
    "mime_type": "audio/mpeg",
    "duration_ms": 2100,
    "blob_id": "sha256:...",
    "ref": "message_attachment:<reply_message_external_id>:0",
    "size": 123456,
    "chunk_size": 49152,
    "chunk_count": 3
  }
}
```

Failure semantics: if TTS fails, `_synthesize_and_send()` already logs and
returns without raising. **No attachment row is created** in that case — the
agent text reply persists, and `messages.history` returns a text-only message
for that reply. Devices must tolerate agent messages with zero audio
attachments.

## 6. `messages.history` response

Return a normalized message contract instead of raw DB rows.

This is a **breaking wire-shape change** for `handle_messages_history` in
`runtime/request_methods.py`. Per workspace rules (no backward compatibility,
no wrappers), the current row-shaped response is replaced outright; existing
device code that read the raw row keys (`id` integer PK, `media_path`, etc.)
must be updated in the same change.

```json
{
  "messages": [
    {
      "id": "msg_external_id",
      "channel_id": 42,
      "sender_type": "agent",
      "sender_id": "server",
      "created_at": "2026-05-08T10:00:00Z",
      "content": [
        {
          "content_type": "text",
          "body": "Sure."
        },
        {
          "content_type": "audio",
          "body": "message_attachment:msg_external_id:0",
          "metadata": {
            "blob_id": "sha256:...",
            "size": 123456,
            "media_type": "audio/mpeg",
            "chunk_size": 49152,
            "chunk_count": 3,
            "duration_ms": 2100,
            "source": "character_tts"
          }
        }
      ]
    }
  ]
}
```

Field notes:

- `id` is `messages.external_id`. The integer PK is not exposed.
- `channel_id` is the integer DB id of the conversation channel (matches what
  `channels.list` returns).
- `sender_type` is whatever the row stores: `"user"` for inbound user
  messages, `"agent"` for server-generated agent replies (verified against
  `domain/message_store.py:persist_inbound` and
  `runtime/agent_manager.py:save_message`).
- `chunk_size` is the chunk size that `files.head` / `files.get` will use for
  this blob. Devices need it up front to size their fetch buffer; the server
  uses `DEFAULT_CHUNK_SIZE` from `domain/blob_store.py`.
- For a user audio message, the `text` content item is omitted if no
  transcript exists. If a transcript exists, return text **plus** audio so the
  UI can show the transcript and still play the original recording.

`resource_sync_version` is **not** part of the response in phase 1. Adding it
later requires registering a `messages` resource in the resource version
store (see §15) — until then `messages.history` is pull-only on channel
open / reconnect, consistent with §15's "open decisions".

## 7. File resolver changes

Today `domain/files_resolver.py` handles only `character_photo:` refs and
scans character directories on every `files.get(blob_id)`. Extend both
functions:

`resolve_ref(workspace_path, ref)` — add a `message_attachment:` branch:

1. parse `<message_external_id>` and `<slot_index>` from the ref body
   (split on `:` from the right so external ids are allowed to contain colons);
2. look up the internal `messages.id` by `external_id`;
3. look up the attachment by `(message_pk, slot_index)`;
4. authorize the device against the channel that owns the message
   (same authz model used elsewhere);
5. return `(path, media_type, blob_id)` from the attachment row directly —
   no on-the-fly hashing.

`resolve_blob_id(workspace_path, blob_id)` — replace the current character-photo
scan with an indexed lookup:

1. `SELECT media_path, media_type FROM message_attachments WHERE blob_id = ?`
   (uses `idx_message_attachments_blob`);
2. fall back to the existing character-photo scan if no row matches (still
   needed for `character_photo:` refs whose blobs are not stored in
   `message_attachments`).

A future `blobs` table can subsume both lookups; until then the indexed
attachment query is O(1) for message audio and the photo scan stays O(N) over
characters only.

## 8. Device behavior

The Flutter app already mirrors messages locally in a Drift database (see
`device_apps/lib/data/local/database/`) and exposes them via
`MessageRepositoryImpl` (`watchChannelMessages` → reactive UI). The design
below builds on that — **local Drift remains the source of truth for the UI**,
and `messages.history` only fills gaps.

### 8.1 Local data model (Drift)

Two table changes in `device_apps/lib/data/local/database/tables/`:

1. **`messages_table.dart`** — add columns to the existing `Messages` table:
   - `transcript TEXT NULL` — promoted out of the `metadata` JSON blob into a
     real column so search/preview do not pay a JSON-decode tax per row;
   - keep `metadata` for everything else (per-modality fields, source flags).

2. **`message_attachments_table.dart`** (new) — mirrors the server schema in
   §4 with device-local fields added:

   ```dart
   class MessageAttachments extends Table {
     TextColumn get messageId => text()();          // FK → Messages.id (external_id)
     IntColumn get slotIndex => integer()();
     TextColumn get contentType => text()();        // 'audio' day-one
     TextColumn get blobId => text()();             // 'sha256:…'
     TextColumn get mediaType => text()();
     IntColumn get size => integer()();
     IntColumn get durationMs => integer().nullable()();
     IntColumn get chunkSize => integer()();
     IntColumn get chunkCount => integer()();
     TextColumn get remoteRef => text()();          // 'message_attachment:<id>:<idx>'
     TextColumn get localPath => text().nullable()();   // null until fetched
     TextColumn get fetchStatus => text()();        // 'pending'|'fetching'|'ready'|'failed'
     IntColumn get lastFetchAttemptMs => integer().nullable()();
     TextColumn get metadata => text().nullable()();
     IntColumn get createdAtMs => integer()();
     @override Set<Column> get primaryKey => {messageId, slotIndex};
   }
   ```

   Indexes: `(blob_id)` for dedup / cache lookup, `(fetch_status)` for the
   queue scan.

3. **`channels_table.dart`** — add `last_history_synced_at INTEGER NULL` so
   the device can ask the server only for messages newer than the last
   successful pull.

A new `MessageAttachmentsDao` provides:

- `watchForMessage(messageId)` — reactive UI binding;
- `getMissingBlobIds()` — for the fetch queue;
- `markFetching/markReady/markFailed(...)`;
- `findByBlobId(blobId)` — for cross-message dedup.

### 8.2 Efficient history reload (only fetch what's missing)

The whole point of this section. Reload is split into **two independent
loops**: (a) row-level incremental sync of the messages table, and (b)
attachment-level dedup of audio bytes.

**Trigger points** (no full re-pull on every chat open):

| Trigger | Action |
|---|---|
| Gateway connect / reconnect | For every channel with cached messages, run incremental sync (§8.2.a). |
| Chat screen opens | If `now - channel.last_history_synced_at > STALE_TTL` (default 60 s), run incremental sync. Otherwise rely on live events + cached rows. |
| `resource.changed` for `messages` *(deferred — see §15)* | Run incremental sync for the affected channel. |
| Pull-to-refresh in chat UI | Force incremental sync regardless of TTL. |

**(a) Row-level incremental sync** — `MessageHistorySync.syncChannel(channelId)`:

1. read `last_history_synced_at` from the local channels row;
2. call `messages.history(channel_id, after=last_history_synced_at, limit=<page>)`;
3. for each message in the response:
   - `INSERT OR IGNORE` into `messages` keyed by `id` (external id) — local
     rows already inserted by live events stay untouched;
   - for each `content_type=audio` item, `INSERT OR IGNORE` into
     `message_attachments` with `fetch_status='pending'` (or `'ready'` if
     `findByBlobId(blob_id)` already has a `localPath`);
4. if the response was full-page, page again with `after = last
   message.created_at`;
5. once exhausted, write `channel.last_history_synced_at = max(created_at)`.

This pattern guarantees: **already-cached messages are never re-downloaded as
JSON**, and **already-cached blobs are never re-fetched as bytes**. A second
chat-open within the TTL is essentially free.

**(b) Attachment fetch loop** — `AttachmentFetchService.tick()`:

1. `SELECT DISTINCT blob_id, remote_ref, size, chunk_count FROM message_attachments WHERE fetch_status = 'pending'`;
2. for each unique `blob_id`:
   - mark all rows with that `blob_id` as `fetching`;
   - call `gatewayRequestClient.filesGet(blob_id)` (existing, used today by
     `character_photo_sync_logic.dart`);
   - assemble bytes from stream frames into a `<docs>/audio/<blob_hex>.partial`
     file (mobile) or an `Uint8List` then `data:` URL (web — see §8.3);
   - verify `sha256(bytes) == blob_id` before publishing;
   - on mobile: atomic rename to `<docs>/audio/<blob_hex>.<ext>`; on web: keep
     the data URL;
   - update **all** rows sharing that `blob_id` to `fetch_status='ready'` and
     `local_path=<path-or-data-url>` in one transaction.
3. on failure (timeout, sha mismatch, gateway disconnect mid-stream): set
   `fetch_status='failed'`, record `last_fetch_attempt_ms`, and re-queue after
   the fixed retry delay (default 30 s). Per
   `file-communication-implementation.md` §1, retries restart from chunk 0.

Concurrency: bounded to **2 in-flight blobs** (matches the current
`character_photo_sync` pattern) so a slow upstream does not stall live UX.

### 8.3 Web vs mobile parity

The substrate already abstracts this in `AudioStorageService` (see
`device_apps/lib/platform/storage/audio_storage_service.dart`) — keep that
abstraction and extend it:

| Platform | Where bytes live | `local_path` shape | Survival |
|---|---|---|---|
| iOS / Android | `<documents>/audio/<blob_hex>.<ext>` (filename = sha256, not message id, so dedup is automatic) | absolute file path | Across restarts |
| Web | `data:<media_type>;base64,<…>` written into `local_path`; bytes also kept in IndexedDB-backed Drift | `data:` URL | Across restarts (Drift on web persists in IndexedDB) |

Two web-specific notes:

- `AudioStorageService.saveBytes()` already returns a `data:` URL on web —
  unchanged. The fetch service feeds it the assembled bytes.
- The current `character_photo_sync_web.dart` / `_io.dart` split is the
  template for `attachment_fetch_web.dart` / `_io.dart` if any platform
  divergence emerges; keep the shared logic in `attachment_fetch_logic.dart`.

The device-side `local_path` is **never** sent back to the server. It is a
purely local handle. The canonical identity stays `(message_id, slot_index)` /
`blob_id`, both of which are platform-agnostic.

### 8.4 Live event integration

Live `message.voiced` (and future `message.attached`) events are now a
**fast-path to the same cache**:

1. live event arrives with `audio` (base64) **plus** `blob_id`, `ref`, `size`,
   `chunk_size`, `chunk_count` (per §5.2 extension);
2. `MessageRepositoryImpl._handleEvent` writes the bytes via
   `AudioStorageService.saveBytes()`;
3. **upserts a `message_attachments` row** with `fetch_status='ready'` and
   the produced `local_path`;
4. UI rebuilds via the reactive Drift stream.

When `messages.history` later returns the same message, step 3 of §8.2.a sees
an existing attachment row with `fetch_status='ready'` and skips fetching.
This closes the loop: live events and history reload converge on the same
local rows, no duplicate downloads, no UI flicker.

### 8.5 `AudioAttachment` model

Extend `device_apps/lib/domain/models/message/audio_attachment.dart` with the
identity fields required by §8.2:

- `blobId` — content hash, cache key;
- `remoteRef` — `message_attachment:<message_id>:<idx>`, fallback fetch path;
- `size`, `chunkCount` — fetch progress UI;
- `fetchStatus` — derived from the attachments table; the UI uses this to
  show "loading", "tap to play", or "failed — retry".

`AudioAttachment.isPlayable` becomes `fetchStatus == ready && localPath != null`.

## 9. Protocol changes

Two contract changes to `UnifiedMessage` event/request payloads. **No new
request methods, no new message types** — the existing `messages.history`,
`files.head`, and `files.get` cover everything in this design. Per workspace
rules, this is the desired end state with no compatibility shim.

### 9.1 `message.voiced` event — extended `data` fields

Today (`runtime/agent_manager.py:_synthesize_and_send`):

```json
{ "audio": "<base64>", "mime_type": "audio/mpeg", "duration_ms": 2100 }
```

After this design:

```json
{
  "audio": "<base64>",
  "mime_type": "audio/mpeg",
  "duration_ms": 2100,
  "blob_id": "sha256:...",
  "ref": "message_attachment:<reply_message_external_id>:0",
  "size": 123456,
  "chunk_size": 49152,
  "chunk_count": 3
}
```

The `audio` field stays so devices that miss the history pull (e.g. a fresh
install during the live exchange) still get immediate playback. `blob_id` lets
the device dedup against any cached attachment row that was filled by a prior
history pull.

### 9.2 `messages.history` response — replaced shape

See §6. This is **breaking** for any existing consumer of the raw row shape
(none today other than the Flutter client itself). Per workspace rules, the
old shape is removed without a compat shim.

### 9.3 Reference namespace

Adds the `message_attachment:` kind to the reference namespace defined in
`docs/file-communication-implementation.md` §4. No other kinds change.

```text
message_attachment:<message_external_id>:<slot_index>
```

## 10. Tools and CLI

| Surface | Change |
|---|---|
| `MessageHistoryTool` (`hirocli/tools/conversation.py`) | Internal callers (CLI, Agent, Admin UI) keep using the tool; the tool's `MessageHistoryResult.messages` becomes the normalized contract from §6 instead of raw row dicts. Update its docstring and result dataclass type hints accordingly. |
| `FilesHeadTool` (`hirocli/tools/files.py`) | Tool description mentions `message_attachment:<id>:<idx>`; the existing execution path calls `resolve_ref`, so `files.head message_attachment:<id>:<idx>` works through the resolver. |
| New `MessageAttachmentListTool` | Decision: skipped for this pass. Add only if a real CLI workflow needs attachment listing. |
| Admin UI / `admin_frontend/src/lib/api/chat-channels.ts` | Audited. The admin messages endpoint deliberately renders raw message rows, not the normalized `messages.history` contract, and its TS type excludes the removed `media_path` field. |

No new HTTP routes, no new request methods. The data-plane surface stays
exactly the set in `runtime/request_methods.py` today.

## 11. Logging

The current code already follows the **Human-first structured logging** rule
(emoji + `{action} — {peer} · {kind}` first arg, readable extras first,
opaque ids last). The new code paths add the following INFO-level entries.
All emit through `Logger.get(...)` in their respective modules.

### Server

| Event | Logger | Sample first arg | Key extras |
|---|---|---|---|
| Inbound audio attachment saved | `MSG_STORE` | `⬇️ Audio attachment stored — {peer} · audio` | `blob_id`, `size`, `duration_ms`, `slot_index`, `msg_id` (last) |
| TTS attachment saved | `AGENT_MGR` | `⬆️ TTS attachment stored — {peer} · audio` | `blob_id`, `size`, `duration_ms`, `model`, `voice`, `ref_id`, `msg_id` (last) |
| TTS attachment skipped (failure) | `AGENT_MGR` | `⚠️ TTS attachment skipped — {peer} · synthesis_failed` | `error`, `ref_id`; `exc_info=True` |
| `messages.history` served (extend existing log) | `REQUEST` | `⬇️ Resource served — request:messages.history` | already logs `count`, `after`; **add** `attachments_count`, `elapsed_ms` |
| `files.get` served (extend existing log) | `REQUEST` | `⬇️ Resource served — request:files.get` | already logs `blob_id`, `size`, `chunk_count`; **add** `kind` ∈ `{"character_photo","message_attachment"}` resolved by the resolver |
| `resolve_ref` failed | `FILES_RESOLVER` (new logger) | `⚠️ Reference unresolved — {kind}:{id}` | `reason` ∈ `{"unknown_kind","not_found","unauthorized"}` |

Skip per-chunk logging on the server (already the convention) — the existing
stream-frame DEBUG logs in `stream_sender.py` are sufficient.

### Device

| Event | Logger | Sample first arg | Key extras |
|---|---|---|---|
| History sync started | `MessageHistorySync` (new) | `⬇️ History sync — {channelId} · pull_after` | `after`, `page_limit` |
| History sync result | `MessageHistorySync` | `✅ History sync — {channelId} · {n_new} new, {n_attachments} attachments` | `elapsed_ms`, `pages` |
| Attachment fetch enqueued | `AttachmentFetch` (new) | `⬇️ Attachment fetch — queued · audio` | `blob_id`, `size`, `chunk_count`, `dedup_count` (rows sharing this blob) |
| Attachment fetch ready | `AttachmentFetch` | `✅ Attachment fetch — ready · audio` | `blob_id`, `elapsed_ms`, `local_path_kind` ∈ `{"file","data_url"}` |
| Attachment fetch failed | `AttachmentFetch` | `❌ Attachment fetch — failed · audio` | `blob_id`, `reason` ∈ `{"sha_mismatch","timeout","gateway_disconnect","resolver_error"}`, `attempt`; `error` |
| Live `message.voiced` short-circuit | `MessageRepository` | `⬇️ Voice reply — {channelId} · live cached` | `ref_id`, `blob_id`, `bytes` |

Per the logging rule, `blob_id` and `msg_id` are **opaque** — they go last.
`peer` / `channelId` and short status text go first. Use `INFO` for
milestones, `DEBUG` for chunk-level / payload dumps, `WARNING` / `ERROR`
with `exc_info=True` for anomalies.

## 12. Mintdocs updates

The architecture documentation needs the following touches when this design
lands. Workspace rule "Document-Executed-Plans" applies.

| Page | Change |
|---|---|
| `mintdocs/architecture/protocol/protocol-contract.mdx` | List the extended `message.voiced` event fields. List `message_attachment:` as a recognized reference kind alongside `character_photo:`. No new request method to add. |
| `mintdocs/architecture/protocol/unified-message.mdx` | Update the `message.voiced` event example to show the new optional `blob_id`, `ref`, `size`, `chunk_size`, `chunk_count` fields. Note in the events table that the same shape is reused for any future `message.attached`-style event. |
| `mintdocs/architecture/concepts/communication-manager.mdx` | Add a short subsection "Message attachments persistence" describing: `persist_inbound` writes both a `messages` row and one `message_attachments` row per audio item; the legacy `messages.media_path` column is removed; agent replies get attachments via `_synthesize_and_send` after TTS success. |
| `mintdocs/architecture/concepts/agent-manager.mdx` | Note that TTS replies now produce a tracked attachment (not a debug file) and that `messages.history` will return them with full blob metadata — this makes agent replies replayable from history. |
| `mintdocs/architecture/concepts/architecture-overview.mdx` | One-line addition under "Storage" mentioning `message_attachments` as the per-message blob index. |
| (New) `mintdocs/architecture/concepts/message-history.mdx` | Decision: skip for this pass. Keep the device-side reload algorithm embedded in this design doc until reviewers ask for a separate canonical page. |
| `mintdocs/build/first-time-setup.mdx` | No tooling change — skip. |

## 13. Implementation checklist

| Step | Server | Device |
|---|---|---|
| 1 | Add `message_attachments` table to `domain/data_store.py` DDL + indexes; add `domain/message_attachments.py` storage helpers (`insert_attachment`, `list_attachments_for_message`, `get_attachment`, `find_by_blob_id`). | Add `message_attachments_table.dart` + `message_attachments_dao.dart` under `data/local/database/`; bump Drift schema version. |
| 2 | Drop `messages.media_path` column and remove `update_media_path()` from `domain/message_store.py`. Update `persist_inbound()` to create one attachment row per audio `ContentItem`. | Add `transcript` column to `messages_table.dart` (promoted out of metadata JSON); migrate existing JSON-stored transcripts in the same Drift migration. |
| 3 | Update `_synthesize_and_send()` in `runtime/agent_manager.py` to save TTS bytes under `data/media/<channel_id>/<reply_pk>.<ext>`, insert an attachment row, and remove the `tts_debug/` write. | Extend `AudioAttachment` with `blobId`, `remoteRef`, `size`, `chunkCount`, `fetchStatus`. |
| 4 | Extend the `message.voiced` event payload (`runtime/envelope_factory.py`, `agent_manager.py`) with `blob_id`, `ref`, `size`, `chunk_size`, `chunk_count`. | Update `MessageRepositoryImpl._handleEvent` (`messageVoiced` case) to upsert an attachment row with `fetch_status='ready'` instead of stuffing data into `messages.metadata.voice`. |
| 5 | Extend `domain/files_resolver.py`: add `message_attachment:` branch in `resolve_ref`; switch `resolve_blob_id` to indexed attachment lookup with photo-scan fallback. | Add `application/sync/message_history_sync.dart` implementing §8.2.a (incremental, keyed by `last_history_synced_at`). |
| 6 | Replace `handle_messages_history` in `runtime/request_methods.py` with the normalized contract from §6 (build `content[]` from row + attachment rows in one query). Add `attachments_count` and `elapsed_ms` to its log line. | Add `application/sync/attachment_fetch_service.dart` implementing §8.2.b (dedupe by `blob_id`, bounded concurrency, sha-verify before publish). |
| 7 | Add the new logging entries from §11 with the prescribed first-arg shape and extras order. | Add the new logging entries from §11; trigger history sync on gateway connect, on chat-screen open past TTL, and on pull-to-refresh. |
| 8 | Update mintdocs pages listed in §12. | Update `MessageRepositoryImpl._rowToMessage` and the audio bubble widget to render from `MessageAttachmentsDao` instead of decoding JSON `metadata.local_path`. |
| 9 | (Deferred) Register a `messages` resource in `ResourceVersionStore` and emit `resource.changed` if server-driven history refresh is desired (see §15). | (Deferred) Wire a `messages` entry into `wireResourceSync` in `application/sync/resource_sync_bootstrap.dart` once §9-server lands. |

## 14. Tests

Server:

- inbound user audio creates a message row plus exactly one attachment row,
  with `blob_id` matching `sha256` of the saved file;
- inbound text-only messages create no attachment rows;
- TTS success creates an attachment row linked to the agent reply message
  (slot `0`), with `metadata.source = "character_tts"`;
- TTS failure leaves the agent text reply intact and creates **no** attachment
  row (regression for the no-orphan-row guarantee in §5.2);
- `messages.history` returns text plus audio metadata for both user and agent
  audio cases, and text-only for failed-TTS replies;
- `messages.history` response contains `message.id` as `external_id` (string),
  not the integer PK;
- `messages.history(after=ts)` returns only rows strictly newer than `ts`
  (incremental reload regression);
- `message_attachment:<message_id>:<idx>` resolves to the expected file via
  `resolve_ref`;
- `files.get` streams a tracked message attachment and the assembled sha
  matches `blob_id`;
- `resolve_blob_id` returns the attachment row directly (indexed lookup)
  without scanning character directories when the blob is in
  `message_attachments`.

Device:

- history reload upserts by canonical message id; running it twice in a row
  produces zero new rows and zero `files.get` calls (idempotency regression
  for §8.2.a);
- after a successful pull, `channel.last_history_synced_at` advances to the
  newest `created_at` and a subsequent pull asks `after=<that ts>`;
- duplicate `blob_id`s across the response produce exactly one `files.get`
  (cross-message dedup, §8.2.b);
- live `message.voiced` short-circuit: an event with `blob_id` populates an
  attachment row with `fetch_status='ready'`, and a subsequent history pull
  that sees the same row triggers no `files.get`;
- fetched audio is sha-verified before publishing `local_path`; a tampered
  blob is rejected and marked `fetch_status='failed'`;
- audio messages loaded from history render and play on **mobile** (path
  source) and **web** (data-URL source);
- audio survives an app restart on both platforms (Drift on web persists in
  IndexedDB; mobile reads from the documents directory);
- reconnect during `files.get` retries from chunk 0 (per
  `file-communication-implementation.md` §1) and still produces a valid local
  file with matching sha.

## 15. Open decisions

| Decision | Proposed answer |
|---|---|
| Resource name | Add a `messages` resource later only if we want server-driven refresh. For phase 1, pull history on gateway connect / chat-screen open past TTL / pull-to-refresh. |
| Attachment table vs JSON | Use a table on both server and device. Easier to resolve, test, inspect, and dedup. |
| Live TTS event payload | Keep base64 for immediate playback, but add `ref` / `blob_id` once the server has saved the attachment so the device cache stays consistent (§9.1). |
| Message id in refs | Use `external_id`, not integer PK, so refs are stable across server and device APIs. |
| Filename convention on device | Filename = `<blob_hex>.<ext>` (not `<message_id>.<ext>`) so two messages sharing a blob share one file on disk. |
| History page size | Default `limit=50` (matches `MessageHistoryTool`). Devices may pass smaller pages; `all_messages=true` is reserved for tools / debug, not the chat UI. |
| Stale TTL for chat-open re-pull | 60 seconds. Tunable later; small enough to feel fresh, large enough to avoid spam on rapid screen toggles. |
