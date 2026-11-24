# HiroLeague: the core

**Hiro** is a self-hosted platform for a household's AI apps, and the framework those apps are built with. **Hiro
League** is the whole: the core and its extensions.

The core holds what every app needs and none should build twice: the people and their roles, one sign-in, AI models and
their budgets, voices, memory, messaging over WhatsApp and the family's devices, and Hiro, the assistant people talk to.

An **extension** is an app built on the core with its two kits, one for the backend and one for the UI. It owns one
area, with its own pages and data, and takes everything else from the core. Extensions reach each other only through
the core. Some are built in, and others come from the community.

**Built today:** the core and its admin, the two kits, the device app, and six extensions: HomeHiro, NetHiro, CodeHiro,
TrainHiro, StudyHiro and EvalHiro.

**Where it's going:**
- extensions from the community, and CodeHiro published;
- personal business, beside the household;
- Hiro searching your chats, email and files;
- a life coach;
- news and social media filtered to what matters to you;
- 3D avatars you can speak to;
- pages and tools built from a prompt.

The core of Hiro League: the family list, roles and the one sign-in; WhatsApp, AI and voices; the admin; the SDK and the
two kits. What it is for people: [the introduction](../hiro-docs/mintdocs/hiro/get-started/introduction.mdx).

The Hiro League standard (hiro-docs `standards/`: the repo map, the task workflow, the working rules) loads in every
session through `~/.claude/CLAUDE.md`; the design and the coding guides are read when needed (the standard's README
says when). This file adds only the core's own facts.

## The admin UI in dev

Check the admin from the **Vite dev site on the environment's 7N02** (env0: `http://127.0.0.1:7002`, started by
`hiro-work up 0`), not the admin the core serves itself, which is rebuilt rarely and usually stale. The environments
and their ports: hiro-docs `standards/workflow/environments.md`.

## Adding a `preferences.json` field

The full round trip (backend model, generated types, the UI control, the save) is in `.claude/rules/preferences-field.md`,
which loads when you open a preferences file. A new preference isn't done until it can be edited in the admin and
persists on Save.

## Inspecting a workspace (DBs, ledger, traces)

- **All databases live under `<workspace>/db/`:** `workspace.db`, `data.db`, `knowledge.db`, `graphiti_kuzu.db`,
  and the `qdrant/` vector store. Content blobs (`data/media`, `data/channel_photos`) and
  `knowledge/fastembed_cache` stay outside `db/`.
- **The Kuzu graph DB** (`<workspace>/db/graphiti_kuzu.db`) is exclusively locked while the server runs: it can't be
  opened or even copied. To query it: `hiro stop`, inspect, then `hiro start` (admin flag).
- **Readable while the server runs** (no lock): the Graph Runs ledger `<workspace>/logs/graph.log` (CSV), and
  per-stage retrieval and ingest traces `<workspace>/logs/retrieval_trace/*.jsonl`. Live settings are in
  `<workspace>/preferences.json`.
- **The memory eval** (its corpora, runs and results) is EvalHiro's (`../evalhiro`). The core serves it `ai.embed`,
  `ai.rerank` and `memory.settings`, and shares the memory library (`hiroserver/hiro-memory`) with it.

## Architecture

- **How the core, the apps and the kits fit together** is the Hiro League design (hiro-docs `standards/design.md`),
  read when needed (the standard's README says when).
- **The core's internals** (Extension Manager, Communication Manager, Agent Manager, message persistence, resource sync,
  the protocol...) are the mintdocs **Architecture** tab (`../hiro-docs/mintdocs/docs.json`). Those pages are older than
  the code in places: check a page against the code before relying on it.
