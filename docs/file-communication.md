# File Communication — desktop ↔ devices

> Status: Draft · Audience: anyone shipping bytes (photos, audio, models,
> attachments) between HiroServer (desktop / hirocli) and a device app over
> the gateway. Companion to `docs/resource-sync.md` and
> `.cursor/plans/resource_sync_protocol_2bf4d8a1.plan.md`.

This document captures the design for moving binary content across the
desktop ↔ gateway ↔ device topology. The immediate driver is character
photos shown alongside `channels.list`, but the same substrate must scale
to larger files (recordings, attachments, model bundles) without a second
rewrite.

We follow workspace rules: **no backward compatibility**, no migrations,
no wrappers — every section below describes the desired end state.

---

## 1. Context: what the topology actually allows

```
device (Flutter)  ─ws─►  Gateway (relay)  ─ws─►  HiroServer (hirocli)
                  ◄───                    ◄───
```

Concrete properties verified against the code:

- The **only** path a paired device has to the desktop is the gateway
  WebSocket. There is no LAN HTTP, no STUN/TURN, no direct socket.
  - `device_apps/lib/data/remote/gateway/...` connects to the gateway only.
  - `hiroserver/channels/hiro-channel-devices/src/hiro_channel_devices/plugin.py`
    is the desktop's only outbound bridge to the gateway.
- The desktop **does** run a FastAPI server
  (`hiroserver/hirocli/src/hirocli/runtime/http_server.py`), with
  `GET /characters/{id}/photo`, `GET /characters/{id}/profile`, etc., but
  it is **loopback / admin-UI only**. Mobile devices never reach it.
- The gateway relay (`hiroserver/gateway/src/hirogateway/relay.py`) is a
  thin JSON forwarder. It re-serializes every relayed message via
  `json.dumps(msg)` and treats the `payload` field as opaque.
- Authentication is per-connection (Ed25519 nonce signing). Every
  authenticated socket has a `device_id` and a role (`desktop` | `device`).
  Once authenticated, all framing is JSON.
- The wire model is `UnifiedMessage` (`hiroserver/hiro-channel-sdk/src/hiro_channel_sdk/models.py`):
  `routing` + `content[]` + optional `event`. `ContentItem.body` is a
  string, by convention base64 for binary content (audio is already
  shipped this way end-to-end).

The shape of the answer is therefore constrained: **binary travels inside
JSON `ContentItem.body` over the gateway WebSocket**, unless and until we
change the relay. Anything that pretends otherwise is fighting the
deployment.

---

## 2. The two file-shaped problems

We deliberately solve them with **different mechanisms** because their
constraints are different.

| Problem | Examples | Size | Frequency | Consistency need |
|---|---|---|---|---|
| **Identity / cacheable assets** | character photos, optional UI icons, small voice samples | ≲ 2 MB | rarely changes; fetched once and cached | must invalidate when the resource version bumps |
| **General file transfer** | exported recordings, document attachments, model bundles, debug archives | up to many MB | on demand | usually content-addressed, often resumable |

Trying to ship a 20 MB model bundle through the same JSON-RPC response
that delivers a 200 KB avatar is what we are explicitly avoiding.

---

## 3. Identity assets: small, etag-gated, base64-in-response

### 3.1 Mental model

Identity assets are a *natural extension of Resource Sync*. The list
response advertises `etag`s; the device pulls the bytes for any row whose
etag changed. There are no ad-hoc events that carry binary; events stay
tiny `resource.changed` hints.

```
resource.changed("characters")           ──► characters.list
characters.list → rows with photo_etag   ──► characters.photo.get(id, if_none_match)
characters.photo.get → bytes_b64 | 304   ──► write to device cache, render
```

### 3.2 Wire shape

Add one JSON-RPC request method:

```jsonc
// request
{
  "method": "characters.photo.get",
  "params": {
    "character_id": "hiro",
    "if_none_match": "9f3a..."   // optional; sha256 hex or short content hash
  }
}

// response — body present
{
  "status": "ok",
  "data": {
    "character_id": "hiro",
    "etag": "9f3a...",
    "media_type": "image/png",
    "bytes_b64": "iVBORw0KGgo..."
  }
}

// response — not modified
{
  "status": "ok",
  "data": { "character_id": "hiro", "etag": "9f3a...", "not_modified": true }
}
```

