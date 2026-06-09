# Eval Recall — Split Facts / Entities / Episodes Into Per-Kind Tables

> **Status:** ✅ implemented (both steps). Step A = the three per-kind tables in
> `KnowledgeEvalPanel.svelte`; Step B = `node_rows`/`episode_rows` (with rerank score) threaded
> from the traced search pipeline through `GraphitiExpansion` into the recall hits.
> **Mode:** initial development — **no backward compatibility / no migration / no wrappers**
> (repo rule, explicitly abided — the score-return signature changes were applied at every call
> site, including tests, with no shims).
>
> **Companions:** [`eval-corpus-tracks-design.md`](eval-corpus-tracks-design.md) (the memory/knowledge
> eval tracks that produce these recalled items) and
> [`memory-graphiti-replacement-design.md`](memory-graphiti-replacement-design.md) (the
> `remember`/`recall` engine whose `search()` returns the hits rendered here).

## Problem

The eval results fold renders **all recalled items in one table** — facts, entities, and
episodes mixed together — via the `recalledTable` snippet in
[`KnowledgeEvalPanel.svelte`](../admin_frontend/src/lib/features/knowledge/eval/KnowledgeEvalPanel.svelte).
That table's columns are **fact-shaped**: `Fact · Relationship · Valid from · Invalid at · Status · Score`.

Two consequences the user flagged:

1. **Wrong columns for non-facts.** Entity and episode rows leave `Relationship`, `Valid from`,
   `Invalid at` blank and show `—` for `Status` (those concepts only apply to fact edges). The
   table reads as "mostly empty columns" for half its rows.
2. **Entities show no score — but they have one.** The recalled-facts table prints `Score = —` for
   entity rows, yet the **retrieval trace** (the `Microscope` dialog) shows real per-node scores.
   This is a **backend payload gap**, not just a display choice (see below).

## Current state (where the data comes from)

`memory.search()` →
[`graphiti_conversation.py:269-274`](../hiroserver/hirocli/src/hirocli/services/memory/graphiti_conversation.py:269)
builds the hit list that becomes `RecalledFact[]`:

```python
fact_rows = tuple(getattr(expansion, "fact_rows", ()) or ())
hits = [dict(row) for row in fact_rows]                                   # facts: STRUCTURED
hits.extend({"memory": summary, "kind": "entity"}  for summary in node_memories)     # entity: text only
hits.extend({"memory": body,    "kind": "episode"} for body    in episode_memories)  # episode: text only
```

- **Facts** come from `expansion.fact_rows` — full dicts (score, `valid_at`/`invalid_at`,
  relationship `name`, source/target uuids). The table's columns are designed for exactly these.
- **Entities** are built from `expansion.node_memories`, a tuple of **plain summary strings** — no
  score, no uuid, no type.
- **Episodes** are built from `expansion.episode_memories`, a tuple of **plain body strings** — no
  score, no timestamp, no chunk id.

The `RecalledFact` type
([`knowledge-events.ts:47-60`](../admin_frontend/src/lib/features/knowledge/shared/knowledge-events.ts:47))
already has a nullable `score` and a `kind` discriminator, so the frontend is *shaped* for per-kind
rendering — it's the **producer** (the `entity`/`episode` branches above) that drops the metadata.

## Proposal

### A. Frontend — three tables, per-kind columns

Replace the single `recalledTable(facts)` with a small dispatcher that partitions by `kind` and
renders up to three sub-tables, each with only the columns that apply. Each is collapsible and
shows a count; empty kinds are omitted.

