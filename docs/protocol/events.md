# Protocol Events

Events are `UnifiedMessage` values with `message_type: "event"`, empty
`content`, and an `event` payload.

| Event | Direction | Data |
|---|---|---|
| `message.received` | server to device | none |
| `message.transcribed` | server to device | `transcript: string` |
| `message.voiced` | server to device | `audio: base64 string`, `mime_type: string`, `duration_ms: number` |
| `message.content_added` | reserved | event-specific object |