### 3.3 Server-side rules

- Reuse the existing resolver
  `hirocli/domain/character.py::resolve_character_photo_file_for_http`.
  Same source of truth as the admin HTTP route. Falls back to the
  packaged default avatar when no upload exists.
- Compute `etag` deterministically: `sha256(file_bytes)[:16]` is enough.
  Persist no etag table — it is always cheap to recompute on read; the OS
  page cache absorbs the cost.
- Enforce a **hard inline cap** (`_MAX_INLINE_PHOTO_BYTES = 2_000_000`,
  already used in `hirocli/admin/features/characters/service.py`). If the
  resolved file is larger, downscale at upload time — never refuse the
  request. The "device profile" of a photo is a separate, server-resized
  artifact (e.g. max 512×512 JPEG/WebP).
- The handler is a Tool first
  (`consider-creating-tools-first.mdc`), exposed via the request method
  registry the same way `channels.list` and `policy.get` are wired in
  `hirocli/runtime/request_methods.py`.

### 3.4 Resource-sync integration

- `characters.list` (when added per the resource-sync plan acceptance
  criteria) returns each row with `photo_etag`.
- `channels.list` does **not** carry photo bytes. It may include the
  associated `character_id` so the device can look up the cached photo;
  it should not duplicate photo metadata that lives on `characters`.
- A `character_changes` signal bumps both the `characters` and
  `channels` resource versions (via `ResourceRegistry`) — no special
  case for photos.

### 3.5 Device-side rules

- Cache photos as files on disk under app-documents:
  `app-docs/character_photos/<character_id>.<ext>`. Track `etag` per
  character in Drift (or in `ResourceVersionStore`-style secure
  storage — author's choice; pick the one already used for the related
  resource). Never inflate device DB rows with raw bytes.
- On a `characters.list` refresh, diff `photo_etag` per row. For each
  changed row issue `characters.photo.get(id, if_none_match=cached_etag)`.
- On `not_modified`, just touch `lastSeenAt`. On a body, write the new
  bytes atomically (write-temp, fsync, rename), update the etag, and
  invalidate any in-memory `Image` providers.
- Treat photo fetches as **idempotent** in `GatewayRequestClient`, so the
  retry-on-reconnect path defined by the resource-sync plan covers them.

### 3.6 When to use this pattern (and when not)

Use it when **all** of these hold:

- Each artifact has a stable identity and a single canonical bytes
  representation.
- The expected size is well under the inline cap (≲ 2 MB after
  base64 → ≲ 2.7 MB JSON).
- The cardinality is bounded (≲ 100 of them per workspace), so a worst
  case "every etag changed at once" is still a few MB total.

Examples that fit: character photos, mascot icons, short character
preview voice clips.

Examples that do **not** fit, even if individually small: per-message
attachments, per-conversation thumbnails generated on the fly. Those go
through Section 4 because the cardinality is unbounded.

---

## 4. General files: chunked stream over the same WebSocket

For everything that does not satisfy Section 3.6, we use a **content-
addressed, chunked transfer** layered on top of the same gateway WS.

### 4.1 Concepts

- **Blob**: an immutable byte sequence identified by its sha256. Stored
  on the desktop under `<workspace>/data/blobs/<aa>/<sha256>` (the first
  two hex chars of the sha shard the directory). This generalizes the
  existing `hirocli/domain/media_store.py`, which already saves message
  attachments to `<workspace>/data/media/<channel>/<msg>.<ext>` using a
  base64 helper.
- **Manifest**: a small JSON record describing a blob (size, sha256,
  media type, optional `chunks`, optional `producer` metadata).
- **Stream session**: a sequence of `MESSAGE_TYPE_STREAM` frames
  (already reserved in `hiro_channel_sdk/constants.py:57`) that carry
  ordered chunks of one blob, correlated by `request_id`.

### 4.2 Wire shape

Two RPC methods plus stream frames:

