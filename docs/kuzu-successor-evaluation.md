# Kuzu Successor Evaluation: LadybugDB and Vela

> Research snapshot: 19 June 2026

## Executive conclusion

Ladybug is the only credible long-term embedded-graph successor for HiroLeague. Vela is useful as an experimental, API-compatible Kuzu build, but its maintenance capacity, packaging, and validation are currently too narrow for a foundational dependency.

Recommended direction:

1. Keep Kuzu 0.11.3 temporarily for production stability.
2. Build and qualify a Ladybug driver as the strategic migration path.
3. Do not build a separate Vela driver; it already exposes the `kuzu` API. Test it through the existing driver only if concurrent writes become necessary.
4. Do not depend on Graphiti to maintain either integration. Its maintainers are actively deprecating Kuzu.

## Comparison

| | Original Kuzu | Ladybug | Vela Kuzu |
|---|---:|---:|---:|
| Status | Archived | Active continuation | Active experimental fork |
| Latest release | 0.11.3, 10 Oct 2025 | 0.17.1, 2 Jun 2026 | 0.12.0 commit release, 14 Jun 2026 |
| Stars / forks | 3,969 / 493 | 1,313 / 101 | 38 / 7 |
| Commits, last 90 days | 0 | 383 | 8 |
| Contributors, last 90 days | 0 | 15 | 1 |
| Open issues | 307 | 60 | 0 |
| Issues created / closed, 90 days | 0 / 0 | 110 / 96 | 0 / 0 |
| PRs merged, 90 days | 0 | 160 | 8 |
| Python distribution | PyPI, broad platforms | PyPI, broadest platforms | GitHub assets only |
| Windows Python wheel | Yes | Yes, x64 and ARM64 | No |
| Python import | `kuzu` | `ladybug` | `kuzu` |
| Existing Kuzu database | Native | Not directly readable | Probably compatible; must test |
| Concurrent writes | No | Available, opt-in | Enabled by default |
| Bus factor | Project abandoned | Strongly concentrated in one maintainer | One maintainer |
| License | MIT | MIT | MIT |

