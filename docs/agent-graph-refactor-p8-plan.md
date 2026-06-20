# P8 — First-Class Retrieval Legs: Resolve the Leg Once, Name It

> **Execution plan (single source) for Stage P8** of
> [`agent-graph-refactor-design.md`](agent-graph-refactor-design.md) — the final stage. Replaces
> the `graph_mode == "graphiti"` checks **smeared across the knowledge retrieval nodes** with a
> single **resolved, named leg** that every node reads.
>
> **Preconditions:** **P1–P3 landed and green** (knowledge decoupled in P1, node bodies
> declarative in P3). **P6 recommended first** so the new `effective_leg` field lands inside the
> already-sectioned `KnowledgeAgentState` (the leg section P6 created — P6 explicitly deferred
> leg routing to "P8"). Independent of P4/P7 (chat-side); **P5 is NOT** — see the note below. The
> §5.2 knowledge characterization net + retrieval-ledger tests are the safety rail.
>
> **Post-P5 reconciliation (read first — P5 Part B.3 landed and restructured `graph_expand`):**
> P5 replaced `graph_expand`'s inline service build with `async with graphiti_session(...)`. This
> **does not change P8's leg logic** (the `graph_mode`/`chunk_ids` decisions are untouched), but
> it changes the **return-point map** §4 must stamp. `graph_expand` now has **5 flat-fallback
> returns**, not 3 — stamp `{"effective_leg": RetrievalLeg.FLAT.value}` on **all** of them:
> (1) `graph_mode != "graphiti"`, (2) no query, (3) no graph DB (`db_path` missing) — the three
> *before* the `async with`; plus (4) **`session is None`** (backend off / no model — P5 split
> this into a distinct return *inside* the `async with`) and (5) the **`except graph_expand_failed`**
> fallback. The single GRAPHITI/effective return stays *after* the `async with` block. (Functionally
> an absent `effective_leg` already routes flat — `_route_after_expand`/`_chunk_dates` read
> `!= GRAPHITI.value` — but stamp it explicitly so "resolve the leg once" actually holds and a
> reader isn't left guessing on the fallback paths.) The other two smear sites (`_route_after_expand`,
> `_chunk_dates`) are **unchanged** by P5 and match §2's table verbatim.
>
> **Mode:** initial development — **no backward compatibility / no wrappers**. No behavior change
> — the leg a query takes today is the leg it takes after.
>
> **Status:** _Ready to build._ Resolves the design doc's open "knowledge legs" item (§1.1).

Reference symbols/node names, not line numbers — re-grep before editing.

---

## 1. The decision (§1.1): resolve a named leg, don't split into subgraphs

The design doc phrased P8 as "flat vs graphiti as **named sub-pipelines / stage spec**." Two
shapes were possible; I'm taking the lower-risk one and recording why.

| Option | Verdict |
|---|---|
| **Full subgraph extraction** — compile a `flat_leg` and a `graphiti_leg` StateGraph, parent routes to one | ❌ **Rejected.** The two legs **converge on a shared, leg-aware `build_context`**, the graphiti leg **soft-falls-back to flat** mid-flight (when it finds no chunk_ids), and the retrieval nodes are reused by **two** compiled builds (`build()` + `build_retrieval()`). Subgraphs multiply that surface for marginal gain. |
| **Resolve a named leg value once, consume it everywhere** | ✅ **Chosen.** Keep the linear graph; introduce a `RetrievalLeg` resolved **once** (intended from `graph_mode`, effective after `graph_expand`), stored in state. Every downstream check reads the resolved leg instead of re-deriving `graph_mode == "graphiti" and chunk_ids`. A small `legs.py` gives the leg — and the soft-fallback — a name and a home. |

This de-smears the branching (its real purpose) without restructuring the graph topology.

---

## 2. Where the smear is today

`graph_mode` (and its implicit chunk_ids fallback) is re-derived independently in several places:

| Site | Today |
|---|---|
| `graph_expand` | `if (state.get("graph_mode") or "off") != "graphiti": skip` |
| `_route_after_expand` | `if graph_mode == "graphiti" and graph_chunk_ids: "graph_only" else "vector"` |
| `_chunk_dates` | `if (state.get("graph_mode") or "off") != "graphiti" or not hits: return {}` |
| `build_context` | leg-specific facts block + `_chunk_dates` call + `score_source` |
| `graph_fetch` / `build_filters` | leg-only by position, explained only in comments |

The soft-fallback (graphiti finds nothing → behave as flat) lives **implicitly** inside
`_route_after_expand`'s compound condition — nowhere named.