```jsonc
// 1) Discover a blob
{ "method": "files.head",
  "params": { "ref": { "kind": "character_photo", "id": "hiro" } } }

// → { "status":"ok",
//     "data": { "blob_id":"sha256:9f3a...",
//               "size": 524288,
//               "media_type": "image/png",
//               "chunk_size": 49152,
//               "chunk_count": 11 } }

// 2) Open a download
{ "method": "files.get",
  "params": { "blob_id": "sha256:9f3a...",
              "offset": 0,        // resume support
              "length": null } }
// → ack response: { "status":"ok", "data":{ "session_id":"…", "chunk_count":11 } }
//   followed by N `message_type:"stream"` frames with the same request_id
```

Each stream frame:

```jsonc
{
  "version": "0.1",
  "message_type": "stream",
  "request_id": "<echo of files.get request_id>",
  "routing": { ... },
  "content": [
    { "content_type": "file",
      "body": "<base64 of one chunk>",
      "metadata": {
        "blob_id": "sha256:9f3a...",
        "seq": 3,
        "final": false,
        "chunk_sha256": "ab12..."   // optional, per-chunk integrity
      } }
  ]
}
```

The final chunk has `metadata.final = true`. The server may follow with a
terminal `response` frame echoing the original `request_id` and carrying
`{"status":"ok","data":{"sha256":"…","size":N}}`, which is what the
device verifies before accepting the assembled blob.

### 4.3 Why JSON-base64 first, binary later

- **Now (no relay changes):** Stream frames stay JSON+base64, so the
  gateway relay (`gateway/relay.py:relay_message`) remains a pure JSON
  forwarder and `_relay_kind` / `_relay_content_hint` keep working
  unchanged. Cost is the standard 33 % base64 inflation plus an extra
  JSON envelope per chunk.
- **Later (binary frames):** When measurements show the JSON path is the
  bottleneck, switch the devices channel and the gateway relay to send
  binary WS frames for `message_type:"stream"` payloads, with a small
  fixed-length header (`[u32 request_id_hash][u32 seq][u8 flags]`) and
  the raw bytes after. This is a transport-only change; the request
  semantics (`files.head` / `files.get`) are unaffected.

We document this as a **single design with two encodings** so that
nobody invents a third one.

### 4.4 Chunk sizing

- Default chunk size: **48 KB raw** (~64 KB after base64). Rationale:
  comfortably below typical default WS frame caps, gives sub-second
  progress updates over a 1 Mb/s link, keeps reassembly buffers small
  on resource-constrained devices.
- The chunk size is advertised in the `files.head` response, not
  hard-coded on the device. Future tuning lives in one place.
- Maximum encoded frame size budget across the stack: **256 KB**. Stay
  comfortably under that on both channel plugin and gateway.

### 4.5 Reliability and resume

- Blobs are content-addressed. The server stores incoming uploads in a
  scratch path `<sha256>.partial` and only renames on full sha match.
  Identical to what `hirocli/domain/media_store.py` would look like
  generalized.
- On reconnect, the device re-issues `files.get` with the highest
  contiguous `seq` it persisted, plus an `offset`. Idempotent by
  construction. The retry policy is the same as for any other
  idempotent request in `GatewayRequestClient`.
- Per-chunk sha is optional but cheap; helps surface a bad path quickly
  rather than after a full 50 MB transfer.
- Server-side: a download session is identified by `(client_request_id,
  blob_id)` and is cancellable. Cancellation is just stopping further
  stream frames; no special protocol needed.

### 4.6 Push vs pull

Both directions are supported, both follow Resource Sync's
"events-are-hints, requests-are-truth" rule:

- **Server → device push**: server bumps a resource version (e.g.
  `audio_assets`) and emits `resource.changed`. Device sees the new
  version, calls `files.head` for any references it does not yet have
  cached, then `files.get`. Server **never** initiates a stream
  unsolicited.
- **Device → server upload**: device calls `files.put.head` with size +
  sha256 + media type, server replies with a `session_id`, device sends
  stream frames with `request_id == session_id`. Server acks the final
  frame with `{"status":"ok","data":{"sha256":"…"}}`.

This means stream frames **always** correspond to a previously
established RPC. There is no spontaneous binary on the wire — important
for log scoping (`unified_message_log_scope`) and for the relay's
`_relay_kind` summaries.

### 4.7 Authorization and quotas

