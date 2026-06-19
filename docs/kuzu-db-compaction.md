# Kuzu DB Compaction — Maintenance Runbook

> **What.** The Graphiti Kuzu DB (`<workspace>/knowledge/graph/graphiti_kuzu.db`)
> grows far beyond its live content after sustained ingestion. This is dead-row +
> FTS-index bloat, not real data. The only reclaim path Kuzu 0.11.3 gives us is a
> full **EXPORT → IMPORT** rebuild. The script
> [`scripts/compact_kuzu_db.py`](../scripts/compact_kuzu_db.py) automates it,
> losslessly, with verification.
>
> **Companions:** [`kuzu-shared-database-design.md`](kuzu-shared-database-design.md),
> [`kuzu_issue.md`](kuzu_issue.md).
>
> **Observed:** 272.98 MB → 81.56 MB (**3.35× smaller, −70%**) on a graph of 2,103
> episodes / 1,552 entities / 4,039 facts. Earlier run on a smaller graph:
> 264.85 MB → 65.39 MB (−75%). The reduced size is the **honest steady-state floor**
> given the current embedding model + FTS config (see Prevention).

## Why it bloats

Three compounding causes — none is a leak, all are storage-engine behavior:

1. **Dead-row bloat from updates (the big one).** Kuzu 0.11.3 has **no VACUUM /
   compaction** for variable-length columns. Every time Graphiti re-summarizes an
   `Entity` or rewrites a `RelatesToNode_.fact` during dedupe/merge, the old value
   stays on disk. Measured on the smaller corpus: `Entity.summary` 233 KB live vs
   **4.36 MB stored** (19×); `RelatesToNode_.fact` 212 KB live vs **2.50 MB stored**
   (12×); 1536-dim embeddings stored 2–2.4× over.
2. **FTS index amplification.** Four BM25 indexes (`Entity name+summary`, `Episodic
   content+source+desc`, `RelatesToNode_ name+fact`, `Community name`) are built over
   the **already-bloated** column storage, so the auxiliary tables run ~3–5× the
   inflated text. This is the majority of the on-disk size.
3. **Uncompressed `FLOAT[]` embeddings.** A floor we accept — see Prevention.

A rebuild reclaims (1) and (2) entirely because EXPORT dumps only **live** rows to
parquet, and IMPORT + a fresh FTS build re-pack everything tight.

## How to compact

### Preconditions
- **Stop the server first.** Kuzu takes an **exclusive file lock** while the server
  runs — you cannot export, copy, or even open the DB. `hiro stop` (and
  `hirogate stop` if relevant).
- Run with the venv that has the **matching kuzu pin** (`kuzu==0.11.3`):
  `hiroserver/.venv/Scripts/python.exe`. A version mismatch can refuse to open the file.

### Run it
```bash
# 1) Verify-only: builds graphiti_kuzu.db.rebuilt next to the original, checks it,
#    does NOT swap. Source DB is never mutated.
hiroserver/.venv/Scripts/python.exe scripts/compact_kuzu_db.py \
  "<workspace>/knowledge/graph/graphiti_kuzu.db"

# 2) Rebuild AND swap in place. Keeps the original as graphiti_kuzu.db.bloated-<ts>.
hiroserver/.venv/Scripts/python.exe scripts/compact_kuzu_db.py \
  "<workspace>/knowledge/graph/graphiti_kuzu.db" --swap
```
Default workspace on this machine:
`C:\Users\GF\AppData\Local\hiro\workspaces\default\knowledge\graph\graphiti_kuzu.db`.

The script prints node counts, edge multisets, FTS index presence, and the size
delta. If **any** verification check mismatches it leaves the `.rebuilt` file in
place and refuses to swap (exit 2). Restart the server when done.

### Manual swap (if you ran without `--swap`)
```
stop server
rename graphiti_kuzu.db          -> graphiti_kuzu.db.bloated-<ts>
rename graphiti_kuzu.db.rebuilt  -> graphiti_kuzu.db
start server
```
The rebuilt file is a true drop-in: single-file Kuzu DB, no `.wal`/`.shadow`
sidecars, same Kuzu version, same schema and index definitions.

