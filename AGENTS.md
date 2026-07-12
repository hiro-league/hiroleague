# What is the project: HiroLeague

- [Read Here](../hiro-docs/mintdocs/hiro/get-started/introduction.mdx)
- [Architecture Docs](../hiro-docs/mintdocs/architecture/concepts/architecture-overview.mdx)

> **Editing mintdocs?** Before adding or changing any documentation under `../hiro-docs/mintdocs/`, read [mintdocs/AGENTS.md](../hiro-docs/mintdocs/AGENTS.md) and follow its rules (folder structure, style, and especially the **Diagrams** rule — mermaid wrapped in `<DiagramViewer>` with `actions={false}`).

# Conventions

## Admin UI during development

Check the admin UI from the **Vite dev site at `http://localhost:5173`** (usually running), **not** the served admin UI at port `18083` — the latter is rebuilt infrequently and is usually stale.

## Adding a `preferences.json` field

A new preference is not done when the backend model has it — it must be **representable and editable in the Preferences admin UI**, and it must actually **persist on Save**. Do the whole round-trip, in order:

1. **Backend model** — add the field to the right model in `hiroserver/hirocli/src/hirocli/domain/preferences.py` (with `Field(...)` bounds/default). The PATCH endpoint is **schema-driven** (`preferences_runtime._set_path` walks the pydantic model), so a new field becomes a valid write path automatically — no backend allow-list to update.
2. **Regenerate frontend types** — from `admin_frontend/`, run `npm run gen:prefs-types` (updates `src/lib/api/generated/*` from the Pydantic model). `npm run check` fails if these artifacts are stale. API-only computed fields (e.g. `*_resolved`) go in `preferences-types.ts`, not the generated file.
3. **UI control** — add an input bound to `ctrl.draft.<section>.<field>` in the correct `admin_frontend/src/lib/features/preferences/sections/**/*.svelte` card (with `oninput={ctrl.markDirty}` or `onchange={ctrl.markDirty}`). **If you're unsure which section/tab a field belongs in, ask the user — do not guess.**
4. **Save payload** — `editsForSave` structurally diffs baseline vs draft using `/preferences/schema` field metadata (`readOnly`, `writeWhole`, `preferencesSaveSkip`, nullable + `model_kind`). A new bound field is picked up automatically; you should not edit path-set allow-lists in `preferences-edits.ts`. Run `npm run test:unit -- preferences-edits` after changing save policy helpers.

Run `npm run check` (admin_frontend) and the preferences tests after, and remember a backend field change needs a **server restart** to take effect.

## Inspecting a workspace (DBs, ledger, traces)

- **All databases live under `<workspace>/db/`** (consolidated layout): `workspace.db`, `data.db`, `knowledge.db`, `eval_results.db`, `graphiti_kuzu.db`, and the `qdrant/` vector store. Content blobs (`data/media`, `data/channel_photos`) and the `knowledge/fastembed_cache` stay outside `db/`.
- **Kuzu graph DB** (`<workspace>/db/graphiti_kuzu.db`) is **exclusively locked while the server runs** — can't open or even copy it. To query: `hiro stop`, inspect, then `hiro start` (admin flag).
- Readable **while the server runs** (no lock): eval results `<workspace>/db/eval_results.db` (SQLite; per-question `row_json` has recalled facts/answer/judge), the Graph Runs ledger `<workspace>/logs/graph.log` (CSV), and per-stage retrieval/ingest traces `<workspace>/logs/retrieval_trace/*.jsonl`. Live settings are in `<workspace>/preferences.json`. **Memory** eval corpora live in the **sibling `eval-corpus` repo** (`../hiro-code-reports/eval-corpus`; override with `$HIRO_EVAL_CORPUS_DIR`) — `benchmarks.yaml` groups them into benchmarks (LoCoMo, BEAM-128k). The **knowledge** corpus (`l3_synthetic`) stays in hiroleague's own `eval/`.

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
- [Image Generation](../hiro-docs/mintdocs/architecture/misc/image-generation.mdx) — Use this for text-to-image: the Cloudflare Workers AI (FLUX.1 schnell) provider, image profiles (recipes) in preferences, the `generate_image` tool, provider account-id credentials, and the Image Lab admin page.
- [Agent Graph](../hiro-docs/mintdocs/architecture/concepts/agent-graph.mdx) — Use this for the per-message assistant workflow nodes, LangGraph event stream, model/tool loop, optional STT/vision/TTS, failure semantics, and agent metadata.
- [Resource Sync](../hiro-docs/mintdocs/architecture/concepts/resource-sync.mdx) — Use this for the `resource.changed` invalidation pattern, server/device sync registries, version counters, reconnect recovery, and adding new cached resources.
- [Channel Plugins](../hiro-docs/mintdocs/architecture/concepts/channel-plugins.mdx) — Use this for standalone plugin topology, plugin lifecycle, Channel Manager JSON-RPC methods, persisted plugin configuration, and the built-in `devices` plugin.
- [Domain Event Bus](../hiro-docs/mintdocs/architecture/concepts/domain-event-bus.mdx) — Use this for the thread-safe bridge from synchronous domain mutations to async runtime subscribers, domain event types, publishing/subscribing rules, and preference reactors.

## Protocol

- [Protocol contract](../hiro-docs/mintdocs/architecture/protocol/protocol-contract.mdx) — Use this for the language-neutral wire contract across Hiro Server, channel plugins, Hiro Gate, and devices, including UnifiedMessage, gateway envelopes, auth/pairing frames, requests, responses, streams, and metadata keys.
- [UnifiedMessage reference](../hiro-docs/mintdocs/architecture/protocol/unified-message.mdx) — Use this for detailed UnifiedMessage fields, validation rules, content/event/request/response shapes, stream chunk requirements, implemented request methods, metadata locations, and wire examples.

## Design Decisions

- [Memory requirements](../hiro-docs/mintdocs/architecture/design-decisions/memory-requirements.mdx) — Use this for long-term memory requirements, memory manager/backend evaluation, selected Mem0 + Qdrant + Kuzu stack, and phased memory implementation plan.