| Table | Columns | Notes |
|---|---|---|
| **Facts** (`kind = 'fact'`) | Fact · Relationship · Valid from · Invalid at · Status · Score | Unchanged from today's columns. `Status` = active / superseded (temporal lens). |
| **Entities** (`kind = 'entity'`) | Entity · Type · Score | `Type` = node label (Person/Org/…) when available; truncate summary + tooltip (matches the #6 fix). |
| **Episodes** (`kind = 'episode'`) | Episode · When · Score | `When` = source turn timestamp; body truncated + tooltip. |

Shared niceties carried over from this pass: long text is `line-clamp`'d with a full-text `title`,
and `Score` is right-aligned `tabular-nums` (`f.score.toFixed(3)` / `—`).

**Layout option (pick one):** stacked sections (Facts → Entities → Episodes, vertical) vs. a small
tab strip inside the fold. Recommendation: **stacked**, since counts are usually small and stacking
avoids hiding data behind a click during eval review.

### B. Backend — populate entity/episode score (+ light metadata)

To make Entities/Episodes show a real `Score`, the `search()` hit builders must carry the metadata
the trace already computes. Concretely, surface structured rows from the expansion (mirroring
`fact_rows`):

- Add `node_rows` (and `episode_rows`) to `GraphitiExpansion` alongside `node_memories` /
  `episode_memories`, each a dict like `{"memory", "kind", "score", "uuid", "name"/"type", ...}`.
- Build hits from those structured rows when present, falling back to the current text-only shape
  for older test fakes (the same `getattr(..., ()) or ()` pattern already used for `fact_rows`).

**Open question (needs a code check at implement time):** confirm where the per-node / per-episode
score is available on the expansion / rerank stage. The score is demonstrably present in the
retrieval **trace** (`retrieval_trace` / `flush_graph_expand`,
[`graphiti_conversation.py:240-254`](../hiroserver/hirocli/src/hirocli/services/memory/graphiti_conversation.py:240)),
so the value exists; the work is threading it onto the returned hits rather than only into the
trace sidecar. If scores are reranker-stage only, decide whether entity score = pre-rerank
similarity or post-rerank relevance (recommend: whatever the Facts column already shows, for
consistency).

## Tradeoffs / scope

- **Frontend-only slice** (Table A) is cheap and immediately improves readability, but Entities
  would still show `Score = —` until Table B lands. We can ship A first, B second.
- **Table B** touches the recall engine's return contract (`GraphitiExpansion` + `search()`), so it
  needs the entity/episode-score corpus to verify and may ripple into the `memory_block` the agent
  sees (the dated-text `memory` field must stay unchanged — only *added* fields). Bounded, but not
  a one-liner.
- No-backward-compat: we extend `GraphitiExpansion` and the hit dicts directly; no shim for the
  old text-only tuples beyond the existing test-fake `getattr` default.

## Recommendation

Two-step: **(1)** split the table by kind (frontend only) so the columns stop lying; **(2)** thread
entity/episode scores onto the recall hits so the Entities/Episodes tables show real relevance.

## What shipped

- **Step A (frontend)** — [`KnowledgeEvalPanel.svelte`](../admin_frontend/src/lib/features/knowledge/eval/KnowledgeEvalPanel.svelte):
  `recalledTable` now partitions by `kind` and renders stacked **Facts / Entities / Episodes**
  cards, each with its own columns (Facts: Fact·Relationship·Valid from·Invalid at·Status·Score;
  Entities: Entity·Type·Score; Episodes: Episode·When·Score). Long text is clamped + tooltip'd.
- **Step B (backend)** — the traced node/episode search functions
  ([`graphiti_fact_search.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_fact_search.py))
  now return their `uuid→score` map; `_traced_search` returns a 6-tuple; `search_chunk_ids`
  ([`graphiti_search.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_search.py))
  builds `node_rows`/`episode_rows` (score + name/type / timestamp) added to `GraphitiExpansion`;
  [`graphiti_conversation.py`](../hiroserver/hirocli/src/hirocli/services/memory/graphiti_conversation.py)
  builds entity/episode recall hits from those rows (falling back to the text-only shape for older
  fakes). The `*_memories` plain-string fields are untouched, so the agent's `memory_block` is
  unchanged. Scores populate at the **trace** observability tier (same place facts get theirs).

**Verified:** 44 backend search/memory tests pass; `svelte-check` clean on the touched files.
