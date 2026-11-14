# What is the project: HiroLeague

- [Read Here](../hiro-docs/mintdocs/hiro/get-started/introduction.mdx)
- [Architecture Docs](../hiro-docs/mintdocs/architecture/concepts/architecture-overview.mdx)

> **Editing mintdocs?** Before adding or changing any documentation under `../hiro-docs/mintdocs/`, read [mintdocs/AGENTS.md](../hiro-docs/mintdocs/AGENTS.md) and follow its rules (folder structure, style, and especially the **Diagrams** rule — mermaid wrapped in `<DiagramViewer>` with `actions={false}`).

# Conventions

## Admin UI during development

Check the admin UI from the **Vite dev site at `http://localhost:5173`** (usually running), **not** the served admin UI at port `18083` — the latter is rebuilt infrequently and is usually stale.

## Adding a `preferences.json` field

The full round trip (backend model, generated types, the UI control, the save) is in `.claude/rules/preferences-field.md`,
which loads when you open a preferences file. A new preference isn't done until it can be edited in the admin and
persists on Save.

## Inspecting a workspace (DBs, ledger, traces)

- **All databases live under `<workspace>/db/`** (consolidated layout): `workspace.db`, `data.db`, `knowledge.db`, `eval_results.db`, `graphiti_kuzu.db`, and the `qdrant/` vector store. Content blobs (`data/media`, `data/channel_photos`) and the `knowledge/fastembed_cache` stay outside `db/`.
- **Kuzu graph DB** (`<workspace>/db/graphiti_kuzu.db`) is **exclusively locked while the server runs** — can't open or even copy it. To query: `hiro stop`, inspect, then `hiro start` (admin flag).
- Readable **while the server runs** (no lock): eval results `<workspace>/db/eval_results.db` (SQLite; per-question `row_json` has recalled facts/answer/judge), the Graph Runs ledger `<workspace>/logs/graph.log` (CSV), and per-stage retrieval/ingest traces `<workspace>/logs/retrieval_trace/*.jsonl`. Live settings are in `<workspace>/preferences.json`. **Memory** eval corpora live in the **sibling `eval-corpus` repo** (`../hiro-code-reports/eval-corpus`; override with `$HIRO_EVAL_CORPUS_DIR`) — `benchmarks.yaml` groups them into benchmarks (LoCoMo, BEAM-128k). The **knowledge** corpus (`l3_synthetic`) stays in hiroleague's own `eval/`.

# Architecture

- **How the core, the apps and the kits fit together** is the Hiro League design (hiro-docs `standards/design.md`),
  loaded in every session. It is written from the code.
- **The core's internals** (Channel Manager, Communication Manager, Agent Manager, message persistence, resource sync,
  the protocol...) are the mintdocs **Architecture** tab (`../hiro-docs/mintdocs/docs.json`). Those pages are older than
  the code in places: check a page against the code before relying on it.
