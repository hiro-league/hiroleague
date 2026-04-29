# Protocol Metadata Keys

`routing.metadata` is an extension object. These keys currently have behavior in
the Python server or Flutter client:

| Key | Producer | Consumer | Purpose |
|---|---|---|---|
| `channel_id` | Flutter client / server responses | Flutter client | Maps a wire message to a local conversation channel. |
| `device_name` | Hiro channel manager / gateway handshake | logs, gateway, runtime | Human-readable paired device name. |
| `sender_device_id` | devices channel | runtime/logging | Original gateway sender identity. |
| `friendly_name` | devices channel | runtime/logging | Legacy display label for sender identity. |
| `request_voice_reply` | client | agent manager | Per-message override for voice reply generation. |

New metadata keys should be documented here before they are used across process
or language boundaries.
