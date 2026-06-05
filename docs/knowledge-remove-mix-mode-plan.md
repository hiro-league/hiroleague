# Plan: Remove `mix` mode + Kuzu-direct graphiti fetch + graphiti passage rerank

**Operating rule:** initial-dev / **no-backward-compatibility** — clean break, no shim mapping old `mix` prefs, no migration code. Re-ingest / pref-reset stated where needed.

Three independent, separable changes. Recommended order: **1 → 3 → 2** (1 is self-contained, 3 is tiny/additive, 2 is the largest and needs a spike).

## Background — what `mix` actually is

`mix` is the one retrieval route where the Graphiti fact search's supporting `chunk_ids` are folded into the Qdrant filter (`HasIdCondition`), so the hybrid+rerank runs **restricted to that chunk set**. It is the *only* mix-specific behavior; `graph_expand`, the facts-skeleton injection, and `valid_at` date-stamping are all **shared** with the `graphiti` leg.

Why remove it: `mix` and `graphiti` are capped to the **same** `graph_chunk_ids` set. `mix` does not broaden recall — it *adds* a query-relevance filter (hybrid + `min_score` + `top_k`) that can drop graph-chosen chunks the graph surfaced for good relational/temporal reasons. Removing it = trust the graph's selection.

The three vocabularies that all collapse from three-way to two-way:

| Layer | Before | After |
|---|---|---|
| Preference `KnowledgeGraphBackend` | `off \| graphiti \| mix` | `off \| graphiti` |
| Agent `graph_mode` | `off \| graphiti \| mix` | `off \| graphiti` |
| Eval legs | `flat \| graphiti \| mix` | `flat \| graphiti` |
| Ask-tab / tool toggle | `off \| on \| compare` (`on`→`mix`) | `off \| on \| compare` (`on`→`graphiti`) |

Retrieval paths after this plan:

```
flat      : query → Qdrant hybrid (whole corpus) → rerank → passages
graphiti  : graph picks chunk_ids → by-id fetch of those ids (no query hybrid) (+facts)
            (mix removed: no more "hybrid restricted to graph chunk_ids")
```

---

## Change 1 — Remove `mix` mode

Collapse the three-way vocabulary to two everywhere. The live "on" / `compare` paths repoint to `graphiti`.

### Backend (Python)

| File | Line(s) | Edit |
|---|---|---|
| `domain/preferences.py` | 442 | `KnowledgeGraphBackend = Literal["off", "graphiti"]` (default `"off"` at :480 unchanged) |
| `services/knowledge/eval_runner.py` | 77–81, 101 | `ALL_EVAL_MODES = ("flat", "graphiti")`; fix mode comments + `LegResult.mode` comment |
| `services/knowledge/service.py` | 778 | `_LEG_TO_GRAPH_MODE = {"flat": "off", "graphiti": "graphiti"}` |
| `services/knowledge/service.py` | 764 | `compare()` `graph_mode="mix"` → `"graphiti"` (+ comment) |
| `services/knowledge/service.py` | 619, 622 | `in ("graphiti","mix")` → `== "graphiti"` (warning guard) |
| `services/knowledge/agent/graph.py` | 85–98 | state docstring: drop the `"mix"` description |
| `services/knowledge/agent/graph.py` | 222–226 | routing comment: drop mix from the "vector" branch description |
| `services/knowledge/agent/graph.py` | 490, 877 | `not in ("graphiti","mix")` → `!= "graphiti"` (`graph_expand` gate, `_chunk_dates` gate) |
| `services/knowledge/agent/graph.py` | 581–582 | comment cleanup (facts feed "both legs" → just graphiti) |
| `services/knowledge/agent/graph.py` | 624–631 | **`build_filters` chunk_ids fold becomes dead code** — only `mix` ever set chunk_ids on the vector path (graphiti routes to `graph_only`, flat has none). Remove the `chunk_ids` merge; keep base filter build. |
| `tools/knowledge.py` | 345 | `("graphiti" if mode == GRAPH_MODE_ON else "off")` (constants `GRAPH_MODE_ON/OFF/COMPARE` stay) |
| `admin_svelte/routes/knowledge.py` | 195, 676–679 | `graph_mode=("graphiti" if body.graph_mode == "on" else "off")` + comments |
| `services/knowledge/eval_registry.py` | 66 | comment: `flat/graphiti` |

