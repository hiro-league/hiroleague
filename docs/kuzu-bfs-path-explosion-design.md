# Kuzu BFS Path Explosion — Design Doc

> **Tracker doc.** Fix for the buffer-pool OOM that aborted memory-eval runs at
> `k_hop=3`: graphiti-core's Kuzu BFS hop expansion enumerates **all paths** up to
> the hop bound, which is exponential through hub entities; we replace the two BFS
> leg functions with a **`SHORTEST`-semantics rewrite** (linear memory, provably
> identical result sets) inside our re-hosted fact-search pipeline.
>
> **Companions:** [`kuzu-shared-database-design.md`](kuzu-shared-database-design.md)
> (shared Database/write-lock concurrency model — a *different* Kuzu failure class),
> [`graph-group-policy-design.md`](graph-group-policy-design.md).
>
> **Mode:** initial development; no backward compatibility / no migration / no
> wrappers. (The fix is behavior-preserving — result sets are proven identical —
> so there is nothing to migrate.)
>
> **Status:** ✅ **implemented** (2026-06-11). New module
> [`graphiti_bfs.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_bfs.py)
> (`edge_bfs_search_shortest` / `node_bfs_search_shortest`);
> [`graphiti_fact_search.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_fact_search.py)
> imports them aliased over the vendored names (call sites and trace labels
> unchanged); compat probes extended in
> [`graphiti_compat.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_compat.py).
> Tests: [`test_graphiti_bfs.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/test_graphiti_bfs.py)
> (parity vs vendored on real in-memory Kuzu, depths 1–3, duplicate origins,
> group filtering, provider guard) — all green alongside the full graph suite.

## 1. Symptom

Memory-eval runs (`run_memory_eval`, LoCoMo corpus) aborted with:

```
RuntimeError: Buffer manager exception: Unable to allocate memory!
The buffer pool is full and no memory could be freed!
```

