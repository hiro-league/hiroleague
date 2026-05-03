# Server Info Requirements And Design

This document captures the requirements and design for advertising Root Node
policy and channel-level media capabilities to device nodes.

The feature is implemented around the `server.info` UnifiedMessage event and the
`server.info.get` request method. It replaces the older audio-specific preference
shape with a media capability model that can grow to voice, image, video, and
file input/output.

## Goals

- Tell device nodes what the Root Node currently allows.
- Tell device nodes what each conversation channel can effectively do.
- Keep the Root Node authoritative when device UI state and server capability
  disagree.
- Let device UI show unavailable opportunities as dimmed controls instead of
  hiding them.
- Support proactive updates on connection and settings changes.
- Keep the protocol general enough to add more server information later without
  introducing one event per setting.

## Non-goals

- Do not add speculative fields beyond the current policy and channel capability
  snapshot.
- Do not persist the user's "reply in voice" preference on the server yet.
  That remains device-local UI state for now.
- Do not implement image, video, or file generation capability yet. Those flags
  are present in the shape but resolve to `false`.
- Do not preserve backward compatibility with the old audio preference fields.
  This project is still unreleased initial development, so the current shape
  replaces the old one directly.

## Preference model

Workspace preferences now expose a media policy instead of audio-specific
booleans.

```json
{
  "media": {
    "input": {
      "voice": true,
      "image": false,
      "video": false,
      "file": false
    },
    "output": {
      "voice": false,
      "image": false,
      "video": false,
      "file": false
    }
  }
}
```

Policy is the workspace-level ceiling. It answers "may the Root Node allow this
modality at all?" It is not directly enough for device UI decisions because some
capabilities also depend on the active character and configured providers.

The source model is `MediaPreferences` and `ModalityFlags` in
`hiroserver/hirocli/src/hirocli/domain/preferences.py`.

## Effective channel capabilities

Device nodes consume effective channel capabilities, not policy alone.

Effective capability is resolved per conversation channel:

```text
effective = workspace policy AND channel character support AND provider/model availability
```

Current rules:

- `input.voice` is true only when workspace policy allows voice input and an STT
  model resolves.
- `output.voice` is true only when workspace policy allows voice output and the
  channel character resolves a usable TTS voice model.
- `image`, `video`, and `file` currently resolve to `false` for both input and
  output.

The canonical resolver is `resolve_modality_capability()` in
`hiroserver/hirocli/src/hirocli/domain/server_info.py`.

## `server.info` snapshot

The Root Node sends a `server.info` event with a versioned snapshot.

```json
{
  "version": 1,
  "policy": {
    "input": {
      "voice": true,
      "image": false,
      "video": false,
      "file": false
    },
    "output": {
      "voice": true,
      "image": false,
      "video": false,
      "file": false
    }
  },
  "channels": [
    {
      "id": 1,
      "name": "devices:device_abc",
      "character": {
        "id": "default",
        "name": "Hiro"
      },
      "capabilities": {
        "input": {
          "voice": true,
          "image": false,
          "video": false,
          "file": false
        },
        "output": {
          "voice": false,
          "image": false,
          "video": false,
          "file": false
        }
      }
    }
  ]
}
```

Fields:

- `version` is the snapshot schema version.
- `policy` is the persisted workspace media policy.
- `channels` lists known conversation channels.
- `channels[].character` gives the device enough context to label the channel.
- `channels[].capabilities` is the effective capability set for that channel.

The event is a normal UnifiedMessage:

- `message_type`: `event`
- `event.type`: `server.info`
- `event.data`: the snapshot above
- `content`: empty

The event builder is `EnvelopeFactory.server_info_event()`.

## Request/response refresh

Device nodes also request the current snapshot explicitly with:

```json
{
  "method": "server.info.get",
  "params": {}
}
```

The response payload contains the same snapshot shape used by the `server.info`
event.

This pull path is required because push delivery can race with a device node's
receive-loop startup after reconnect. The device should request `server.info.get`
after connecting and also accept pushed `server.info` events. Applying the same
snapshot twice is safe.

## Push triggers

The Root Node proactively sends `server.info` in these cases:

- A device node connects or reconnects.
- Workspace preferences are saved.
- A character changes.
- A conversation channel changes.

The gateway emits `device_connected` and `device_disconnected` channel events to
the Root Node. The Root Node tracks connected device IDs and pushes snapshots
through `ServerInfoBroadcaster`.

On reconnect, the Root Node always sends a fresh snapshot, even if nothing
changed since the last one. This keeps the device node simple and clears stale
local state.

## Device behavior

The device node stores the most recent snapshot locally.

For UI:

- Use `channels[].capabilities` to decide whether a control is currently active.
- Show unavailable controls dimmed, not hidden.
- Keep the per-channel "reply in voice" toggle device-local for now.
- When the user asks for a voice reply, send `routing.metadata.request_voice_reply`
  on the outgoing message.

The server decides whether the request can be honored. Device-local preference is
an ask, not authority.

## Server behavior on mismatch

If a device asks for voice output and `output.voice` is false, the Root Node does
not reject the message. It sends the normal text reply, skips TTS, and writes a
warning log because the mismatch deserves inspection.

Log shape:

```text
⚠️ Voice reply requested but unavailable — <peer> · output.voice=false
```

The warning should include a machine-readable reason and message/channel context
where available.

Current reason:

- `policy_or_character_unavailable`

Future reasons may split this into:

- `policy_disabled`
- `character_no_voice_models`
- `no_provider_credentials`
- `tts_resolve_failed`

## Implementation map

- Server info models and resolvers:
  `hiroserver/hirocli/src/hirocli/domain/server_info.py`
- Media policy model:
  `hiroserver/hirocli/src/hirocli/domain/preferences.py`
- Event builder:
  `hiroserver/hirocli/src/hirocli/runtime/envelope_factory.py`
- Push broadcaster:
  `hiroserver/hirocli/src/hirocli/runtime/server_info_broadcaster.py`
- Request method:
  `hiroserver/hirocli/src/hirocli/runtime/request_methods.py`
- Gateway connection events:
  `hiroserver/gateway/src/hirogateway/relay.py`
- Devices channel event bridge:
  `hiroserver/channels/hiro-channel-devices/src/hiro_channel_devices/plugin.py`
- Dart snapshot model:
  `device_apps/lib/domain/models/server_info/server_info.dart`
- Dart gateway refresh/apply flow:
  `device_apps/lib/application/gateway/gateway_notifier.dart`

## Versioning note

The feature intentionally follows the no-backward-compatibility rule for
unreleased development. Existing development workspaces with old audio preference
fields should recreate or rewrite `preferences.json` instead of relying on a
migration layer.