```mermaid
flowchart TB
    RW["rewrite_query"] -->|intended_leg| GE["graph_expand<br/>(resolves EFFECTIVE leg)"]
    RW -->|skip small-talk| BC
    GE -->|effective=GRAPHITI<br/>(chunk_ids found)| GF["graph_fetch (by-id)"]
    GE -->|effective=FLAT<br/>(off OR soft-fallback)| BF["build_filters → embed → search → rerank"]
    GF --> BC["build_context<br/>(reads effective_leg)"]
    BF --> BC
    BC --> AFTER["call_model / finalize"]
    note["leg is RESOLVED once in graph_expand,<br/>READ everywhere else"]
```

---

## 3. The design — `legs.py` + one resolved field

New `services/knowledge/agent/legs.py`:
```python
"""Retrieval legs — the single source of truth for flat vs graphiti.

The leg is resolved in two steps: the *intended* leg (from the per-query graph_mode) gates
whether the graph is even consulted; the *effective* leg (after graph_expand) encodes the
soft-fallback (graphiti that found no supporting chunks behaves as flat). Downstream nodes read
the effective leg instead of re-deriving graph_mode + chunk_ids.
"""
from __future__ import annotations
from enum import Enum


class RetrievalLeg(str, Enum):   # str-Enum → JSON-safe in KnowledgeAgentState
    FLAT = "flat"
    GRAPHITI = "graphiti"


def intended_leg(graph_mode: str | None) -> RetrievalLeg:
    return RetrievalLeg.GRAPHITI if (graph_mode or "off") == "graphiti" else RetrievalLeg.FLAT


def effective_leg(intended: RetrievalLeg, *, chunk_ids: list) -> RetrievalLeg:
    """Soft-fallback made explicit: graphiti with no supporting chunks → flat."""
    if intended is RetrievalLeg.GRAPHITI and chunk_ids:
        return RetrievalLeg.GRAPHITI
    return RetrievalLeg.FLAT


def graphiti_facts_block(facts: list[str]) -> str:
    """The graph-leg answer skeleton prefix (moved verbatim out of build_context)."""
    kept = [f for f in (facts or []) if (f or "").strip()]
    if not kept:
        return ""
    return "Known facts from the knowledge graph:\n" + "\n".join(f"- {f}" for f in kept)
```

State (in the P6 leg section of `KnowledgeAgentState`):
```python
    # Set by graph_expand: the resolved leg after the soft-fallback. Downstream nodes read THIS,
    # not graph_mode + chunk_ids. Values: RetrievalLeg.value ("flat" | "graphiti").
    effective_leg: str
```

---

## 4. File-by-file checklist (`services/knowledge/agent/graph.py`)

- [ ] `graph_expand`: early in the node, `intended = intended_leg(state.get("graph_mode"))`.
      Return `{"effective_leg": RetrievalLeg.FLAT.value}` (with the existing skip `observe(...)`)
      on **all 5 flat-fallback returns** (see the post-P5 note): `graph_mode != graphiti`, no
      query, no graph DB, **`session is None`** (inside the `async with graphiti_session(...)`),
      and the **`except graph_expand_failed`**. After the Graphiti search (after the `async with`),
      return `{"graph_chunk_ids": …, "graph_facts": …, "effective_leg": effective_leg(intended, chunk_ids=expansion.chunk_ids).value}`.
      (Keep the sanctioned P3 ledger flush + `graphiti_session` CM untouched.)
- [ ] `_route_after_expand`: `return "graph_only" if state.get("effective_leg") == RetrievalLeg.GRAPHITI.value else "vector"`.
- [ ] `_chunk_dates`: `if state.get("effective_leg") != RetrievalLeg.GRAPHITI.value or not hits: return {}`.
- [ ] `build_context`: replace the inline facts-prefix with `graphiti_facts_block(state.get("graph_facts"))`;
      leave the `score_source` / `_minmax_relevances` logic unchanged.
- [ ] Add the comment headers in the builder (`_add_retrieval_nodes`) naming the two paths:
      `# --- graphiti leg: graph_expand → graph_fetch → build_context ---` and
      `# --- flat / vector leg: build_filters → embed_query → vector_search → rerank → build_context ---`.
- [ ] Import `RetrievalLeg`, `intended_leg`, `effective_leg`, `graphiti_facts_block` from `.legs`.
- [ ] **Do not** change `graph_mode` (still the per-query input) — only stop *re-deriving the
      leg* from it past `graph_expand`.

---

## 5. Tests this stage adds

`services/knowledge/test_retrieval_legs.py` (**parent dir**, per the placement rule):
- [ ] `intended_leg`: `"graphiti"` → GRAPHITI; `"off"`/`None`/anything else → FLAT.
- [ ] `effective_leg`: GRAPHITI + chunk_ids → GRAPHITI; GRAPHITI + `[]` → **FLAT** (soft-fallback);
      FLAT + anything → FLAT.
- [ ] `graphiti_facts_block`: empty/whitespace facts → `""`; facts → the `- ` bulleted skeleton.
- [ ] Routing: `_route_after_expand` reads `effective_leg` (GRAPHITI→`graph_only`, FLAT→`vector`).