- Every blob fetch resolves through a per-resource resolver (e.g.
  `files_resolver.resolve("character_photo", id="hiro") → blob_id`).
  The resolver is the only place that decides whether a given device is
  allowed to fetch a given blob. Today this is "any authenticated
  device", but the choke point exists from day one so per-user scoping
  (already foreseen in `DeviceTargeting`) drops in cleanly.
- Add a per-session byte budget in the server (e.g. N MB / minute per
  device) to bound damage from a misbehaving client. Implement as a
  decorator around `files.get`, not inside the relay.

### 4.8 What this is **not**

- Not a generic CDN. Devices fetch only what they have a reference to.
- Not a sync engine. Selecting *which* references a device should fetch
  is a Resource Sync concern, not a files concern.
- Not a streaming media protocol. We do not target real-time playback;
  for that, the channel should negotiate a separate codec-aware path.

---

## 5. Where each kind of code lives

| Concern | Server | Device |
|---|---|---|
| RPC entry point | `hirocli/runtime/request_methods.py` (`<resource>.photo.get`, `files.head`, `files.get`) | `data/remote/gateway/gateway_request_client.dart` |
| Tool implementation | `hirocli/tools/character.py`, new `hirocli/tools/files.py` | n/a |
| Bytes resolver | `hirocli/domain/character.py::resolve_character_photo_file_for_http`, generalized `hirocli/domain/blob_store.py` | n/a |
| Stream framing | new `hirocli/runtime/stream_sender.py` (chunker) + `EnvelopeFactory.stream_chunk(...)` | new `application/files/stream_receiver.dart` |
| On-disk cache | `<workspace>/data/blobs/<aa>/<sha>` | `app-docs/blobs/<aa>/<sha>` + per-feature symlink/index (e.g. `character_photos/<id> → <sha>`) |
| Invalidation hook | `ResourceRegistry` entries that bump `characters` / `audio_assets` / etc. on domain signals | `ResourceSyncRegistry` fetcher that walks rows and calls the bytes RPCs |

The split exists so that adding a new file-bearing resource in the
future is a small fixed checklist, mirroring the resource-sync
acceptance criteria.

---

## 6. Choosing between the two patterns

A short decision rule for future authors:

1. Is the artifact a **bounded-cardinality identity asset** (one per
   character / icon / preset) that fits comfortably under the 2 MB
   inline cap? → **Section 3** pattern.
2. Otherwise: **Section 4** pattern. This includes anything per-message,
   anything potentially over a few MB, anything that benefits from
   resume, and anything where you would otherwise be tempted to encode
   a big blob in a regular `message` payload.

When in doubt, prefer Section 4. The chunked path is strictly more
general; Section 3 is an optimization for the easy case.

---

## 7. Open questions (do not pretend they are settled)

- **Compression**: today we send raw bytes. PNG/JPEG/WebP are already
  compressed; arbitrary files are not. A future option on `files.head`
  could advertise `encoding: "zstd"` and have the device decompress on
  the fly. Not a v1 concern; document the field name now so it does not
  collide later.
- **Media-type negotiation**: a device may want a 256×256 JPEG of a
  character photo even though the stored asset is a 1024×1024 PNG. We
  punt on this by having upload-time downscale produce one canonical
  device-profile artifact. If multi-profile becomes necessary, model it
  as separate blobs (`character_photo_512`, `character_photo_2048`)
  rather than dynamic resizing in the request path.
- **Encryption at rest on devices**: app-docs is private to the app on
  iOS/Android, but file-level encryption (e.g. for personal photos
  attached to messages) may be a later requirement. Decide once,
  document here, do not retrofit per feature.
- **Binary WS frames switch-over**: the trigger for moving from JSON
  base64 chunks to true binary frames is a measurement, not a feeling.
  Open a follow-up only when a profiling pass shows base64
  encode/decode or relay JSON throughput dominating a real workflow.

---

## 8. Summary

> Identity assets ride **JSON-RPC + etag + base64 body**, gated by
> Resource Sync.
> General files ride **`files.head` / `files.get` + chunked
> `message_type:"stream"` frames**, content-addressed by sha256, JSON
> base64 today and binary frames later.

Both rules collapse to the same underlying principle the rest of the
substrate already commits to: **events hint, requests are truth,
content is content-addressed**.
