# hiro-channel-devices

Mandatory Hiro channel plugin that owns the gateway WebSocket connection and
bridges gateway relay envelopes to/from `UnifiedMessage`.

## Direction mapping

- Inbound from gateway:
  - envelope: `{ sender_device_id, payload: <UnifiedMessage> }`
  - output to Hiro: `channel.receive` with `UnifiedMessage`
- Outbound from Hiro:
  - input: `channel.send` with `UnifiedMessage`
  - envelope to gateway: `{ target_device_id?, payload: <UnifiedMessage> }`

## Events emitted to Hiro

- `gateway_connected`
- `gateway_disconnected`