## What the script does (and the Kuzu bug it works around)

1. `EXPORT DATABASE (format='parquet')` from the **read-only** source → temp dir
   (~1 s; ~34 MB of parquet for the 273 MB DB).
2. **Strips the FTS replay from the export**: removes the auto-generated
   `*_TOKENIZE` macros from `schema.cypher` and empties `index.cypher`.
   - **Why:** Kuzu's `IMPORT DATABASE` replays `index.cypher`, which issues four
     `CALL CREATE_FTS_INDEX(..., stopWords := 'default')`. All four want the same
     shared `default_english_stopwords` catalog table; IMPORT's replay path creates
     it on the first index and then **crashes on the second** with
     *"default_english_stopwords already exists in catalog"*. The macros collide the
     same way. So we skip IMPORT's FTS step entirely.
3. `IMPORT DATABASE` rebuilds **tables + COPYs data only** (clean, no FTS).
4. Recreates the four FTS indexes via the normal **runtime** path
   (`CALL CREATE_FTS_INDEX`), which **tolerates** the shared stopwords table exactly
   as Graphiti does when it builds the graph live, then `CHECKPOINT`.
5. **Verifies losslessly**: per-table node counts and per-`(table, from, to)` edge
   multiset counts must match the source exactly, and all 4 FTS indexes must be
   present. (Edge counts use a structural `MATCH (a)-[r]->(b)` pattern, not the bare
   `count(r)` relationship counter, which is known to over-report by one in some
   Kuzu builds — that "1 missing edge" is a counter quirk, not lost data.)

## Prevention — can we stop it recurring?

**Short answer: not fully, on Kuzu 0.11.3 with the current constraints. Treat
compaction as periodic maintenance.** The bloat is inherent to an
update-heavy workload on a storage engine with no online vacuum. Options, ranked:

| Lever | Effect | Cost / constraint |
|---|---|---|
| **Periodic rebuild** (this script) | Reclaims 100% of dead-row + FTS bloat | Requires server downtime; run on a cadence or a size threshold |
| **Fewer re-summarize/rewrite ops** | Attacks the root cause (each Entity/fact rewrite leaves a dead row) | Tuning Graphiti dedupe/merge aggressiveness trades graph quality for less churn — only worth it if quality holds |
| **Compress embeddings / drop to fewer dims** | Cuts the embedding floor (~half the post-rebuild size is `FLOAT[]`) | **Explicitly ruled out** by the user (no embedding-model change) |
| **Trim FTS coverage** (fewer indexed columns) | Smaller FTS aux tables | **Explicitly ruled out** (no FTS-config change); also hurts recall |
| **Newer Kuzu with compaction** | Would remove the need entirely | Not available at 0.11.3; a version bump is a separate, larger change |

**Recommended operating policy**
- **Don't chase below the post-rebuild floor** (~80 MB here). That size is honest
  given the no-change-embedding and no-change-FTS constraints.
- **Trigger a rebuild on bloat ratio, not raw size.** Rough heuristic: when the live
  `graphiti_kuzu.db` exceeds **~3× a fresh post-compaction size**, run the script.
  After a big ingest/eval batch is a natural checkpoint.
- **A scheduled job is viable** but must `hiro stop` → compact → `hiro start`, so it
  belongs in an off-hours maintenance window, not a live-server cron. Ask before
  wiring one up.

## Cleanup of stale copies

After a successful swap + a server restart that confirms the graph loads, the
`graphiti_kuzu.db.bloated-<ts>` backup (and any older `graphiti_kuzu - backup.db`,
`graphiti_kuzu_2.db`, `*_base_*.db` experiment files) can be deleted to reclaim disk
— they are full-size bloated copies. Keep at least one known-good backup until the
restarted server has served real traffic.
