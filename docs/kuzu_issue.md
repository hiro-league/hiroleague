## Issue

IO exception: Could not set lock on file : C:\Users\augr\AppData\Local\hiro\workspaces\default\knowledge\graph\graphiti_kuzu.db See the docs: https://docs.kuzudb.com/concurrency for more information.
this happened when i tried to open the graph page while doing eval extraction...
here is the link https://kuzudb.github.io/docs/concurrency/

## Response

Now let me read the service file to understand the connection lifecycle and how the graph page vs eval extraction open the DB.

Let me see how the graph page route and the eval runner each obtain their Kuzu access — same process or separate.

Let me check the process topology — how eval extraction is launched vs. how the graph snapshot is served.

I have enough to diagnose. Let me confirm one thing — whether eval and the graph page share the server process (it changes the fix).

## Diagnosis

I traced the lock conflict end to end. It's a structural issue, not a transient race.

### What's happening

Both the eval extraction and the Graph page open their **own** `KuzuDriver` against the same file, **in the same process**:

| Consumer | Code path | Kuzu object |
|----------|-----------|-------------|
| Eval extraction | `eval_run` → `asyncio.create_task(_runner())` ([knowledge.py:901](hiroserver/hirocli/src/hirocli/admin_svelte/routes/knowledge.py:901)) → `ingest_adam_corpus_via_service` → `GraphitiMemoryService.from_preferences` ([eval_runner.py:485](hiroserver/hirocli/src/hirocli/services/knowledge/eval_runner.py:485)) → `KuzuDriver(...)` ([graphiti_service.py:184](hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:184)) | `kuzu.Database` **#1** (READ_WRITE), held open for the whole multi-minute build |
| Graph page | `GET .../graph` ([knowledge.py:738](hiroserver/hirocli/src/hirocli/admin_svelte/routes/knowledge.py:738)) → `graph_snapshot_payload` → `read_graph_snapshot` → `KuzuDriver(str(path))` ([graphiti_service.py:453](hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:453)) | `kuzu.Database` **#2** — opened fresh on every request |

The eval is a fire-and-forget `asyncio.create_task` in the **same FastAPI process** that serves the Graph page route. So when you open the page mid-build, the snapshot tries to construct a **second `kuzu.Database`** on a file already locked by the eval's driver.

### Why it must fail (per the docs you linked)

> Only **one READ_WRITE Database object** can connect to a database at any time... you cannot have a READ_WRITE `db1` and a separate READ_ONLY or READ_WRITE `db2` and concurrently query the same database.

The rule is **one `Database` object per file** — many `Connection`s from that *one* Database are fine, but a second `Database` (which is what each `KuzuDriver(path)` builds internally) is not. Our design currently creates a fresh Database per ingest *and* per snapshot read. They only coexist without error because, outside of eval, the windows don't overlap and `_release_kuzu` ([graphiti_service.py:101](hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:101)) deterministically drops the lock between operations. During a long eval build, the windows **do** overlap → lock error.

```
                 same process (admin FastAPI server)
   ┌──────────────────────────────┐     ┌─────────────────────────────┐
   │ eval task (minutes)          │     │ GET /knowledge/.../graph     │
   │ KuzuDriver → Database #1 (RW)│     │ read_graph_snapshot          │
   │ ▓▓▓▓▓▓▓ holds file lock ▓▓▓▓▓│     │ KuzuDriver → Database #2 ✗   │
   └──────────────────────────────┘     │  "Could not set lock on file"│
                                         └─────────────────────────────┘
```

### Note on `READ_ONLY` mode (the obvious-looking fix that won't work)

Opening the snapshot driver in `READ_ONLY` does **not** fix this. The docs are explicit that a READ_WRITE Database and a separate READ_ONLY Database cannot concurrently touch the same file. Read-only mode only helps *multiple readers when there is no writer*. The eval is a writer.

## Options to fix

**Option A — Single shared `Database` per workspace (the canonical Kuzu pattern).** A process-wide registry keyed by `db_path` holds one live `kuzu.Database`; both ingest and snapshot reads draw `Connection`s from it. This is exactly Kuzu's "one Database, many Connections" model and the only option that lets you **view the graph while a build runs**.
- *Cost:* Graphiti's `KuzuDriver` builds its Database from a path internally, so this needs either passing a shared `Database` into `KuzuDriver` (need to verify graphiti-core 0.29.1 supports that) or routing snapshot reads through the *same live driver* the ingest holds. Plus refcounting so `_release_kuzu`/`close` doesn't tear down a Database another consumer is still using.

**Option B — Fail-fast with a process-wide lock.** A per-`db_path` guard; if a build holds it, the snapshot route returns a clean "graph build in progress, view unavailable" instead of a raw lock exception. Cheap and safe, but you **can't see the graph during a build** (which is arguably the moment you most want to).

**Option C — Serialize (block) the read behind the same lock.** Snapshot waits for the build to finish. Rejected: builds are multi-minute, so the page would hang.

My recommendation is **A** as the real fix, with **B**'s clean error as a fallback for any path that still can't share the Database. But this is a design decision with real surface area (driver-sharing + lifecycle refcounting), so per our design-first norm I'd rather settle the approach before writing code.

## To get you unblocked right now

The lock is held by the live eval task in the running server. To clear it:
- Let the eval build finish (the eval task closes its driver via `_release_kuzu` on completion), **or**
- Restart the admin server / `hiro stop` to drop the process holding the lock.

The DB file itself is fine — this is an in-process locking conflict, not corruption.

## TL;DR

- **Root cause:** Eval build and the Graph page each construct a **separate `kuzu.Database`** on the same file, in the **same server process**. Kuzu allows only **one Database object per file** → "Could not set lock on file" when they overlap. ([graphiti_service.py:184](hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:184) vs [:453](hiroserver/hirocli/src/hirocli/services/knowledge/graph/graphiti_service.py:453); eval is in-process via `asyncio.create_task` at [knowledge.py:901](hiroserver/hirocli/src/hirocli/admin_svelte/routes/knowledge.py:901)).
- **`READ_ONLY` mode won't fix it** — the docs forbid a RW Database and a separate RO Database on the same file concurrently.
- **Real fix (Option A):** one **shared Database per workspace**, many Connections — lets you view the graph during a build. **Fallback (Option B):** fail-fast "build in progress" message.
- **Unblock now:** finish the eval, or restart the server / `hiro stop` — the file is not corrupted.
- **Next step / open decision:** which option do you want — shared-Database (A), fail-fast (B), or A-with-B-fallback? I'll write a design doc / plan before implementing.