Lowering the **k-hop** preference from 3 to 2 made the same eval pass. The
brute-force cosine similarity scan (graphiti's unindexed Kuzu search) was the
initial suspect but is **not** the cause — see evidence below.

## 2. Root cause (captured + reproduced, not theorized)

### The failing query (from `server.log`, run `l3eval-f1b7c5bd…`)

graphiti's Kuzu driver logs the failing Cypher on error. The aborted question
("what are John's goals…") died inside graphiti-core's
`search_utils.edge_bfs_search` **Kuzu fallback**:

```cypher
UNWIND $bfs_origin_node_uuids AS origin_uuid
MATCH path = (origin:Entity {uuid: origin_uuid})-[:RELATES_TO*1..5]->(:RelatesToNode_)
UNWIND nodes(path) AS relNode
MATCH (n:Entity)-[:RELATES_TO]->(e:RelatesToNode_ {uuid: relNode.uuid})-[:RELATES_TO]->(m:Entity)
WHERE e.group_id IN $group_ids
RETURN DISTINCT … LIMIT $limit
```

with origins = the uuids of **John (out-degree 232)** and **Tim (194)** — the two
LoCoMo speakers — *each passed twice*. `*1..5` is `k_hop=3` after the depth
doubling (each semantic hop = 2 physical edges through the reified
`RelatesToNode_`; depth = `2·k−1`).

### Why it explodes

Three compounding properties of that query shape:

1. **All-paths enumeration.** Cypher variable-length `MATCH path = …` binds every
   distinct path, not every reachable node. Path counts grow ~`degree^depth`;
   through two ~200-degree hubs that's tens of millions of path rows on a
   315-entity graph.
2. **Path materialization.** Every path object is held and `UNWIND`ed into its
   nodes (length × path-count rows) inside the buffer pool.
3. **`RETURN DISTINCT` blocks `LIMIT`.** The distinct-hash must consume the whole
   stream before LIMIT can apply — no early exit. (A sibling BFS shape without
   path-binding/DISTINCT early-exits fine even at depth 6.)

### Controlled reproduction (copy of the real workspace graph, fixed 4 GB pool)

| Query (real shapes, real origins/group) | Result |
|---|---|
| Brute-force cosine scan (1536-dim, DISTINCT + sort) | ✅ 83 ms — total embeddings are only ~4.4 MB (747 facts); can never fill the pool |
| Logged BFS at `k_hop=2` (`*1..3`) | ✅ 0.3 s |
| Logged BFS at `k_hop=3` (`*1..5`) | 💥 **12.3 s → the exact buffer-manager error** |

One variable changed between pass and fail: the depth. The cosine-scan hypothesis
is conclusively dead; brute-force similarity remains a (linear) *latency* concern
only — tracked separately as the optional HNSW work.

## 3. The fix — `SHORTEST` semantics (reachable set, not path set)

The hop expansion's contract is *"facts/entities within k hops of the origins"* —
a **reachable set**. A node lies on *some* path of length ≤ d **iff** its
*shortest* path is ≤ d, so all-paths enumeration buys nothing but the blowup.
Kuzu's `* SHORTEST 1..d` recursive-relationship semantics compute exactly the
reachable set with a frontier BFS — each node visited once, linear memory — and
let the fact node be the **destination** directly (no path binding, no
`UNWIND nodes(path)`):

```cypher
UNWIND $bfs_origin_node_uuids AS origin_uuid
MATCH (origin:Entity {uuid: origin_uuid})-[:RELATES_TO* SHORTEST 1..{2k-1}]->(e:RelatesToNode_)
MATCH (n:Entity)-[:RELATES_TO]->(e)-[:RELATES_TO]->(m:Entity)
WHERE e.group_id IN $group_ids
RETURN DISTINCT … LIMIT $limit
```

Measured on the real eval graph, same origins/group as the crashed run:

| | depth 3 (`k_hop=2`) | depth 5 (`k_hop=3`) |
|---|---|---|
| Vendored all-paths shape | 2,337 ms · 482 facts | 💥 OOM (4 GB pool) |
| `SHORTEST` rewrite | **47 ms · 482 facts — identical set** | **82 ms · 482 facts** |

The depth-3 column is the equivalence proof on real data (set equality, not
count equality). ~50× faster even where the original survives.

### Kuzu syntax constraints (validated on kuzu 0.11.3)

- `SHORTEST` **requires lower bound 1**. The vendored node queries use
  `*2..{2k}`, but reified paths strictly alternate node types (Entity at even
  depths, `RelatesToNode_` at odd), so typing the destination makes
  `SHORTEST 1..d` equivalent to the vendored bounds.
- `SHORTEST` works **mid-pattern** after a fixed `-[:MENTIONS]->` hop (needed for
  the Episodic-origin sub-queries).
- Origins are **deduped** before UNWIND (order-preserving) — the crashed run
  passed each hub twice, multiplying the traversal for zero recall gain.

## 4. Where it lives (and why not in graphiti)

The exploding fallback is only reached from **our re-hosted pipeline**:
`graphiti_fact_search.py` calls `search_utils.edge_bfs_search` /
`node_bfs_search` directly (3 call sites). graphiti's own `search()` recipes used
elsewhere (e.g. `add_episode` dedup) carry no BFS methods, so swapping our call
sites covers every path to the bug:

- [`graphiti_bfs.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_bfs.py) —
  drop-in replacements (same signatures, same record parsers, same per-sub-query
  LIMIT behavior), Kuzu-only with a loud `ValueError` guard for other providers.
- [`graphiti_fact_search.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_fact_search.py)
  imports them **aliased to the vendored names** so call sites and retrieval-trace
  labels stay identical.
- **Rejected:** graphiti's `driver.search_interface` extension seam — five of its
  call sites (`edge/node_fulltext`, `edge/node_similarity`, `episode_fulltext`)
  do **not** catch `NotImplementedError`, so a partial interface would crash the
  non-BFS lanes. Vendored package stays untouched either way.
- Drift guard: `graphiti_compat._EXPECTED_SIGNATURES` extended with the six
  graphiti internals `graphiti_bfs` relies on (filter constructors, return-query
  builders, record parsers); the exact-version pin (0.29.1) already trips on any
  upgrade and forces re-validation.

## 5. Test plan (✅ checked in)

- **Parity (the core invariant):** vendored vs rewrite on a real in-memory Kuzu
  graph — chain + cycle-through-origin + episodic origin + duplicate origins —
  identical uuid sets for edges and nodes at depths 1–3.
- **Pinned frontier semantics:** depth d returns exactly the first d hop levels
  (`r1,rh` → `+r2,rm` → `+r3,rc`).
- **Group filtering:** other-partition group_ids return nothing (partition policy
  holds through the rewrite).
- **Guards:** empty/None origins, depth 0, non-Kuzu provider rejection.

## 6. Follow-ups / out of scope

- **`k_hop=3` is now safe to use** — but note the LoCoMo graph *saturates* at
  ~2 hops (depths 3 and 5 return the same 482 facts); deeper hops only pay off on
  longer-chain corpora.
- **Per-level frontier pruning** (top-N by relevance per hop level) if a future
  graph is dense enough that even the linear reachable set is large — would live
  in `graphiti_bfs.py` behind the same signatures.
- **HNSW vector index** for the similarity legs (latency, not memory) — separate
  de-risked design, optional.
- Vendored `search_utils` fallbacks for other providers (Neo4j/Neptune) — not our
  deployment; out of scope.

## 7. TL;DR

- **Root cause (captured in logs + reproduced):** graphiti-core's Kuzu BFS
  fallback enumerates all paths (`MATCH path = …*1..5` + `UNWIND nodes(path)` +
  `RETURN DISTINCT` blocking LIMIT) — ~`degree^depth` through the two ~200-degree
  LoCoMo hubs → buffer-pool OOM at `k_hop=3`. Not the brute-force cosine scan
  (83 ms, 4.4 MB of embeddings).
- **Fix:** rewrite the two BFS legs with Kuzu `* SHORTEST` semantics (reachable
  set, linear memory) + origin dedup, in **our** module `graphiti_bfs.py`,
  aliased over the vendored names in the re-hosted pipeline.
- **Proof:** identical result sets at depth 3 on the real eval graph (482/482)
  and in checked-in parity tests; 82 ms at depth 5 where the original OOM'd a
  4 GB pool; ~50× faster at depth 3.
- **`k_hop=3` is usable again**; per-level pruning and HNSW remain optional
  follow-ups.
