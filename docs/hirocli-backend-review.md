# hirocli Backend — Robustness & Refactor Review

**Status:** 📋 Review (point-in-time assessment) · **Date:** 2026-06-24
**Scope:** the Python server backend `hiroserver/hirocli` (~82k LOC) — runtime core, domain layer, services (knowledge/memory/eval/media), tools, and admin HTTP.
**Companion:** [hirocli-architecture-overview.md](hirocli-architecture-overview.md) (the high-level map this review critiques).
**Method:** five focused read-passes (one per subsystem) plus direct verification of the two highest-impact claims.

---

## Overall assessment

The architecture is **fundamentally sound** — this is a hardening job, not a rewrite. The composition root (`runtime/server_process.py`), the `ServerContext` shared-state bag, the `DomainEventBus` thread→loop trampoline, the Tool abstraction, and the provider-factory + credential-store pattern are all the *right* designs.

The weaknesses are **consistent and cross-cutting**, which is the good news — a handful of systemic fixes hit the whole codebase. The dominant gap is **resilience at the boundaries** (external calls, task lifecycle, cross-store consistency), not internal structure. Internal-structure issues (god files) are real but secondary.

```
                    Robustness maturity by subsystem
  high │ metrics ████  memory(params) ████  image-gen ████
       │ CLI ████  credentials(storage) ███
  med  │ runtime-core ███  domain-stores ██▌  knowledge-graph ██▌
       │ eval ██  STT/TTS ██▌
  low  │ vision █  admin-HTTP-auth █  external-call-resilience █
       └────────────────────────────────────────────────────
```

---

## Tier 1 — Systemic robustness gaps (fix first)

### 1.1 No timeouts / retries / backoff on *any* external call

The single biggest gap; it spans every subsystem that touches a model or DB.

| Layer | Evidence | Failure mode |
|---|---|---|
| Embeddings | `services/knowledge/embedder.py:78`, `service.py:1268` | one 429 fails a whole ingest |
| Graph ingest LLM | `services/knowledge/graph/graphiti_ingest.py:496` | hung extraction holds the **Kuzu write lock** indefinitely → wedges all writers |
| Agent retrieval | `services/knowledge/agent/retrieval_nodes.py:190` | stalls an entire chat turn |
| STT / TTS | `services/stt/openai_provider.py:168` | no per-call timeout; tenacity retries latency-unbounded |
| Vision | `services/vision_service.py:108` | no try/except, no timeout, no retry at all |
| Memory recall | `services/memory/graphiti_conversation.py:172` | locked Kuzu / hung LLM stalls the turn |

**Direction:** one shared `hiro_commons` helper — `asyncio.wait_for` + bounded retry/backoff + a transient-vs-fatal classifier — with timeout/attempts sourced from tuning-profile preferences. Gemini providers currently retry on *any* exception (burning attempts on auth errors); OpenAI retries only on `(RateLimitError, APIError)`. One classifier fixes both. **Prioritize the ingest-LLM path** because it holds the Kuzu lock.

### 1.2 Fire-and-forget tasks + a magic-number shutdown drain

- Agent runs, request handlers, and domain-event handlers are spawned with **dropped task references** (`runtime/communication_manager.py:135`, `runtime/inbound_pipeline.py:158`, `domain/events.py:143`) — GC can kill them mid-flight and exceptions vanish.
- Shutdown is `await asyncio.sleep(1.5); server_task.cancel()` (`runtime/server_process.py:291`) — a graph run longer than 1.5 s is cut off mid-DB-write. The trailing `except (CancelledError, Exception): pass` swallows every shutdown error unlogged.
- `gather(..., return_exceptions=True)` means a coro that **crashes at startup** (e.g. `channel_manager.run()`) is captured and never inspected — the server looks "up" while a core component is dead.

**Direction:** track spawned tasks in `set[asyncio.Task]` per spawner; on shutdown, `gather` them with a real timeout instead of `sleep(1.5)`; log non-cancelled exceptions from the gather result.

### 1.3 A single send failure can kill all outbound delivery

`send_to_channel` / `send_event_to_channel` call `await ch.ws.send(...)` with **no try/except** (`runtime/channel_manager.py:461`). A `ConnectionClosed` propagates into `OutboundPipeline.run`, whose only `finally` is `task_done()` — the exception **terminates the one outbound worker coroutine**, silently halting *all* delivery for the rest of the process lifetime. Wrap the send so one bad message drops one message.

### 1.4 Cross-store writes are non-atomic with *opposite* orderings

Upsert writes **vectors→catalog**; delete writes **catalog→vectors** (`services/knowledge/service.py:1314`). Crash recovery only flips the catalog row to `failed` — it **never reconciles Qdrant** (`services/knowledge/catalog_store.py:86`). Result: `ready` rows pointing at missing vectors, or orphaned vectors with no row, invisible to dedup. Pick the catalog as source of truth, use one ordering, add a vector-orphan sweep to `recover_abandoned_work`.

