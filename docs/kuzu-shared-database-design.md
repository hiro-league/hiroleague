# Kuzu Shared-Database — Design Doc

> **Tracker doc.** Fix for the in-process Kuzu file-lock conflict, generalized to a
> safe concurrency model for the embedded Graphiti/Kuzu graph: the eval/ingest build
> and the Graph tab each open a **separate `kuzu.Database`** on the same file, in the
> **same server process**, so opening the Graph page mid-build throws *"IO exception:
> Could not set lock on file … graphiti_kuzu.db"*. The same model must also hold once
> **concurrent chats** write memory episodes to the one graph.
>
> **Source diagnosis:** [`kuzu_issue.md`](kuzu_issue.md). **Kuzu rule (grounded, §3):**
> one `Database` per file, many `Connection`s; **serializable, single-writer** — a
> second concurrent write *errors* (it does not block/queue).
>
> **Companions:** [`knowledge-graphiti-pivot-design.md`](knowledge-graphiti-pivot-design.md),
> [`knowledge-graph-viz-design.md`](knowledge-graph-viz-design.md).
>
> **Mode:** initial development; **no backward compatibility / no migration / no
> wrappers** — we refactor the open sites directly and delete `_release_kuzu`.
>
> **Decision:** one **refcounted lazy-singleton `Database` per workspace** that **owns a
> per-workspace write lock** (serializes all writers) + **lock-free reads**, with a
> thin **fail-fast** fallback for an external-process lock (A + B). Reader connection:
> **option (b)** — snapshot reads on a **dedicated `AsyncConnection`** over the shared
> `Database` (§4.4, §8), so a Graph-tab load mid-build never queues behind the writer's
> pool=1 connection.
> **Status:** ✅ **implemented** (2026-06-04). New module
> [`kuzu_registry.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/kuzu_registry.py)
> (refcounted shared driver + per-workspace write lock); `graphiti_service.py` opens/closes
> via the registry and passes the write lock; `graphiti_ingest.py` wraps each `add_episode`
> in the lock; `_release_kuzu` deleted (folded into the registry closer); Option-B "DB busy"
> guard in the `graph_export` route. Tests: `test_kuzu_registry.py` (refcount, FIFO
> fairness, factory-failure) + regression in `test_graphiti_service.py` (snapshot while a
> service holds the graph open). Concurrency assumptions **empirically validated** (§3).

## 1. Goal (one sentence)

One shared `kuzu.Database` per workspace, used by every in-process consumer (eval,
graph ingest, retrieval, viz, and later concurrent-chat memory writes), with **writes
serialized to one-at-a-time** and **reads lock-free and concurrent** — so the Graph tab
renders during a build and concurrent chats never corrupt or crash the graph.

## 2. Root cause (verified against current code)

Both consumers construct their **own** `KuzuDriver(path)`, and each `KuzuDriver`
internally news up a `kuzu.Database(path)` (verified: graphiti-core **0.29.1**,
`KuzuDriver.__init__(db: str = ':memory:', max_concurrent_queries: int = 1)` — takes
only a path, always builds its own `kuzu.Database`, exposes `.db` / `.client`, `close()`
is a no-op). Kuzu allows only **one `Database` object per file** → second open fails.

### Every consumer is transient today — nothing holds the graph open

| Consumer | Open site | Lifetime |
|----------|-----------|----------|
| Eval ingest (writer) | [eval_runner.py:485](../hiroserver/hirocli/src/hirocli/services/knowledge/eval_runner.py:485) → close :522 | per run |
| Graph ingest (writer) | [tools/knowledge_graph.py:192](../hiroserver/hirocli/src/hirocli/tools/knowledge_graph.py:192) → close :254 | per batch |
| Retrieval / `graph_expand` (reader) | [agent/graph.py:523](../hiroserver/hirocli/src/hirocli/services/knowledge/agent/graph.py:523) → close :557 | **per query** |
| Graph tab snapshot (reader) | [graphiti_service.py:453](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:453) → release :484 | per request |

All funnel through **one open + one release pair** inside `graphiti_service.py`:
- Open: `GraphitiMemoryService.__init__` → `KuzuDriver(str(self._db_path))` ([:184](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:184)); snapshot → `KuzuDriver(str(path))` ([:453](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:453)).
- Release: `_release_kuzu` in `close()` ([:312](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:312)) and snapshot finally ([:484](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:484)).

**`_release_kuzu` is itself the anti-singleton workaround** — its docstring ([:101](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:101)) says it drops the file lock *between operations* so the **next** open can succeed. The bug is exactly the window where two opens overlap and that dance can't help. A shared `Database` deletes the workaround and the bug class together.

## 3. Kuzu + graphiti concurrency — grounded findings

Measured against the **installed** stack (kuzu **0.11.3**, graphiti-core **0.29.1**),
not just docs. Test: open one `Database`, drive concurrent writes/reads from multiple
`Connection`s.

| Scenario | Measured result | Source |
|---|---|---|
| Many `Connection`s from one `Database` | Safe — `AsyncConnection` builds a **pool of N `Connection(db)`** (default 4), routes each query to the least-busy one | [kuzu/async_connection.py](../hiroserver/.venv/Lib/site-packages/kuzu/async_connection.py); [docs/concurrency](https://kuzudb.github.io/docs/concurrency/) |
| 8 threads × 50 concurrent auto-commit **writes** | **44 ok, 356 errored** — `RuntimeError: Cannot start a new write transaction in the system. Only one write transaction at a time is allowed` | live test, kuzu 0.11.3 |
| Open write txn + **second write** (other conn) | **Errors immediately** (same RuntimeError) — does **not** block, queue, or wait | live test |
| Open write txn + **concurrent read** (other conn) | **Read SUCCEEDS** — returns last-committed snapshot while the writer's txn is open | live test |
| Isolation / writers | **Serializable; single-writer** — "only one write transaction at a time" | [docs/cypher/transaction](https://kuzudb.github.io/docs/cypher/transaction/) |

**graphiti's own rule agrees** ([graphiti.py:1057](../hiroserver/.venv/Lib/site-packages/graphiti_core/graphiti.py:1057)):
> *"It's important that each episode is added sequentially and awaited before adding the next one… use FastAPI background tasks or a dedicated task queue."*

**Why a lone ingest works today:** graphiti's `KuzuDriver` defaults
`max_concurrent_queries=1`, so its `AsyncConnection` pool is **one** connection — every
query (even `semaphore_gather`'d ones) self-serializes through it. **Corollary:** the
**writer driver must stay at pool=1** — bumping it would let graphiti's internal writes
land on different pool connections and **self-collide** with the single-writer rule.

### Three consequences that drive the design

1. **Reads are always safe** — concurrent with each other and with an active writer
   (serializable snapshot). Retrieval (many chats) + viz-during-build → **no lock**.
2. **Concurrent writers hard-fail** — two `add_episode`s on one graph (two chats, or a
   chat write + eval ingest), **even in-process**, throw `Cannot start a new write
   transaction`. → writers **must** be serialized to one-at-a-time per workspace.
3. **A shared `Database` does not, by itself, make writes safe** — it makes them
   *coordinatable*. The actual safety mechanism is an **app-level write serializer**.

## 4. Chosen design — refcounted lazy-singleton that owns a write lock

### 4.1 The shared object — one per workspace, refcounted

A new module **`services/knowledge/graph/kuzu_registry.py`** holds process-wide state:
one live `kuzu.Database` **plus one `asyncio.Lock`** per resolved `db_path`,
reference-counted. The registry is a **generic refcounted resource pool** — it imports
no `graphiti`/`kuzu` internals; the caller supplies the open/close callables, so all
graphiti/kuzu knowledge stays inside `graphiti_service.py` (the G3/G8 boundary).

```python
# kuzu_registry.py  (shapes, not final)
@dataclass
class _Entry:
    resource: Any            # the live KuzuDriver bound to the one shared kuzu.Database
    write_lock: "asyncio.Lock"   # serializes ALL writers on this db_path  ← the singleton owns this
    refcount: int

_REGISTRY: dict[str, _Entry] = {}
_GUARD = threading.Lock()    # guards the dict + refcounts (short critical section)

def acquire(key: str, factory: Callable[[], Any]) -> _Entry: ...   # first caller opens; rest reuse
def release(key: str, closer: Callable[[Any], None]) -> None: ...  # last caller closes → frees the file lock
def write_lock(key: str) -> "asyncio.Lock": ...                    # the per-workspace writer gate
```

- **First** `acquire` on a `db_path` calls `factory()` (graphiti opens the real file +
  `setup_schema`); later acquirers reuse the **same** `KuzuDriver` object, `refcount++`.
- **`release`** decrements; on `refcount == 0` it calls `closer()` (today's
  `_release_kuzu` logic), freeing the file lock — so when nothing is using the graph the
  lock is free (file deletable, external tools can open). This is a **lazy singleton**.
- Uses only graphiti's **public** `KuzuDriver(path, max_concurrent_queries=1)` ctor — no
  `.db`/`.client` swap, no `import kuzu`. (Earlier draft's swap hack is **rejected**, §8.)

### 4.2 Write serialization — the singleton owns the lock (the core of the fix)

The singleton holds **one `asyncio.Lock` per workspace**. Every writer — eval ingest,
graph ingest, and (later) concurrent-chat memory — acquires that **same** lock before
writing, so writes are serialized to one-at-a-time. Two distinct rules require this:

- **Kuzu (mechanical):** only one write transaction at a time, else a second concurrent
  write **errors** (§3).
- **graphiti (semantic — the binding one):** each episode must be processed
  *sequentially and awaited* before the next, because its dedup/resolution step **reads
  the current graph** to merge entities ([graphiti.py:1057](../hiroserver/.venv/Lib/site-packages/graphiti_core/graphiti.py:1057)).
  Concurrent episodes would dedup against a stale snapshot → duplicate entities.

**Two granularity decisions, on different axes:**

1. **Within an episode → lock the WHOLE `add_episode`** (extraction → dedup → write),
   not just the millisecond Kuzu write. graphiti's dedup reads prior state, so the read
   work must be serialized too. *If it were only Kuzu's rule, a write-only lock would
   suffice — graphiti is what forces the wider scope.*
2. **Across episodes → RELEASE between episodes**, not held for the whole batch. The lock
   wraps **each iteration** of the ingest loop, around the per-episode write unit
   (`_preseed_episode_node` + `add_episode`, [graphiti_ingest.py:312-333](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_ingest.py:312)):

```python
# graphiti_ingest.py — INSIDE the per-episode loop (NOT around the whole batch)
async with write_lock:                       # one episode's worth, then released
    await _preseed_episode_node(driver, ...)
    result = await graphiti.add_episode(...)
```

**Fairness is free.** `asyncio.Lock` wakes waiters **FIFO**. A writer (eval) only
re-requests the lock *after* releasing each episode, so a chat that began waiting
mid-episode is already ahead in line and runs **before** the eval's next episode — no
starvation. Worst-case wait for a chat = **one in-flight episode (~8.5s measured)**, not
the ~5-min batch. Because the lock lives on the **singleton** (not a transient service),
two chats that each build their own `GraphitiMemoryService` over the same workspace still
contend on the **same** lock.

```
 within  →  hold the pen for the WHOLE episode (extract+dedup+write)   [graphiti reason]
 across  →  PUT THE PEN DOWN between episodes                          [fairness/pile-up]

 Eval:  [🖊 ep1 ][🖊 ep2 ]...        ← releases between episodes
             ↓ free
 Chat:    ⏳waiting→ grabs pen → [🖊 1 memory]   ← cuts in (FIFO), waits ≤ ~8.5s
```

### 4.3 Reads are lock-free

`search_chunk_ids` (retrieval) and `read_graph_snapshot` (viz) **do not** take the write
lock. They read concurrently with each other and with the active writer (§3 proved this
returns last-committed data). This is what lets the Graph tab render during a build and
many chats retrieve at once.

### 4.4 Writer driver stays `max_concurrent_queries=1`; readers get their own connection

The factory opens the shared **writer** driver at **pool=1** (graphiti's default and its
self-serialization guarantee) — never bumped, else graphiti's internal `semaphore_gather`
writes land on different pool connections and self-collide with Kuzu's single-writer rule
(§3).

**Resolved (was the §8 open item): readers get a dedicated connection — option (b).**
`read_graph_snapshot` shallow-copies the shared driver and swaps in its **own**
`kuzu.AsyncConnection(shared_db, max_concurrent_queries=4)`, so snapshot reads run on a
separate connection from the writer's pinned one — no head-of-line blocking when the Graph
tab loads mid-build. This is the textbook **1 writer + N readers** shape, and it's safe
because a read **never opens a write transaction** (concurrent reads are fine; only the
*writer* pool must stay at 1). The shared `Database` is untouched — still one `Database`
per file; we only add a second `Connection` on it. graphiti's Kuzu `get_by_group_ids`
hits only `driver.execute_query` (→ the swapped client) + `driver.provider`, so a shallow
copy suffices and the ORM is kept (no hand-maintained Cypher). The dedicated connection is
closed in the read's `finally`, before the refcount is dropped, so it never outlives the
shared `Database`. ([graphiti_service.py](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py) `read_graph_snapshot`).

### 4.5 Option B — thin fail-fast fallback

In-process opens can no longer collide, so B shrinks to a guard for an **external OS
process** holding the file lock (a second `hiro`, a stale handle): the Graph export route
catches the Kuzu lock IO error (message contains `Could not set lock on file`) and returns
`envelope_failure("Graph database is busy — try again shortly.")` instead of a raw stack.
Detection lives in the registry as `is_kuzu_lock_error(exc)` (one home for the match).

### 4.6 Call-site changes (the only edits to existing code)

- [graphiti_service.py:184](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:184) & [:453](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:453): `KuzuDriver(...)` → `kuzu_registry.acquire(key, lambda: KuzuDriver(str(path), max_concurrent_queries=1))`
- [graphiti_service.py:312](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:312) & [:484](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:484): `_release_kuzu(driver)` → `kuzu_registry.release(key, _release_logic)`
- `_release_kuzu` (101) is **deleted** — its body moves into the registry's `release` closer (no wrapper kept).
- Write paths (`ingest_chunks` and the eval/graph-ingest callers) wrap their graph
  mutation in `async with kuzu_registry.write_lock(key)`.
- `driver._database = group_id` seed ([:220](../hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:220)) unchanged (see §8 hazard note).

```
                         ONE shared kuzu.Database per workspace (registry, refcounted)
   ┌───────────── WRITE (serialized by the singleton's write_lock) ─────────────┐
   │  eval ingest ┐                                                             │
   │  graph ingest├─► async with write_lock(key):  add_episode  (driver pool=1) │  exactly ONE
   │  chat memory ┘                                                             │  writer at a time
   └────────────────────────────────────────────────────────────────────────────┘
   ┌───────────── READ (no lock) ───────────────────────────────────────────────┐
   │  retrieval (many chats) + Graph-tab snapshot  ── concurrent, incl. mid-build │  ✅ last-committed
   └────────────────────────────────────────────────────────────────────────────┘
```

## 5. Concurrency truth table (grounded, §3)

| | reader | writer |
|---|---|---|
| **reader** | ✅ concurrent | ✅ reader sees last-committed snapshot |
| **writer** | ✅ (reader unaffected) | ⛔ second writer errors → **serialized by `write_lock`** |

## 6. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Concurrent writers crash the graph | Per-workspace `write_lock` on the singleton serializes **all** writers; **validated** that without it Kuzu errors (§3) |
| Bumping reader concurrency self-collides graphiti's internal writes | Writer driver pinned to `max_concurrent_queries=1`; readers use a **separate** `AsyncConnection` (§4.4) — read-only, so its pool size can't trip the single-writer rule |
| Refcount leak (acquire without release on an exception path) | every acquire paired in `close()`/`finally`; unit test asserts registry empties to `{}` |
| `write_lock` held forever if a writer hangs | writer is `await`ed inside `async with`; a crash releases the lock; episodes are bounded units |
| `_database` shared-seed on a shared driver | safe today (one group/workspace); flagged as a hazard if multi-group lands (§8) |
| Registry dict races | `threading.Lock` around dict + refcount mutation |

## 7. Test plan

- **Unit (registry):** acquire twice on one key → same resource, refcount 2; release
  twice → registry empties, lock freed; reacquire reopens. `write_lock(key)` returns the
  same lock object across acquirers.
- **Unit (lock-error predicate):** `is_kuzu_lock_error` matches the real message, rejects
  unrelated errors.
- **Integration (the reported bug):** hold a writer `GraphitiMemoryService` open, then
  `read_graph_snapshot` the same path → returns nodes, **no lock exception**. Regression
  test for `kuzu_issue.md`.
- **Integration (concurrent writers):** two `ingest_chunks` tasks on one workspace →
  with `write_lock` both **succeed serially**; assert that bypassing the lock reproduces
  the `Cannot start a new write transaction` error (guards against the lock being dropped).
- **Concurrency probes (already green, §3):** read-during-write succeeds; 8×concurrent
  unguarded writes error — keep as a checked-in invariant test.

## 8. Open items / follow-ups

- **Reader connection — ✅ RESOLVED (2026-06-04): chose (b).** Shipped (a) initially
  (readers share the pooled driver), but under real ingest the snapshot read queued behind
  the writer's pool=1 connection and the Graph-tab export hung past its 60s client timeout
  → "signal is aborted" / blank graph. Escalated to **(b)**: `read_graph_snapshot` opens
  its **own** `AsyncConnection` on the shared `Database` (shallow-copied read driver,
  writer driver untouched) — see §4.4. The originally-considered `.db`/`.client` swap *on
  the shared driver* stays rejected (§8 last bullet); this is a swap on a per-read **copy**,
  localized to `graphiti_service.py`, so the G3/G8 boundary holds.
- **Promote to a held (non-lazy) singleton:** keep the `Database` open for the whole
  workspace session instead of refcount-closing when idle. Cleaner end-state, but needs
  teardown hooks on **workspace switch / graph reset / server stop** (else the lock leaks
  and "delete workspace" breaks). Deferred; refcount flavor avoids this now.
- **Persistent / durable write queue** (escalation from the in-memory `asyncio.Lock`):
  v1's lock is correct but its waiting line lives only in memory (lost on restart), has no
  depth/backpressure visibility, and is strictly FIFO (no priority). Escalate to a durable
  queue when any holds: **durability** (chat-memory survives a restart), **sustained write
  rate > drain rate**, **priority** (live chat ≻ long eval batch), or **off-request-path**
  submit-and-return with retry. graphiti recommends this (Celery/task-queue). All writers
  already go through the singleton's write-lock seam, so lock→queue is a localized swap.
  Deferred to the memory phase, when concurrent-chat writes actually arrive.
- **`driver._database` multi-group hazard:** a shared driver carrying one group's seed is
  unsafe if per-group databases arrive; revisit then.
- **Rejected:** the earlier `:memory:`-throwaway + `.db`/`.client` swap (imported `kuzu`,
  reassigned graphiti internals, widened the rip-out-able surface) — replaced by the
  public-ctor + generic-registry approach above.

## 9. Out of scope

- Cross-**process** sharing (two `hiro` servers on one workspace) — B's clean error, not a
  shared Database.
- Graph build/extraction semantics, ontology, viz frontend.

## 10. TL;DR

- **Root cause (verified):** two `kuzu.Database` objects on one file in one process; Kuzu
  allows one. `_release_kuzu`-between-ops is the anti-singleton workaround; the bug is its
  failure window.
- **Concurrency, grounded on kuzu 0.11.3 (measured, not assumed):** **serializable,
  single-writer** — a second concurrent write **errors** (`Cannot start a new write
  transaction`), does not block. **Reads run safely during a write.** graphiti mandates
  sequential adds too.
- **Fix:** one **refcounted lazy-singleton `kuzu.Database` per workspace** that **owns a
  per-workspace `asyncio.Lock`**. **All writers** (eval, graph ingest, chat memory)
  serialize through that lock — **the singleton serializes the writes**. **Reads are
  lock-free** and concurrent, including mid-build.
- **Keep the writer driver at `max_concurrent_queries=1`** (bumping self-collides
  graphiti's internal writes). Registry stays a **generic** pool — zero graphiti/kuzu
  internals leaked; boundary intact.
- **Readers use a dedicated connection (option b, shipped):** the Graph-tab snapshot reads
  on its own `AsyncConnection` over the shared `Database`, so a load mid-build doesn't queue
  behind the writer's pool=1 connection (fixes the hung/aborted export). Safe — reads never
  open a write txn.
- **Option B** shrinks to a thin "DB busy" guard for an external-process lock.
- **Validated:** read-during-write works; unguarded concurrent writes error — both kept as
  invariant tests.
- **Open items:** reader-connection choice (default: share the pool); promote-to-held
  singleton later (needs teardown hooks). **Next:** "lets implement".
