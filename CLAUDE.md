# HiroLeague: the core

The core of Hiro League: the family list, roles and the one sign-in; WhatsApp, AI and voices; the admin; the SDK and the
two kits. What it is for people: [the introduction](../hiro-docs/mintdocs/hiro/get-started/introduction.mdx).

The Hiro League standard (hiro-docs `standards/`: the repo map, building and releasing, working rules, the design) loads
in every session through `~/.claude/rules/hiro-league.md`, and the coding guides load with the code. This file adds
only the core's own facts.

## The admin UI in dev

Check the admin from the **Vite dev site at `http://localhost:5173`** (usually running), not the served admin on
`18083`, which is rebuilt rarely and usually stale.

## Adding a `preferences.json` field

The full round trip (backend model, generated types, the UI control, the save) is in `.claude/rules/preferences-field.md`,
which loads when you open a preferences file. A new preference isn't done until it can be edited in the admin and
persists on Save.

## Inspecting a workspace (DBs, ledger, traces)

- **All databases live under `<workspace>/db/`:** `workspace.db`, `data.db`, `knowledge.db`, `eval_results.db`,
  `graphiti_kuzu.db`, and the `qdrant/` vector store. Content blobs (`data/media`, `data/channel_photos`) and
  `knowledge/fastembed_cache` stay outside `db/`.
- **The Kuzu graph DB** (`<workspace>/db/graphiti_kuzu.db`) is exclusively locked while the server runs: it can't be
  opened or even copied. To query it: `hiro stop`, inspect, then `hiro start` (admin flag).
- **Readable while the server runs** (no lock): eval results `<workspace>/db/eval_results.db` (SQLite; per-question
  `row_json` has recalled facts, answer and judge), the Graph Runs ledger `<workspace>/logs/graph.log` (CSV), and
  per-stage retrieval and ingest traces `<workspace>/logs/retrieval_trace/*.jsonl`. Live settings are in
  `<workspace>/preferences.json`.
- **Memory eval corpora** live in the sibling `eval-corpus` repo (`../codehiro/eval-corpus`; override with
  `$HIRO_EVAL_CORPUS_DIR`); `benchmarks.yaml` groups them into benchmarks (LoCoMo, BEAM-128k). The **knowledge**
  corpus (`l3_synthetic`) is in this repo's `eval/`.

## Architecture

- **How the core, the apps and the kits fit together** is the Hiro League design (hiro-docs `standards/design.md`),
  loaded in every session.
- **The core's internals** (Channel Manager, Communication Manager, Agent Manager, message persistence, resource sync,
  the protocol...) are the mintdocs **Architecture** tab (`../hiro-docs/mintdocs/docs.json`). Those pages are older than
  the code in places: check a page against the code before relying on it.