`_route_after_expand` (`graph.py:283`) stays correct as-is: with `graph_mode ∈ {off, graphiti}`, graphiti-with-chunk_ids → `graph_only`, everything else → `vector` (flat + graphiti soft-fallback). Just simplify its comment.

### Frontend (Svelte / TS)

| File | Line(s) | Edit |
|---|---|---|
| `lib/api/preferences.ts` | 83 | `backend: 'off' \| 'graphiti'` |
| `lib/features/preferences/sections/KnowledgeSection.svelte` | 399, 409 | remove `<option value="mix">`; rewrite hint (recommend **Graphiti**, drop "Mix recommended") |
| `lib/features/knowledge/state/knowledge-eval.svelte.ts` | 44, 50, 114 | `EVAL_ALL_LEGS = ['flat','graphiti']`; drop `mix:'Mix'`; fix default-legs comment |
| `lib/features/knowledge/shared/knowledge-events.ts` | 33, 55 | `EvalLeg = 'flat' \| 'graphiti'` |
| `lib/features/knowledge/ask/KnowledgeAskEvalBatch.svelte` | 180, 194, 578, 584 | leg-selector chips + help text |
| `lib/features/knowledge/ask/KnowledgeAskEvalTerminal.svelte` | 76, 86, 88 | drop `mix` preview-preference + mark string |
| `lib/api/knowledge.ts` | 372 | comment |
| `lib/features/preferences/state/preferences-edits.ts` | — | scan for `mix` seed/default (likely none) |