Extend the knowledge characterization (using `FakeKnowledgeService`, whose
`fetch_hits_by_point_ids` returns `[]`):
- [ ] **Flat leg** (`graph_mode` absent/off) → `effective_leg == "flat"`, vector path, same rows.
- [ ] **Graphiti soft-fallback** (`graph_mode="graphiti"` but expansion yields no chunk_ids) →
      `effective_leg == "flat"`, routes to `vector` — proving the fallback is preserved.

---

## 6. Self-validation gates

**Gate A — the leg is resolved once, read everywhere (no re-derivation):**
```bash
# graph_mode compared only where the leg is RESOLVED (graph_expand) — not re-derived downstream:
grep -n 'graph_mode.*==.*graphiti\|"graphiti"' hiroserver/hirocli/src/hirocli/services/knowledge/agent/graph.py
# expect: only inside graph_expand (intended_leg call); _route_after_expand / _chunk_dates read effective_leg
grep -n "effective_leg" hiroserver/hirocli/src/hirocli/services/knowledge/agent/graph.py
# expect: set in graph_expand; read in _route_after_expand + _chunk_dates
```

**Gate B — facts block extracted:**
```bash
grep -n "Known facts from the knowledge graph" hiroserver/hirocli/src/hirocli/services/knowledge
# expect: only in legs.py (graphiti_facts_block), not inline in build_context
```

**Gate C — import health / no cycle:**
```bash
python -c "import hirocli.services.knowledge.agent.legs, hirocli.services.knowledge.agent.graph"
```

**Gate D — ⭐ knowledge characterization + retrieval-ledger unchanged:**
```bash
pytest hiroserver/hirocli/src/hirocli/services/knowledge -k "characterization or ledger or retrieval_legs or compare_and_graph_mode or fact_search"
git diff -- "**/test_*characterization*.py"   # expect: NO assertion edits
```

**Gate E — full knowledge suite + lint:** `pytest hiroserver/hirocli/src/hirocli/services/knowledge` + `ruff check`.

---

## 7. Definition of done

- [ ] `legs.py` exists: `RetrievalLeg`, `intended_leg`, `effective_leg`, `graphiti_facts_block`.
- [ ] `effective_leg` is set once in `graph_expand` and read by `_route_after_expand` +
      `_chunk_dates`; `build_context` uses `graphiti_facts_block` (Gates A/B).
- [ ] The soft-fallback (graphiti → flat on no chunk_ids) is **named** in `effective_leg`, not
      implicit in a routing condition.
- [ ] `graph_mode` is unchanged as the per-query input; not re-derived past `graph_expand`.
- [ ] `test_retrieval_legs.py` added; characterization (incl. soft-fallback) unchanged (Gate D).
- [ ] No behavior change — same leg per query, same rows.

---

## 8. Gotchas & cues

- **`graph_mode` stays the input; `effective_leg` is the resolved output.** Don't delete
  `graph_mode` (callers/eval set it) — just stop re-deriving the leg from it after `graph_expand`.
- **The soft-fallback is the whole point of `effective_leg`** — graphiti with no chunk_ids must
  resolve to FLAT and route to `vector`, exactly as today. The characterization soft-fallback
  test guards it.
- **Don't extract subgraphs** (§1.1) — shared `build_context`, the soft-fallback, and the two
  build variants make that high-risk for no behavior gain.
- **`RetrievalLeg` is a `str`-Enum** so `effective_leg` stays JSON-safe in `KnowledgeAgentState`;
  store/compare `.value` (`"flat"`/`"graphiti"`).
- **Move `graphiti_facts_block` verbatim** — the answer skeleton text feeds the model; a wording
  change would shift answers (and fail characterization).
- **Land the state field in P6's leg section** — if P6 hasn't run, add `effective_leg` with a
  section comment matching P6's style.
- **Reflecting-build-updates:** internal refactor — no server restart / workspace reset / config
  change. Note it in the PR summary.

---

## 9. TL;DR

- **Decision:** resolve a **named `RetrievalLeg`** once (in `graph_expand`) and read it
  everywhere, instead of re-deriving `graph_mode == "graphiti" and chunk_ids` across 4–5 nodes.
  **Reject** full subgraph extraction (shared `build_context` + soft-fallback + two build
  variants make it high-risk for no gain).
- **Do:** add `services/knowledge/agent/legs.py` (`RetrievalLeg`, `intended_leg`,
  `effective_leg`, `graphiti_facts_block`); store `effective_leg` in `KnowledgeAgentState`; have
  `_route_after_expand` / `_chunk_dates` / `build_context` read it; name the soft-fallback.
- **Prove it:** Gate A (leg resolved once), Gate B (facts block extracted), Gate C (no cycle),
  **Gate D (knowledge characterization incl. soft-fallback unchanged)**, Gate E (suite + lint);
  plus `test_retrieval_legs.py`.
- **No behavior change** — same leg per query, same rows. This completes the P1–P8 plan set.
