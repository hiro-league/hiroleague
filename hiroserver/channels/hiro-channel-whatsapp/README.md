# hiro-channel-whatsapp

WhatsApp channel plugin for Hiro-League, built on
[neonize](https://github.com/krypton-byte/neonize) (Python bindings over the Go
`whatsmeow` multi-device library).

See the design and plan:
- `docs/whatsapp-channel-design.md`
- `docs/whatsapp-channel-implementation.md`

## Status

**Phase 1 — Link & receive (raw).** Links a WhatsApp account via QR, persists the
session, and logs inbound messages. Routing into the agent and sending replies
land in later phases.

## Dev install

```bash
hiro channel install whatsapp --editable       # or: hiro channel setup with a workspace dir
hiro channel setup whatsapp                     # writes the channel_plugins row
hiro stop && hiro start                          # ChannelManager spawns the plugin
```

On first run, an ASCII QR is written to the plugin log
(`<log-dir>/channel-whatsapp*.log`) — scan it from WhatsApp → Linked Devices. The
session persists to `~/.hiro/whatsapp/session.db` (until Phase 3 pushes a
workspace-scoped path), so later restarts reconnect without a new QR.

> Uses an unofficial WhatsApp Web library — see the design doc for the accepted
> ToS/ban-risk trade-off. No backward-compatibility guarantees (initial development).