Sources: [Kuzu repository](https://github.com/kuzudb/kuzu), [Ladybug repository](https://github.com/LadybugDB/ladybug), [Vela repository](https://github.com/Vela-Engineering/kuzu), [Kuzu releases](https://github.com/kuzudb/kuzu/releases), [Ladybug releases](https://github.com/LadybugDB/ladybug/releases), and [Vela releases](https://github.com/Vela-Engineering/kuzu/releases).

## Original Kuzu

Kuzu 0.11.3 remains the lowest-risk short-term option because it is what HiroLeague already runs and tests. The engine itself was substantial and mature, but it is now frozen.

The maintenance position is decisive:

- The repository is archived; its last code push and release were on 10 October 2025.
- 307 issues and 22 pull requests remain open.
- The backlog includes unresolved crashes, checkpoint corruption, vector-index corruption, and performance problems.
- Python 0.11.3 still has good platform coverage, including Windows, but there will be no fixes for future Python, operating-system, compiler, or security changes.

Sources: [open Kuzu issues](https://github.com/kuzudb/kuzu/issues?q=is%3Aissue%20is%3Aopen), [open Kuzu pull requests](https://github.com/kuzudb/kuzu/pulls?q=is%3Apr%20is%3Aopen), and [Kuzu on PyPI](https://pypi.org/project/kuzu/).

HiroLeague is already paying the maintenance cost:

- Kuzu is pinned at 0.11.3.
- `scripts/compact_kuzu_db.py` exists because deleted or replaced variable-length data is not reclaimed.
- `graphiti_service.py` works around Graphiti's uninitialized `_database` attribute.
- HiroLeague maintains Kuzu-specific FTS rebuilds and `SHORTEST` traversal rewrites.
- Kuzu's exclusive database lock complicates live inspection.

Therefore, "maintain the original driver" means maintaining both a Graphiti driver and a permanently frozen native engine dependency.

## Ladybug

Ladybug is effectively the general-purpose continuation of Kuzu, although its repository is not marked as a GitHub fork. The project states that it was formerly Kuzu in its [README](https://github.com/LadybugDB/ladybug#ladybug).

### Activity and maintenance

Ladybug's activity is materially stronger:

- Six minor release lines, 0.12 through 0.17, since the Kuzu shutdown.
- 383 commits from 15 authors in the last 90 days.
- 110 issues opened and 96 closed during that period.
- 160 merged pull requests.
- Active CI, CodeQL, benchmarks, release workflows, extension publishing, and cross-platform wheel builds.

Maintainer concentration remains a risk: 141 of the last 153 commits were authored by Arun Sharma. Ladybug has outside contributors, but its core maintenance capacity is still dominated by one person.

### New capabilities

Compared with Kuzu 0.11.3, Ladybug has added or developed:

- Foreign and Parquet-backed tables.
- DuckDB integration and query pushdown.
- Multiple graph catalogs with `CREATE GRAPH`, `USE GRAPH`, and `DROP GRAPH`.
- Arrow-backed node and relationship tables.
- Concurrent writes and non-blocking checkpointing, originally ported from Vela.
- Flexible thread-pool sizing.
- JSON type work.
- HTTP/S3 remote access, remote `ATTACH`, Xet, and object-store support.
- Windows ARM64 packages.
- Secondary ART indexes and statistics-aware optimization.
- New packed-path execution work and vector-search improvements on the current `main` branch.

The Vela concurrency port is visible in [Ladybug commit `05d6f0f`](https://github.com/LadybugDB/ladybug/commit/05d6f0f2a); subsequent work is visible in [Ladybug's commit history](https://github.com/LadybugDB/ladybug/commits/main/).

### Issue handling and relevant risks

Ladybug is visibly engaging with difficult reports, but two open issues are directly relevant to HiroLeague:

- A persistent FTS index on an empty table can fail after reopening: [Ladybug issue #464](https://github.com/LadybugDB/ladybug/issues/464).
- Large on-disk variable-length traversals can become prohibitively expensive: [Ladybug issue #475](https://github.com/LadybugDB/ladybug/issues/475).

These must be explicit acceptance tests because HiroLeague depends heavily on persistent FTS and bounded path traversal.

### Packaging

Ladybug has the strongest operational packaging of the candidates:

- Installation through `pip install ladybug`.
- Python 3.10 through 3.14.
- Windows x64 and ARM64.
- macOS x64 and ARM64.
- Linux glibc and musl, x64 and ARM64.
- Node, Java, Rust, Go, Swift, WASM, and native binaries.

See [Ladybug on PyPI](https://pypi.org/project/ladybug/).

### Database migration compatibility

An independent compatibility test created a Kuzu 0.11.3 database and attempted to open it with Ladybug 0.17.1. Ladybug rejected it with:

```text
Unable to open database. The file is not a valid Lbug database file!
```

Ladybug uses `LBUG` file magic instead of `KUZU`, so it is not an in-place package replacement. Migration requires:

1. Stop Hiro.
2. Export from Kuzu 0.11.3.
3. Import into a new Ladybug database.
4. Rebuild Graphiti's four FTS indexes.
5. Verify node counts, edge signatures, search parity, and timestamps.
6. Swap databases only after validation.

The existing Kuzu compaction workflow already implements much of this pattern and can be adapted into a migration tool.

## Vela Kuzu

Vela deliberately preserves the `kuzu` module, C++ namespaces, Cypher dialect, and file identity. It should not require a distinct Graphiti driver.

Its principal work is concurrent multi-writer support, background or non-blocking checkpointing, checkpoint-recovery hardening, an extension registry, and newer Python wheels. The latest change enables concurrent writes by default and adds substantial transaction and WAL tests. See [Vela pull request #17](https://github.com/Vela-Engineering/kuzu/pull/17).

The problems are project maturity and distribution:

- Only one contributor during the last 90 days.
- Eight merged pull requests, all internal and with no review discussion.
- No public issue traffic, which is absence of evidence rather than evidence of reliability.
- Release tags are commit-stamped builds of `0.12.0`, not conventional patch releases.
- The primary workflow builds Linux and macOS ARM Python wheels but no Windows wheels.
- Vela does not control the `kuzu` PyPI package; installation requires direct release assets or a privately maintained package registry.
- Most original upstream workflows were disabled and replaced primarily by build-and-release workflows.

Vela's source retains Kuzu's `KUZU` file magic and storage version 39, so compatibility with 0.11.3 appears likely. This is code-level evidence, not sufficient migration proof; a copy of a real Graphiti database must be tested before relying on it.

For HiroLeague, Vela's main feature has limited value today: the Kuzu registry and Graphiti connection already serialize writes, and Graphiti is instantiated with `max_concurrent_queries=1`. Enabling multi-writer behavior would add storage risk without removing the current application-level bottleneck.

## Graphiti's position

Graphiti 0.29.2 marks `KuzuDriver` deprecated and says it will be removed. See the [current Kuzu driver](https://github.com/getzep/graphiti/blob/main/graphiti_core/driver/kuzu_driver.py) and [current dependency declaration](https://github.com/getzep/graphiti/blob/main/pyproject.toml).

This is already affecting maintenance:

- [Graphiti pull request #1508](https://github.com/getzep/graphiti/pull/1508) fixed two real Kuzu driver defects: missing `_database` initialization and missing FTS index construction.
- Graphiti closed it unmerged on 8 June, stating that Kuzu support had been deprecated.
- [Ladybug driver RFC #1509](https://github.com/getzep/graphiti/issues/1509) proposes an approximately 280-line driver and reports 32 passing driver, operations, and end-to-end tests.
- The RFC had received no maintainer response as of this research snapshot.

The RFC identifies the concrete Ladybug differences:

- Replace `kuzu.*` calls with `ladybug.*` calls.
- Install and load the FTS extension before index creation.
- Preserve `None` values and fill missing parameters because Ladybug rejects unbound query parameters that Kuzu treated as null.
- Reuse Graphiti's existing Kuzu operation classes and Cypher.
- Add `LADYBUG` to Kuzu-dialect provider branches.

This makes a Ladybug driver technically modest, but it will be owned by HiroLeague unless Graphiti changes direction.

## HiroLeague implementation impact

### Original Kuzu

No immediate migration is required, but HiroLeague must preserve or vendor the Graphiti Kuzu driver before upgrading to a Graphiti release that removes it. Existing workarounds, compaction tooling, and Kuzu-specific queries remain necessary.

### Ladybug

The driver can reuse Graphiti's Kuzu operations layer, but HiroLeague must also update its own Kuzu provider gates and tooling:

- Driver construction in `graphiti_service.py`.
- FTS rebuild gating in `graphiti_ingest.py`.
- Provider checks and Kuzu query generation in `graphiti_bfs.py`.
- Tests that instantiate or assert `KuzuDriver` and `GraphProvider.KUZU`.
- `scripts/compact_kuzu_db.py`, or a replacement migration/compaction tool using the `ladybug` API.

The custom `SHORTEST` queries, FTS calls, timestamp behavior, database locking, and export/import workflow require real-engine parity tests rather than mocked driver tests alone.

### Vela

No new Graphiti driver should be implemented. A trial should replace the native `kuzu` wheel while retaining the existing Graphiti driver and provider value. The primary work would be building and hosting reproducible Windows wheels and running the complete Kuzu parity suite.

## Decision and execution plan

1. Keep Kuzu 0.11.3 for the next production release.
2. Vendor or preserve Graphiti's Kuzu driver before upgrading beyond the currently pinned Graphiti version.
3. Implement a Ladybug driver behind HiroLeague's graph-store construction boundary.
4. Run identical corpora against Kuzu and Ladybug, measuring:
   - ingestion correctness and throughput;
   - FTS results and reopen behavior;
   - `SHORTEST` traversal parity, latency, and memory;
   - database growth after repeated deduplication and fact replacement;
   - checkpoint and restart integrity;
   - Windows behavior;
   - export/import fidelity.
5. Switch only if Ladybug resolves or avoids HiroLeague's concrete Kuzu problems.

## Effort estimate

| Work | Expected effort |
|---|---:|
| Vela compatibility trial on Linux | 1–2 engineering days |
| Build and host Vela Windows wheels | Additional packaging and CI work |
| Ladybug driver implementation | Approximately 2–4 engineering days |
| Ladybug migration and platform qualification | Approximately 1–2 weeks |
| Continue with Kuzu | Lowest immediate effort, increasing long-term ownership |

The strategic choice is Ladybug versus privately maintaining a frozen Kuzu stack. Ladybug is worth building and qualifying a driver for. Vela is worth a compatibility experiment, but not a separate driver or production commitment at its current maturity.