### 1.5 Non-atomic writes to critical config files

`preferences.json`, `providers.json`, the registry, and the master key all use direct `write_text` (`domain/preferences.py:1473`, `domain/credential_store.py:133`). A crash or full disk mid-write truncates them — and `providers.json` then **silently resets to empty** via a broad-except load, losing every configured provider. Use temp-file + `os.replace` (one `atomic_write_text` helper).

---

## Tier 2 — Correctness bugs found during review

| Bug | Location | Effect | Confidence |
|---|---|---|---|
| Stdlib logger called with structured kwargs | `domain/credential_store.py:174,191,245,360,367` | keyring-failure **fallback path itself raises `TypeError`** — graceful degradation becomes a hard crash | **Verified** |
| `except Exception: pass` swallowing subprocess/WS failures | `runtime/channel_manager.py:201,209,271` | orphaned plugin subprocesses; `terminate()` never escalated to `kill` | High (violates project rule) |
| `except Exception: pass` on Qdrant index creation | `services/knowledge/vector_store.py:567` | filtered retrieval silently runs without indexes | High |
| Silent corrupt-config swallow, no log | `domain/config.py:133`, `domain/workspace.py:106` | corrupted registry silently discarded; user loses workspaces with no signal | High |
| `_row_to_dict` leaves `metadata` as raw string on JSON error | `domain/message_store.py:494` | deferred `AttributeError` downstream instead of logged at source | Medium |
| Process-global dedup-floor monkeypatch is last-writer-wins | `services/knowledge/graph/graphiti_service.py:104` | workspace B's dedup floor overwrites workspace A's (multi-workspace-per-process) | Medium |

> The `credential_store` bug is **verified** and cheap: it uses stdlib `logging.getLogger(__name__)` but calls `logger.warning("…", provider_id=…, error=…)`. Stdlib `Logger.warning` rejects arbitrary kwargs → `TypeError` raised *inside* the keyring-fallback path whose whole purpose is to degrade gracefully. Swap to `hiro_commons.log.Logger` (used everywhere else) and the structured kwargs become valid.

---

## Tier 3 — The Tool abstraction leaks for knowledge / eval / memory

The "one Tool = CLI + agent + HTTP" design **holds well** for CLI commands and ~13 admin domains (route → `admin/features/*/service` → `*Tool().execute()`). But it **leaks badly** in three domains:

- `admin_svelte/routes/knowledge.py:27` imports `KnowledgeService` directly and **clones the Tool's own private wiring** (`_resolve_service`/`_close_if_owned`), re-issuing every operation the `Knowledge*Tool` classes already expose over HTTP.
- `admin_svelte/routes/eval.py:165` re-implements the entire eval pipeline in a nested `_runner` closure — even though `EvalRunTool`'s docstring explicitly says it exists *"so the same implementation backs CLI, the admin UI Eval Batch button, and any agent."* The route never calls it.
- `routes/eval.py` even imports `_resolve_service`/`_success` **from its sibling `routes/knowledge.py`** — duplicated wiring promoted to a cross-module private.

Every knowledge/eval operation now has **two implementations that will drift**. Fix: route these through `registry.invoke_async(...)` (HTTP path already exists at `runtime/http_server.py:160`) or a thin service wrapper like the other 13 domains.

> Note: `admin/` is **not** dead code or a half-finished migration — it is the live service layer that `admin_svelte/` routes call into. The `admin` vs `admin_svelte` naming is misleading and invites the wrong refactor (deleting "old" `admin/`). Consider renaming/merging into one cohesive package.

---

## Tier 4 — God files (decompose along existing seams)

None is tangled beyond repair; each has a clean extraction.

| File | LOC | Extract |
|---|---|---|
| `domain/preferences.py` | 2127 | `schema` / `prompts` (~491 LOC of prose → data files) / `io` / `resolution` (15 `resolve_*` fns) |
| `services/knowledge/service.py` (KnowledgeService) | 1388 | `RerankerDownloadManager` (subprocess supervision), `IngestPipeline`, answer façade |
| `services/knowledge/graph/graphiti_service.py` | 1379 | a 330-LOC snapshot/export subsystem + Kuzu-lifecycle + mapping |
| `admin_svelte/routes/knowledge.py` | 1139 | CRUD / graph routes / rerankers / SSE — and **remove the in-process Tkinter folder picker from the server** |
| `admin_svelte/routes/eval.py` | 1007 | move `_runner` into `services/eval/runner.py` |
| `services/eval/runner_memory.py` | 1087 | two 250-LOC mega-functions; also **wrap per-question failures** — `TaskGroup` lets one error kill the whole expensive run (`:1003`) |
| `runtime/agent_manager.py` | 1002 | 8 hot-reload reactors swap live-graph services with **only a partial lock** — race against in-flight runs; needs a `MediaServiceBundle` + one rebuild lock |
| `runtime/graph_event_subscriber.py` | 933 | cost-accounting math + a stringly-typed `_run_state` dict bag → typed `RunState` dataclass |

