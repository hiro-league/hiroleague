## Question
can you review the implementation of @knowledge-graphiti-pivot-design.md  and give me feedback only for the gaps (skip successful compliance). sort/group them by priority plz

> **⚠️ Superseded (2026-06-05):** the items below that call for **adding a `mix` leg**
> (e.g. "eval is 2-way, design mandates 3-way") are no longer valid — `mix` was
> **removed**, retrieval is two-way (`flat`/`graphiti`). See
> [`knowledge-remove-mix-mode-plan.md`](knowledge-remove-mix-mode-plan.md).

## Feedback


I'll start by finding and reading the design doc, then assess the implementation against it.

This is a thorough design doc with a phased plan. Let me examine the actual implementation against it. I'll explore the key implementation files in parallel.

I'll dispatch parallel exploration agents to review each major area of the implementation against the design doc, then synthesize the gaps.

Reviews are in and cross-confirm each other on the key findings (the dead-knob gaps surfaced independently in two separate agents). Here's the synthesized gap report.

# Knowledge → Graphiti Pivot: Implementation Gaps

Reviewed the implementation against `knowledge-graphiti-pivot-design.md`. Listing **only gaps** (compliant areas omitted), grouped by priority. Severity reflects impact on the pivot's stated goals + the repo's strict rules (no-hardcoded-knobs, ledger observability).

---

## 🔴 Critical

### 1. Ledger token/cost sink is plumbed but never connected
The `on_usage` sink exists in the adapter (`graphiti_adapters.py:190`) and `from_preferences(on_usage=...)`, but **all three production call sites omit it** — `tools/knowledge_graph.py:190`, `eval_runner.py:435`, `agent/graph.py:488`. So `_report_usage` early-returns and **zero token rows are emitted** for any graph ingest or search.
- **Violates:** G7 ("preserves ledger"), §5.1, §12 ("token/cost captured in the LLM adapter → existing ledger rows").
- This is the single biggest deviation — the no-hardcoded-model-params memory rule pairs with "graph nodes must show tokens/errors," and right now they show nothing.

### 2. `edge_type_map` / `edge_types` defined and passed nowhere
`graphiti_ontology.py` defines only `GRAPHITI_ENTITY_TYPES`; the comment at `:14` admits edge-type pinning is deferred. `ingest_chunks` passes `entity_types` only — `edge_types`/`edge_type_map` left `None`.
- **Violates:** §5.4 + §3.3 N5, which name `edge_type_map` a "comes in" deliverable and explicitly warn: *"without it Graphiti free-forms `LIVES_IN`/`RESIDES_IN`/`STAYS_AT` synonyms."*
- Relation-synonym fragmentation degrades exactly the `multi_hop`/relational eval categories the pivot must win — so this also undermines the eval thesis.

### 3. Dead preference knobs — `search_recipe`, `k_hop` (no runtime effect)
Both render UI controls, are typed in `preferences.ts`, and persist to schema — but are **read nowhere** in the backend. `graphiti_search.py:70` calls `graphiti.search(q, group_ids, num_results)` with no recipe and no BFS depth; `graphiti_service.py:92-95` confirms RRF is fixed. `k_hop` is bound to nothing (retrieval uses `top_k`). Selecting MMR/cross-encoder or changing k-hop does nothing.
- **Violates:** G13/§9/§10 — *"no knob ships hardcoded."* (Cross-confirmed by two independent reviewers.) This directly contradicts the **admin-UI-prefs-for-settables** rule in memory.

---

## 🟠 High

### 4. Eval is 2-way (flat/graph), design mandates 3-way (flat/graphiti/**mix**)
`service.compare` runs `answer` twice on `use_graph` False/True only; `QuestionResult` has just `flat_*`/`graph_*` fields; `by_category` and the UI table are 2-way. The **`mix` leg is entirely absent**.
- **Violates:** G12, §1.2, §8.5, §8.6 (the sample table has three columns; the gate is defined on `Δ(best)` across all three).
- "graphiti" vs "mix" (fused graph-focused Qdrant) is the core thesis — the current eval **cannot produce the evidence the gate needs**.

### 5. Question bank is 29 questions; design floor is ≥50
`eval/adam_questions.yaml` has 29 `- id:` rows (the Phase 5 checkbox even mis-claims 32). All 17 categories are present, but most have 1–2 rows, so the per-category × mode table rests on single-sample cells where one LLM flake flips a verdict.
- **Violates:** §8.5 ("**≥50 questions**"). ~42% under floor — undermines the eval's statistical power.

### 6. `GraphitiIngestStats` carries no tokens and no facts-created/invalidated split
Tracks `episodes_*`, `entities_total`, `edges_total` only (`graphiti_ingest.py:70-91`), despite its own docstring claiming ledger surfacing. No retrieval ledger row is emitted either (`graphiti_search.py` only logs).
- **Violates:** §12 ("Ingest stats row: … facts created/invalidated, tokens"; "Retrieval ledger: facts returned … fusion outcome").

