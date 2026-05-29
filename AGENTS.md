# What is the project: HiroLeague

- [Read Here](../hiro-docs/mintdocs/hiro/get-started/introduction.mdx)
- [Architecture Docs](../hiro-docs/mintdocs/architecture/concepts/architecture-overview.mdx)

# Architecture Documentation Index

This mirrors the `Architecture` tab in `../hiro-docs/mintdocs/docs.json`; use it to choose the right document before making architecture-sensitive changes.

## Concepts

- [Hiro League Concepts](../hiro-docs/mintdocs/architecture/concepts/architecture-overview.mdx) — Start here for the high-level Hiro League topology and definitions of Root Node, Hiro Server, Workspace, Nodes, Control Room, Gateway, third-party apps, and CLI commands.
- [Network topology](../hiro-docs/mintdocs/architecture/concepts/network-topology.mdx) — Use this for local-only, local-network, remote/VPS, and VPN deployment topology decisions.

### Hiro Server Components

- [Hiro Server Components](../hiro-docs/mintdocs/architecture/concepts/hiro-server-components.mdx) — Use this to understand how the workspace server process wires HTTP Server, Channel Manager, Communication Manager, Agent Manager, Metrics Collector, and Admin UI.
- [Channel Manager](../hiro-docs/mintdocs/architecture/concepts/channel-manager.mdx) — Use this for channel plugin subprocess lifecycle, JSON-RPC handling, infrastructure events, pairing flow, and inbound/outbound channel routing.
- [Communication Manager](../hiro-docs/mintdocs/architecture/concepts/communication-manager.mdx) — Use this for UnifiedMessage validation, request/event/message routing, graph-event subscription, persistence side effects, outbound envelopes, and resource-change dispatch.
- [Agent Manager](../hiro-docs/mintdocs/architecture/concepts/agent-manager.mdx) — Use this for assistant runtime boundaries, character/channel resolution, graph lifecycle, memory ownership, and how graph events reach Communication Manager.
- [HTTP Server](../hiro-docs/mintdocs/architecture/concepts/http-server.mdx) — Use this for the local FastAPI control surface, status/channels/tools/characters/metrics/lifecycle endpoints, and local Tool Registry access.

### Message Persistence

- [Message Lifecycle](../hiro-docs/mintdocs/architecture/concepts/message-persistence.mdx) — Use this for the durable message and attachment model across server and devices, including row metadata, blob identity, history reads, and reconciliation.
- [File Transfer & Resolver](../hiro-docs/mintdocs/architecture/concepts/message-persistence/file-transfer-and-resolver.mdx) — Use this for `files.get`, `files.head`, reference resolution, blob authorization, chunked streaming, and device-side integrity verification.
- [Device History Sync](../hiro-docs/mintdocs/architecture/concepts/message-persistence/device-history-sync.mdx) — Use this for Flutter/device local mirror behavior, message history watermarks, attachment fetch loops, first-time load, reconnect sync, and bulk-clear reconciliation.

## Misc

- [Tools architecture](../hiro-docs/mintdocs/architecture/misc/tools-architecture.mdx) — Use this for the shared Tool abstraction that unifies CLI commands, AI agent tools, and HTTP API calls behind one operation implementation.
- [Workspace folder](../hiro-docs/mintdocs/architecture/misc/workspace-folder.mdx) — Use this for workspace directory layout, `workspace.db`, `data.db`, character files, logs, runtime files, media storage, and the global registry location.
- [Workspace Preferences](../hiro-docs/mintdocs/architecture/misc/preferences.mdx) — Use this for `preferences.json`, validated preference writes, runtime preference snapshots, preference change events, and live subsystem reactions.
- [Agent Graph](../hiro-docs/mintdocs/architecture/concepts/agent-graph.mdx) — Use this for the per-message assistant workflow nodes, LangGraph event stream, model/tool loop, optional STT/vision/TTS, failure semantics, and agent metadata.
- [Resource Sync](../hiro-docs/mintdocs/architecture/concepts/resource-sync.mdx) — Use this for the `resource.changed` invalidation pattern, server/device sync registries, version counters, reconnect recovery, and adding new cached resources.
- [Channel Plugins](../hiro-docs/mintdocs/architecture/concepts/channel-plugins.mdx) — Use this for standalone plugin topology, plugin lifecycle, Channel Manager JSON-RPC methods, persisted plugin configuration, and the built-in `devices` plugin.
- [Domain Event Bus](../hiro-docs/mintdocs/architecture/concepts/domain-event-bus.mdx) — Use this for the thread-safe bridge from synchronous domain mutations to async runtime subscribers, domain event types, publishing/subscribing rules, and preference reactors.

## Protocol

- [Protocol contract](../hiro-docs/mintdocs/architecture/protocol/protocol-contract.mdx) — Use this for the language-neutral wire contract across Hiro Server, channel plugins, Hiro Gate, and devices, including UnifiedMessage, gateway envelopes, auth/pairing frames, requests, responses, streams, and metadata keys.
- [UnifiedMessage reference](../hiro-docs/mintdocs/architecture/protocol/unified-message.mdx) — Use this for detailed UnifiedMessage fields, validation rules, content/event/request/response shapes, stream chunk requirements, implemented request methods, metadata locations, and wire examples.

## Design Decisions

- [Memory requirements](../hiro-docs/mintdocs/architecture/design-decisions/memory-requirements.mdx) — Use this for long-term memory requirements, memory manager/backend evaluation, selected Mem0 + Qdrant + Kuzu stack, and phased memory implementation plan.

