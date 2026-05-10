# Message Send Tool — Design

> Send a chat message into a conversation as the workspace owner user, from
> the Admin UI or the CLI, using the existing tool architecture. Supports
> text and audio (mirror of the Flutter `sendText` / `sendAudio` flows).

## Goal

One operation, three callers (CLI, AI agent, Admin UI), one wire shape.
Reuses the inbound message pipeline that the `devices` channel plugin
already feeds — no parallel paths.

## Architecture

```
Admin UI ─┐
CLI ──────┼─► ToolRegistry ─► MessageSendTool.execute()
          │                       │
          │                       ▼
          │           CommunicationManager.InboundPipeline.receive(dict)
          │                       │
Devices plugin ────────────────────┘   (same boundary, different producer)
```

`InboundPipeline.receive()` is the **single canonical entry point** for any
inbound `UnifiedMessage(message_type="message")`. The tool builds the dict
and calls it. Ack, adapters (transcription for audio), persistence, agent
reply, and outbound fan-out all happen unchanged.

### Live fan-out to sibling devices — `UserMessageMirrorHook`

The "every paired device sees every message live" guarantee for real device
sends is an emergent property of the gateway broker: a device sends a
UnifiedMessage with no `target_device_id`, and the gateway broadcasts that
frame to every other connected peer. In-process producers — admin UI, CLI,
and AI agent calling this tool — bypass the gateway entirely, so siblings
would never see the row live and would only catch up at the next explicit
`messages.history` trigger.

`CommunicationManager` therefore registers a `UserMessageMirrorHook` in the
post-adapt chain that re-emits every inbound user `message` as an outbound
**broadcast** (no `recipient_id`). The mirror preserves `routing.id` and
`routing.timestamp`, so device-side upserts are idempotent across the live
broadcast and any future `messages.history` upsert. The originating device
(when one exists) is excluded by the gateway's `did != sender_id` filter, so
nobody sees their own send twice.