### Tests
`test_eval_runner.py` (mode-list asserts 256/267/269, `_LEG_ELAPSED` 160, leg-key sets 386), `test_compare_and_graph_mode.py` (63/77/121/188 — `compare`'s graph leg now `graphiti`), `test_eval_registry.py`, `test_eval_graphiti.py`, `test_eval_adam_corpus.py`, `domain/tests/test_preferences_graph.py` (add: `backend="mix"` now raises `ValidationError`).

### Docs
`docs/knowledge-graphiti-pivot-design.md`, `docs/graphiti-feedback.md` — update the leg/backend descriptions. Per `.claude/rules/document-executed-plans.md`, check mintdocs knowledge pages for the off/on/mix wording.

### Reflecting build updates (no-backward-compat)
Any `preferences.json` with `"backend": "mix"` will **fail Literal validation on load**. Action: set knowledge graph backend to `graphiti` (or `off`) in the admin UI / preferences before/after pulling.

### Verify
`pytest` the knowledge service + eval tests; `pnpm` typecheck/build the admin frontend.

---

## Change 2 — Kuzu-direct passage fetch for the graphiti leg

**Goal:** graphiti leg reads passages from Kuzu (`EpisodicNode.content`) instead of Qdrant, making the graph leg store-independent and folding `valid_at` into the same read.

### ⚠️ The catch that sizes this change
`EpisodicNode` (Kuzu) carries only: `content` (text), `source_description` (=`document_id`), `valid_at`, `name` (`"{title} · {chunk[:8]}"`). But `KnowledgeSearchHit` / citations need **title, heading_path, source_uri, owner_kind/id, category_id, subcategory_id, tags** — which today come **only from the Qdrant payload** (`hit_from_payload`, `vector_store.py:243`). So "just read text from Kuzu" loses citation metadata.

→ A truly Qdrant-free graphiti fetch requires **denormalizing that metadata onto the episode at ingest**. That makes this an ingest + schema change, not a read-path tweak.

### Step 2.0 — Spike (do first, gates the rest)
Confirm `graphiti_core`'s `EpisodicNode` can **persist + round-trip custom attributes** through `get_by_uuids` (it already round-trips `content`/`valid_at`). If yes → store metadata as node attributes. If not → store a small JSON blob in an existing free-text field, or a sidecar Kuzu node. **Decision point before committing to Change 2.**

### Step 2.1 — Ingest denormalization
- Extend `GraphitiEpisodeInput` (`graphiti_ingest.py:62`) with the citation fields (title, heading_path, source_uri, owner_*, category_*, tags).
- Populate them where episodes are built from chunks (the ingest caller that maps chunks → `GraphitiEpisodeInput`).
- Persist them in `_preseed_episode_node` (`graphiti_ingest.py:121`) per the 2.0 decision.

### Step 2.2 — New read path
- Add `KnowledgeService.fetch_hits_from_episodes(uuids)` (mirrors `fetch_hits_by_point_ids`, `service.py:824`) that reads `EpisodicNode.get_by_uuids`, builds `KnowledgeSearchHit` from `content` + denormalized metadata, score descending by graph rank, `valid_at` carried inline.
- `graph_fetch` (`graph.py:588`) calls the new method.
- In `build_context`, **skip `_chunk_dates`** for the graphiti leg (valid_at already on the hit) — removes the second graph round-trip (`graph.py:812`, `_chunk_dates` :869).
- Removes the "empty-text point skipped" failure mode (Kuzu always has `content`).

### Reflecting build updates
Denormalized fields only exist on **newly ingested** episodes → existing graphs must be **re-ingested** (`knowledge build-graph` / rebuild) to get citation metadata on the graphiti leg. Acceptable under no-backward-compat.

### Honest scoping note
The compute win is modest (today's `graph_fetch` is a cheap Qdrant by-id retrieve, not a vector search). The real payoff is architectural: graph leg independent of Qdrant + one read for text+date. Worth it, but **only proceed past 2.0 if the spike is clean**; otherwise this is more cost than benefit and we keep the current by-id Qdrant fetch.

---

## Change 3 — Passage reranking on the graphiti leg (behind the existing toggle)

**Goal:** let the cross-encoder `rerank` node run over the graphiti leg's by-id passages, gated by the existing `knowledge.retrieval.reranker.enabled` pref. Off = today's graph-ranked order (no behavior change); On = query-relevance reranked + `top_n`.

### Implementation (tiny)
- In `_add_retrieval_nodes` (`graph.py:232`), change the edge `graph_fetch → build_context` to `graph_fetch → rerank` (the vector path already goes `… → rerank → build_context`, so both converge).
- The `rerank` node (`graph.py:734`) already: no-ops to passthrough when reranker disabled / no candidates (keeps graph order, `reranked=False`), and sets `reranked=True` + relevance when active. No node changes needed.
- Net effect: graphiti passages get optional query-relevance reranking; **no `min_score` drop** (that lives in `vector_search`, not `rerank`), so the graph's selection is never silently culled — only reordered / trimmed-to-`top_n`.

This is the "feature we weren't using." Purely additive, reversible, no new pref. Independent of Change 2 (works whether passages come from Qdrant or Kuzu).

### Tests / Verify
Add a graph-leg test asserting: reranker off → graph order preserved; reranker on → reordered + `reranked=True`. Re-run the agent-graph routing tests.

---

## Sequencing & risk

```
Change 1  ──► self-contained, low risk, mechanical. Do first, ship.
Change 3  ──► ~1 edge + tests, behind existing toggle. Do next.
Change 2  ──► spike 2.0 FIRST → if clean: ingest + read change + re-ingest. Largest.
```

### Two relevant facts (also noted in feature 2)
- **graphiti already reranks at the fact level** via `search_recipe = cross_encoder` (`EDGE_HYBRID_SEARCH_CROSS_ENCODER` + `KnowledgeGraphRerankerPreferences`). Change 3 is about **passage**-level rerank, which is separate.
- **chunk text == episode `content`**: one chunk = one episode, `uuid = chunk_id = Qdrant point_id`, `content = chunk text` (`graphiti_ingest.py:3`). This is why Change 2 is possible at all.