---

## 🟡 Medium

### 7. Per-query temporal override is dead plumbing
`state.graph_temporal` is *read* (`agent/graph.py:498`) but **never set** by any tool param, route, or `service.answer` thread. Only the admin-pref default is reachable.
- **Violates:** §7 ("admin pref **with a per-query override**"); Phase 3 claims `graph_temporal` works.

### 8. Temporal "current" uses a Python post-filter, not `SearchFilters`
`current` is enforced by dropping superseded edges *after* a relevance-ranked `num_results` set returns (`graphiti_search.py:84-87`) — superseded facts consume slots first, silently under-filling `chunk_ids`.
- **Violates:** §7 ("we set `SearchFilters` explicitly").

### 9. `communities_enabled` toggle is live in UI but wired to nothing
Renders as an active toggle (`KnowledgeSection.svelte:512`), consumed nowhere. Deferral is fine per G9, but it should read as inert/deferred rather than a functional switch.

### 10. Viz DTO field omissions (§5.6)
- `GraphNodeDTO.chunk_ids` / `document_ids` / `aliases` hardcoded empty (`graphiti_serialize.py:48-51`) — node-level provenance lost vs the written contract.
- `GraphEdgeDTO` omits `expired_at` even though supersession logic reads it — viz can't distinguish expired facts.

### 11. Token usage read from `usage_metadata`, not the LangChain callback
`graphiti_adapters.py:101` pulls tokens off `raw.usage_metadata`; returns `(0,0)` silently on providers/streams that don't populate it.
- **Violates:** §5.1 ("captured **via LangChain callback**").

---

## 🟢 Low

| # | Gap | Note |
|---|-----|------|
| 12 | **Add-tab build-graph stats stale** — `KnowledgeIngestPanel.svelte:448` reads Ladybug keys (`entities_created`, `entities_linked_*`); Graphiti emits `entities_total`/`edges_total`/`episodes_processed`. UI shows `0`s. | Phase 8 left this unchecked — confirmed; it's a live wrong-display, not just missing. |
| 13 | `expected_kind: world` never handled by scorer (only `abstain`). Worked around via fragments. | §8.5 enum divergence; no functional break. |
| 14 | `episode_metadata` / `document_title` not persisted. | The Graphiti `add_episode` param the design names **doesn't exist**; `document_id` survives via `source_description`, only title is lost. Design field unimplementable as written. |
| 15 | Bulk path (`add_episode_bulk`) not used — `knowledge_graph_ingest_batch` loops sequential `ingest_chunks`. | Acceptable per G12 (bulk doesn't cut LLM cost); optional. |
| 16 | Optional `knowledge_graph_search` Tool absent (§11). | Marked optional. |
| 17 | Export Tool docstrings stale ("empty graph until Phase 4") though code calls `read_graph_snapshot` correctly. | Cosmetic. |
| 18 | Bank path `adam_questions.yaml` vs design's `question_bank.yaml`; UI 50-cap unreachable at 29 Qs. | Traceability only. |

---

## TL;DR

- **Critical:** (1) **ledger sink never wired** — no token rows emitted anywhere (G7/§12); (2) **`edge_type_map` missing** — the exact relation-synonym fragmentation the design warned against is unguarded (§5.4); (3) **`search_recipe` + `k_hop` are dead knobs** — render in UI, read nowhere, violating the **no-hardcoded-knobs** rule (G13).
- **High:** eval is **2-way not 3-way** (no `mix` leg → gate can't produce `Δ(best)`); **bank is 29 Qs vs ≥50** floor; ingest/retrieval **stats lack tokens + facts-invalidated**.
- **Medium:** per-query temporal override is **dead plumbing**; temporal uses a **post-filter** not `SearchFilters`; `communities` toggle is live-but-inert; viz DTO drops node `chunk_ids`/`document_ids`/`aliases` + edge `expired_at`; tokens read from `usage_metadata` not the callback.
- **Most load-bearing fixes:** wire `on_usage` at the three call sites, define+pass `edge_type_map`, thread `search_recipe`/`k_hop` into `search_chunk_ids`, and add the `mix` eval leg.
- **Holding up well (not gaps):** uuid==point_id provenance + no mapping table, F7 write-gate in front of `add_episode`, sequential chronological ingest, soft-fallback fusion, the §4 `graphiti_core` boundary (no leaks), G7 model_size routing, G8 dual-method shared embedder, full 35-episode corpus with all 17 categories + supersession traps, and the fail-loud token assertion in the loader.

Want me to fix any of these? The three Critical items are concrete and low-risk — I'd suggest starting with the ledger wiring and the dead knobs.