Net effect: the `message_send` tool produces the same live device fan-out as
a real device send — without any special-casing of the synthetic `admin`
sender. See
[Communication Manager — User message mirror](https://docs.hiroleague.com/architecture/concepts/communication-manager#user-message-mirror).

## Tool

**Name:** `message_send`
**File:** `hiroserver/hirocli/src/hirocli/tools/conversation.py`
**Scope:** **runtime-scoped** (requires a live server; needs the
`CommunicationManager` instance). Add a `runtime: bool = True` flag to
`Tool` base. Workspace-scoped tools keep `runtime = False` (default).

### Parameters

| Name | Type | Required | Notes |
|---|---|---|---|
| `channel_id` | int | yes | Conversation channel id (writes to `routing.metadata.chat_channel_id`). |
| `text` | str | one of `text` / `audio_*` | UTF-8 message body. |
| `audio_path` | str | one of `text` / `audio_*` | Server-local path to an audio file. CLI uses this. |
| `audio_base64` | str | one of `text` / `audio_*` | Base64-encoded audio bytes. Admin UI uses this (no upload endpoint needed). |
| `audio_mime_type` | str | with audio | e.g. `audio/m4a`, `audio/webm`. |
| `audio_duration_ms` | int | with audio | Recorded duration in ms. |
| `request_voice_reply` | bool | no | Maps to `routing.metadata.request_voice_reply`. |
| `workspace` | str | no | Defaults to registry default. |

Exactly one of `text`, `audio_path`, `audio_base64` must be provided.
Reject the call otherwise — no implicit empty messages.

### Identity

`sender_id` is **always the workspace owner user id**, resolved from the
workspace. This tool is not an impersonation tool. A future
`message_send_as` tool, if ever needed, would be a separate name guarded
by the registry policy hook.

### Synthetic source channel

`routing.channel = "admin"`. Reserved name for in-process producers.
Do not reuse `"devices"` — that lies about the transport. Logging and
audit will see `admin` as the peer.

## Wire shape (mirror of Flutter)

Text:

```json
{
  "message_type": "message",
  "routing": {
    "id": "<uuid4>",
    "channel": "admin",
    "direction": "inbound",
    "sender_id": "<workspace_owner_user_id>",
    "timestamp": "<iso8601 UTC>",
    "metadata": {
      "chat_channel_id": <int>,
      "request_voice_reply": true   // optional
    }
  },
  "content": [
    { "content_type": "text", "body": "<text>" }
  ]
}
```

Audio (matches `sendAudio` in
`device_apps/lib/application/messages/message_send_notifier.dart`):

```json
{
  "message_type": "message",
  "routing": { "...": "same as text, plus request_voice_reply if asked" },
  "content": [
    {
      "content_type": "audio",
      "body": "<base64 audio bytes>",
      "metadata": {
        "duration_ms": <int>,
        "mime_type": "<mime>",
        "blob_id": "sha256:<hex>",
        "size": <bytes>,
        "chunk_size": <default_blob_chunk_size>,
        "chunk_count": <ceil(size / chunk_size)>
      }
    }
  ]
}
```

For `audio_path`, the tool reads the file once. For `audio_base64`, it
decodes once. From there both paths share: compute `blob_id` (sha256),
size, chunk_size/chunk_count, base64-encode for `body`. Use the same
helpers the persistence layer already uses for blob IDs and chunking — do
not reinvent them.

## Behavior

1. Validate params (exactly-one-content-source, channel exists, audio
   fields present together).
2. Resolve workspace owner user id.
3. Build the `UnifiedMessage` dict (above).
4. `await comm_manager.inbound_pipeline.receive(payload_dict)`.
5. Return `MessageSendResult(message_id=<uuid>, channel_id=<int>)`
   immediately. Do **not** wait for the agent reply — devices don't
   either; the Admin UI will see the new message and the eventual reply
   through the same live message stream it already uses.

## Caller wiring

- **Admin UI (`admin_frontend/src/routes/chats/+page.svelte`):** add a
  composer bar (text input + mic button). Submit calls the existing
  `/api/tools/invoke` (or whatever the registry HTTP endpoint is named)
  with `{ "tool": "message_send", "params": { ... } }`. For audio, record
  in the browser, base64-encode, send `audio_base64`.
- **CLI:** `hiro message send --channel <id> [--text "..." | --audio
  <path>] [--voice-reply]`. Because the tool is runtime-scoped, the CLI
  dispatches via HTTP `/invoke` to the running server (same pattern other
  live-server tools use). If the server is down, fail with a clear
  "live server required" error — do not fall back to anything.
- **AI agent:** picks up `message_send` automatically through the
  registry-derived schema. No extra wiring.

## Runtime-scoped tool plumbing (one-time)

- Add `runtime: bool = False` on `Tool` base.
- `ToolRegistry` accepts an optional `RuntimeContext` at construction
  (carries `comm_manager`). When registering a runtime-scoped tool, the
  registry injects the context onto the tool instance.
- Direct `tool.execute()` for a runtime-scoped tool outside a server
  process raises `RuntimeError("requires live server")`.
- Server startup builds the registry with the live `RuntimeContext` and
  registers `MessageSendTool` alongside the existing tools.

## Out of scope (v1)

- Image / file content (only text + audio).
- Multi-content messages (single `ContentItem`).
- Sending as a different user.
- Scheduled / delayed sends.
- Edit / delete of sent messages (those are separate tools).

## Files touched

- `hiroserver/hirocli/src/hirocli/tools/base.py` — add `runtime` flag.
- `hiroserver/hirocli/src/hirocli/tools/registry.py` — runtime context
  injection; refuse direct execute when no context.
- `hiroserver/hirocli/src/hirocli/tools/conversation.py` — new
  `MessageSendTool` and result dataclass.
- `hiroserver/hirocli/src/hirocli/tools/__init__.py` — export.
- Server bootstrap (where the registry is built today) — pass
  `RuntimeContext(comm_manager=...)` and register `MessageSendTool`.
- CLI commands module — add `hiro message send` that POSTs to `/invoke`.
- `admin_frontend/src/routes/chats/+page.svelte` — composer bar with
  text + mic, calls `/invoke`.

## Doc updates after implementation

- `mintdocs/architecture/misc/tools-architecture.mdx` — add a short
  "Workspace-scoped vs runtime-scoped tools" subsection.
- `mintdocs/architecture/concepts/communication-manager.mdx` — note that
  `InboundPipeline.receive()` is the canonical entry point for *all*
  inbound message producers, including in-process ones.
  **Done — also added the `UserMessageMirrorHook` and `user_message_mirror`
  envelope to the hooks / factory tables, plus a "User message mirror"
  subsection explaining why in-process producers need an explicit
  server-owned broadcast.**
- `mintdocs/architecture/concepts/message-persistence/device-history-sync.mdx`
  — added a "User message mirror (live tier for non-device producers)"
  subsection under *Live event integration* explaining how the live mirror
  and the history catch-up converge on the same `routing.id`.