---

## Tier 5 — Maintainability / layering

- **Provider duplication:** STT, TTS, and image-gen are near-verbatim copies of the same provider-ABC + service-loop + `*_sync` thread-wrapper + factory. Lift a `ModelRoutedService` base into `hiro_commons` (per the `common-utility` rule) — then Tier-1 fixes apply once, not 4×. **Bring `vision_service.py` into this pattern too** — it's the lone outlier with hardcoded `openai:gpt-4o-mini` + `temperature=0.7` + env-var config.
- **DB hygiene:** ~40 ad-hoc `sqlite3.connect` sites, **no `WAL`, no `busy_timeout`**, and `foreign_keys=ON` set in only one place — so the schema's `ON DELETE CASCADE` is decorative and every store hand-cascades. One shared connection helper fixes the lock-storm risk *and* makes cascades real.
- **Layering inversion:** domain reaches *up* into services (`save_preferences` imports `services.knowledge` at `domain/preferences.py:1491`; `domain/local_models.py:94`) via function-local imports masking a cycle. `runtime/agent_manager.py` has **31** function-local imports hiding a real `agent_manager ↔ graph_event_subscriber ↔ communication_manager` cycle.
- **Admin HTTP:** **no auth** (loopback-only — `admin/run.py:76`) + raw `str(exc)` returned to clients across handlers, leaking internal paths/DB messages.
- **Hardcoded knobs to promote to prefs:** vector batch size, reranker `top_n`, prefetch limit, distance metric, fallback-snippet caps; plus graph defaults (`sim_min_score`, `query_timeout_s`, `num_results`) are **defined twice** and will drift.
- **Eval reproducibility:** no LLM seed captured and no corpus/judge-prompt version hash, yet results accumulate across runs in `eval_results.db` — an edited corpus silently contaminates merged summaries.
- **Memory agentic-recall parity:** the sophisticated `services/memory/agent/` retrieval loop benefits only the eval harness; live chat uses single-shot `GraphitiConversationMemory.search()`, yet prefs/docs imply parity. Either promote it to live chat or relabel it eval-only.

---

## Suggested sequencing

```
Quick wins (correctness, low effort, do now)
  └─ credential_store stdlib-logger fix · except:pass logging · atomic config writes
     · log corrupt-config swallows · per-question eval guard
Foundational (one helper, broad payoff)
  └─ shared external-call wrapper (timeout+retry+classify) in hiro_commons
     · shared SQLite connection helper (WAL/busy_timeout/FK)
     · task-tracking + real shutdown drain
Structural (higher effort, schedule deliberately)
  └─ decompose preferences.py + KnowledgeService + the two route god-files
     · de-duplicate knowledge/eval admin routes onto the Tool layer
     · ModelRoutedService base + fold in vision · resolve domain→services cycle
Then verify
  └─ admin API auth · cross-store consistency sweep · memory agentic-recall parity decision
```

---

## Keep as-is (bright spots)

- `domain/events.py` — the `DomainEventBus` thread→loop trampoline is the correct abstraction.
- `services/metrics/collector.py` — blocking `psutil` via `to_thread`, per-iteration error isolation, slow-subscriber drop on `QueueFull`.
- The CLI layer — validates args, clean exit codes, domain-exception → message mapping.
- Memory's zero-hardcoded-params discipline and reuse of the graph engine.
- Credential *storage* (keyring + env fallback, never logs the token) — only its *logging call* is broken.

---

## TL;DR

- **The architecture is sound** — hardening, not rewrite.
- **#1 issue: zero timeout/retry/backoff on any external call** across every subsystem (a hung ingest model even holds the **Kuzu write lock**). Fix with one shared `hiro_commons` wrapper.
- **Three highest-payoff robustness fixes:** the external-call wrapper; **track fire-and-forget tasks + replace `sleep(1.5)` shutdown** with a real drain; **wrap `ws.send`** so one failure doesn't kill all outbound delivery.
- **Real correctness bugs** (not just smells): `credential_store` stdlib-logger `TypeError` in its own fallback (**verified**); `except: pass` leaking subprocesses/indexes; silent corrupt-config discard; non-atomic config writes that can wipe `providers.json`.
- **The Tool abstraction leaks** for knowledge/eval/memory — admin routes clone the Tool implementations → two copies that will drift.
- **God files** (`preferences.py`, `KnowledgeService`, two admin routes, `runner_memory`, `agent_manager`) have clean extraction seams — decompose deliberately.
- **Cross-cutting cleanups:** `ModelRoutedService` base for STT/TTS/image-gen/**vision**; SQLite `WAL`/`busy_timeout` + real FK cascades; resolve the domain→services cycle; **auth on the admin API** + stop leaking `str(exc)`.
