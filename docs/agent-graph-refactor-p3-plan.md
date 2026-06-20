# P3 — Declarative Ledger: the `observe()` Family

> **Execution plan (single source) for Stage P3** of
> [`agent-graph-refactor-design.md`](agent-graph-refactor-design.md), following
> [`P1`](agent-graph-refactor-p1-plan.md) and [`P2`](agent-graph-refactor-p2-plan.md).
> Written so a junior agent can build and **self-validate** the highest-observability-risk
> stage without regressing a single ledger row.
>
> **Preconditions:** **P1 + P2 landed and green.** The §5.2 characterization net **including
> committed ledger-row snapshots** is green. P3's entire safety model rests on those
> snapshots — if they don't exist or aren't byte-comparable, **stop and build them first.**
>
> **Mode:** initial development — **no backward compatibility / no wrappers**. We change how
> nodes talk to the ledger; we do **not** change what the ledger records.
>
> **Status:** _Ready to build._ Resolves the design doc's open "P3 shape" decision (§1.1).
>
> **Post-P1/P2 reconciliation (read first — these are verified facts about the landed net):**
> - **"Ledger-row snapshots" are in-test assertions, not golden `.snap` files.** The net uses a
>   `RecordingLedgerSink` (in `runtime/tests/graph_fakes.py`) that captures each node's
>   `to_row()` dict in `.captured`, plus projections the tests assert on: `.nodes()` (ordered
>   node names), `.decisions()` (`node → (kind, detail)`), `.row(node)`, `.has_usage(node)`.
>   "Byte-identical / unchanged" therefore means **those assertions still pass without editing
>   them** — there is no file to `git diff`. A bad translation shows up as a failing assertion.
> - **Fakes to reuse by name:** `ScriptedChatModel` + `ai_text()` / `ai_tool_call()` / `echo_tool`
>   (chat model + scripted turns), `FakeSTT/FakeVision/FakeTTS/FakeMemory`,
>   `FakeKnowledgeSubgraph` / `FakeKnowledgeService`, `make_inbound_envelope()`, and `run_graph()`
>   — all in `runtime/tests/graph_fakes.py`.
> - **P3 touches node *bodies* only, never `add_node` wiring** — so the known
>   `retry=`→`retry_policy=` deprecation in `chat.py` stays out of scope (tracked for P4).
> - **Two guard styles exist — you must convert BOTH (verified counts).** `base.py` is mostly the
>   walrus form `if entry := current_entry.get():` (36×, + 3 plain-assign), but
>   `knowledge/agent/graph.py` is mostly **plain-assign** `entry = current_entry.get()` then a
>   later `if entry:` (29 walrus + ~13 plain `if entry:` blocks). §3 has a pattern for **each**
>   (P-A walrus, P-A2 plain-assign), and Gate A greps for **both**. ⚠️ Converting only the walrus
>   form leaves ~16 `if entry:` blocks behind while the walrus grep reads falsely-green.

---

## 1. Goal & scope

**Goal.** Remove the imperative ledger boilerplate from node bodies — the ~60
`if entry := current_entry.get(): entry.set_…()` guard blocks — by introducing a small
**declarative facade** on the ledger, while keeping every emitted row **byte-identical**.

**In scope:** add `observe()`, `substep_scope()`, `record_child()` to `ledger.py`; rewrite
~20 node bodies in `base.py` and `services/knowledge/agent/graph.py` to use them; add facade
unit tests + lean on the existing ledger-row snapshots.

**Out of scope:** changing row *content/shape*, node *logic*, event emission, node-group split
(P4), state restructuring (P6). **P3 is a pure instrumentation-ergonomics refactor.**

### 1.1 Decision: `observe()` family, **not** a `NodeResult` return

The design doc floated two shapes and leaned `NodeResult`. After reading the node bodies, a
pure `NodeResult` return **cannot** achieve the goal, because three patterns legitimately need
the live entry *mid-body* and don't fit a single return value:

| Pattern | Why a return value can't express it | Node(s) |
|---|---|---|
| **Usage recorded before `raise`** | `add_usage(...)` + `fail(...)` then the exception propagates — there is no return | chat `call_model`, knowledge `rewrite_query`/`embed_query`/`rerank`/`call_model` |
| **Per-tool child rows in a loop** | N child rows spawned inside a `for` loop — not one result | chat `tools` |
| **Substep nesting** needs `entry.step_index` | the nested subgraph/ingest rows must read the parent's step index *while the node runs* | chat `_store_turn_memory`, knowledge `knowledge_retrieve` |

A `NodeResult` would still leave all three imperative *and* force every early-`return` site to
change. The **`observe()` family** instead collapses the boilerplate, handles all three cases
declaratively (a context manager + a child helper), and is a smaller, safer diff for the
riskiest stage. **Recorded decision: build the `observe()` family.**

**Refined exit criterion** (the design doc said "zero `current_entry.get()`"): *no
`if entry := current_entry.get():` guard blocks remain in node bodies, and no node calls
`current_substep.set(...)` / `entry.spawn_child(...)` directly.* The **one sanctioned**
remaining direct-entry use is knowledge `graph_expand` (§4.3), which passes the entry object to
`flush_graph_expand(...)` and reads `entry.run_id`/`entry.step_index` for the trace sidecar —
genuine API needs, clearly commented, not boilerplate.

---

## 2. The facade — add to `ledger.py`

These belong in `ledger.py` (they touch `current_entry`, `current_substep`, `LedgerEntry`) —
**not** `graph_kit.py` (which stays pure). All three are **no-ops when there is no active
entry**, so nodes call them unconditionally.

```python
from contextlib import contextmanager

def observe(
    *,
    input: str | None = None,
    output: str | None = None,
    decision: str | tuple[str, str] | None = None,
    usage: dict | None = None,
    skipped: str | None = None,
    error: str | None = None,
    fail: dict | None = None,                 # {"code": str, "message"?: str, "decision"?: str}
    input_max_len: int = 280,
    output_max_len: int = 280,
) -> None:
    """Declarative ledger write for the current node. No-op without an active entry.

    Each argument maps 1:1 to a LedgerEntry setter so a former guard block translates exactly:
    input→set_input_preview, output→set_output_preview, decision→set_decision,
    usage→add_usage(**usage), skipped→set_skipped, error→set_error, fail→fail(...).
    """
    entry = current_entry.get()
    if entry is None:
        return
    if input is not None:
        entry.set_input_preview(input, max_len=input_max_len)
    if usage is not None:
        entry.add_usage(**usage)
    if decision is not None:
        kind, detail = decision if isinstance(decision, tuple) else (decision, "")
        entry.set_decision(kind, detail)
    if skipped is not None:
        entry.set_skipped(skipped)
    if error is not None:
        entry.set_error(error)
    if output is not None:
        entry.set_output_preview(output, max_len=output_max_len)
    if fail is not None:
        entry.fail(fail["code"], message=fail.get("message", ""),
                   decision=fail.get("decision", "provider_error"))


@contextmanager
def substep_scope():
    """Nest child rows (subgraph / ingest) under the current node's step. No-op without entry."""
    entry = current_entry.get()
    token = current_substep.set(entry.step_index) if entry is not None else None
    try:
        yield
    finally:
        if token is not None:
            current_substep.reset(token)


def record_child(
    *,
    node: str,
    status: str = "ok",
    elapsed_ms: int = 0,
    branch_index: int | None = None,
    input: str | None = None,
    output: str | None = None,
    decision: str | tuple[str, str] | None = None,
    usage: dict | None = None,
    fail: dict | None = None,
) -> None:
    """Spawn + fill one child ledger row under the current entry. No-op without entry."""
    parent = current_entry.get()
    if parent is None:
        return
    child = parent.spawn_child(node=node, status=status, elapsed_ms=elapsed_ms,
                               branch_index=branch_index)
    if input is not None:
        child.set_input_preview(input)
    if output is not None:
        child.set_output_preview(output)
    if usage is not None:
        child.add_usage(**usage)
    if decision is not None:
        kind, detail = decision if isinstance(decision, tuple) else (decision, "")
        child.set_decision(kind, detail)
    if fail is not None:
        child.fail(fail["code"], message=fail.get("message", ""),
                   decision=fail.get("decision", "provider_error"))
```

- [ ] Add the three to `ledger.py` and to its `__all__` (if present).

> **Byte-stability is the contract.** `observe`/`record_child` call the **same** `LedgerEntry`
> setters with the **same** arguments the node used before — only the call site moves. As long
> as each former guard block becomes **exactly one** `observe(...)` call (don't merge across
> blocks, don't drop a field), the resulting row is identical.

---

## 3. Translation patterns

Apply these mechanically. Each former `if entry := current_entry.get():` block → one
`observe(...)`.

```text
# P-A  preview + decision (happy path)
- if entry := current_entry.get():
-     entry.set_input_preview(f"q: {text}")
-     entry.set_decision("retrieved" if hits else "empty", str(len(hits)))
-     entry.set_output_preview(preview)
+ observe(input=f"q: {text}",
+         decision=("retrieved" if hits else "empty", str(len(hits))),
+         output=preview)

# P-A2  plain-assign guard (the DOMINANT form in knowledge/agent/graph.py)
# The node grabs the entry early, then guards later with `if entry:` (not a walrus). Both the
# assignment AND the guard block are removed; the body keeps whatever non-ledger logic sat between.
- entry = current_entry.get()
  ...
- if entry:
-     entry.set_decision("ok", f"hits_{len(hits)}")
-     entry.set_output_preview(preview, max_len=KNOWLEDGE_PREVIEW_MAX)
+ ...
+ observe(decision=("ok", f"hits_{len(hits)}"),
+         output=preview, output_max_len=KNOWLEDGE_PREVIEW_MAX)
#  ⚠️ Exception: `graph_expand` KEEPS its `entry = current_entry.get()` (it passes the entry to
#  flush/sidecar — §4.3). Every OTHER plain-assign node drops the assignment entirely.

# P-B  early-return skip
- if entry := current_entry.get():
-     entry.set_decision("skipped", "disabled")
-     entry.set_output_preview("results: 0; disabled")
  return {}
+ observe(decision=("skipped", "disabled"), output="results: 0; disabled")
  return {}

# P-C  custom output budget
- entry.set_output_preview(f"{head} · {rows}", max_len=KNOWLEDGE_PREVIEW_MAX)
+ observe(output=f"{head} · {rows}", output_max_len=KNOWLEDGE_PREVIEW_MAX)

# P-D  usage + fail before raise
- if entry := current_entry.get():
-     entry.add_usage(provider=provider, model=effective_model)
-     entry.fail(_error_slug(exc), message=str(exc))
  raise
+ observe(usage={"provider": provider, "model": effective_model},
+         fail={"code": _error_slug(exc), "message": str(exc)})
  raise

# P-E  skipped / error variants
- if entry := current_entry.get():
-     entry.set_decision("skipped_unsupported", "vision_unavailable")
-     entry.set_skipped("vision_unavailable")
-     entry.set_output_preview("error: vision_unavailable")
+ observe(decision=("skipped_unsupported", "vision_unavailable"),
+         skipped="vision_unavailable", output="error: vision_unavailable")

# P-F  substep nesting
- entry = current_entry.get()
- substep_token = current_substep.set(entry.step_index) if entry is not None else None
- try:
-     out = await self._knowledge_subgraph.ainvoke(sub_input)
- finally:
-     if substep_token is not None:
-         current_substep.reset(substep_token)
+ with substep_scope():
+     out = await self._knowledge_subgraph.ainvoke(sub_input)

# P-G  per-tool child row
- parent_entry = current_entry.get()
- if parent_entry is not None:
-     child = parent_entry.spawn_child(node=…, status=…, elapsed_ms=…, branch_index=idx)
-     child.set_input_preview(…); child.set_output_preview(…)
-     child.set_decision("ok","ok")  # or child.fail(slug, decision="client_error")
+ record_child(node=…, status=…, elapsed_ms=…, branch_index=idx,
+              input=…, output=…,
+              decision=("ok","ok"),                                  # success
+              fail={"code": slug, "decision": "client_error"})       # failure (omit decision arg above)
```

> **`fail` default-matching cue:** the old default for `entry.fail(code)` is
> `message=""`, `decision="provider_error"`. Only put `message`/`decision` in the `fail` dict
> when the original call passed them — otherwise the facade applies the same defaults and the
> row stays identical.

---

## 4. Node conversion checklist

Work **one node group at a time, re-running the snapshot gate after each** (§6 Gate D). Tick
each node once converted and snapshot-clean.

### 4.1 `runtime/agent_graph/base.py`
- [ ] `stt_node` — P-A/P-D/P-E
- [ ] `vision_node` — P-A/P-E (uses `set_error` → `error=`)
- [ ] `media_failed_node` — P-A
- [ ] `memory_search_node` — P-A/P-B/P-D
- [ ] `knowledge_retrieve_node` — P-A/P-B/P-D **+ P-F** (`substep_scope()`)
- [ ] `make_compose_context_node` closure — P-A
- [ ] `make_call_model_node` closure — P-A **+ P-D** (pre-raise usage/fail)
- [ ] `make_tools_node` closure — **P-G** (`record_child`)
- [ ] `memory_out_node` — P-A/P-B
- [ ] `_store_turn_memory` (helper) — P-A/P-B/P-D **+ P-F**
- [ ] `tts_node` — P-A/P-D/P-E
- [ ] `finalize_node` — P-A/P-D
- [ ] Add `observe, substep_scope, record_child` to the existing `from .ledger import (...)`.
- [ ] **Skip** (no entry pokes): `ingest_node`, `gather_node`, `trim_history_node`,
      `context_build_node`, and the pure routers (`input_gate`, `knowledge_fanout`,
      `should_continue`, `tts_gate`, `dispatch_media`).

### 4.2 `services/knowledge/agent/graph.py`
- [ ] `rewrite_query` — P-A/P-B/P-D
- [ ] `graph_fetch` — P-A/P-B/P-C
- [ ] `embed_query` — P-A/P-D
- [ ] `vector_search` — P-A/P-B/P-C
- [ ] `rerank` — P-A/P-B/P-C/P-D
- [ ] `build_context` — P-A/P-C
- [ ] `call_model` — P-A/P-D
- [ ] `finalize` — P-A/P-B
- [ ] Add `observe, substep_scope, record_child` to the ledger import line.
- [ ] **Skip:** `parse_query`, `build_filters`.

### 4.3 `graph_expand` — the **one sanctioned** exception
Convert its `if entry: entry.set_…` preview/decision pokes to `observe(...)` like everywhere
else, **but keep** a single explicit, commented block for the parts that need the entry object:

```python
entry = current_entry.get()  # kept: flush + sidecar need the entry object, not just previews
...
if entry is not None:
    # Sanctioned direct-entry use: priced rerank roll-up + per-stage trace sidecar keyed by
    # this run/step. observe() can't express these — they consume the LedgerEntry itself.
    flush_graph_expand(entry, expansion, rerank_usage=rerank_usage)
    if capture is not None and capture.trace is not None:
        write_trace_sidecar(self._workspace_path, run_id=entry.run_id,
                            step_index=entry.step_index, trace=capture.trace)
```
Everything else in `graph_expand` (input/decision/output previews) goes through `observe`.

---

## 5. New tests this stage adds

### 5.1 `runtime/tests/test_ledger_observe.py` — the facade
Set up a real active entry with `RecordingLedgerSink` (no CSV, no pricing) and assert via
`to_row()`:
```python
sink = RecordingLedgerSink(tmp_path)
entry = sink.open_entry("probe", {}, None)
token = current_entry.set(entry)
try:
    observe(decision=("retrieved", "3"), output="x", usage={"provider": "p", "model": "m", "input_tokens": 10})
    row = entry.to_row()
    assert row["decision_kind"] == "retrieved" and row["decision_detail"] == "3"
finally:
    current_entry.reset(token)
```
- [ ] `observe(...)` with **no** active entry → returns `None`, raises nothing (no-op).
- [ ] `observe(...)` with an entry → sets input/output/decision/usage/skipped/error/fail (assert
      `to_row()` fields, incl. `has_usage`-style usage columns).
- [ ] `decision` accepts both a bare string and a `(kind, detail)` tuple.
- [ ] `fail` dict applies `code` with default `message=""`/`decision="provider_error"` when
      those keys are omitted.
- [ ] `substep_scope()` sets `current_substep` to the entry's `step_index` inside the block and
      resets it after; no-op (and no raise) without an entry; resets even when the body raises.
- [ ] `record_child(...)` spawns one child row under the parent entry with the given fields;
      no-op without an entry. (Mirror the `child_node` pattern already in `test_graph_ledger.py`.)

### 5.2 The characterization assertions are the real test
P3's correctness is proven by the **existing** characterization `RecordingLedgerSink` assertions
— `.nodes()`, `.decisions()`, `.row(...)`, `.has_usage(...)` — still passing **without edits**.
There is no golden file to regenerate: each row is asserted inline, so any drift surfaces as a
failing assertion. **Do not weaken or rewrite those assertions to make P3 pass** — a failure
means a translation error, not a new baseline.

---

## 6. Self-validation gates (run in order)

**Gate A — boilerplate is gone (BOTH guard styles).** No guard blocks, no direct substep/child
calls in nodes. The first grep catches the walrus form **and** the plain `if entry:` guard —
both must be zero (don't grep only the walrus form, or knowledge's ~13 plain guards read green
while still present):
```bash
NODE_FILES="hiroserver/hirocli/src/hirocli/runtime/agent_graph/base.py hiroserver/hirocli/src/hirocli/services/knowledge/agent/graph.py"
# zero matches expected — covers `if entry := current_entry.get():` AND `if entry:`:
grep -rnE "if entry := current_entry\.get\(\)|^[[:space:]]*if entry:" $NODE_FILES
grep -rn "current_substep.set(" $NODE_FILES
grep -rn ".spawn_child(" $NODE_FILES
```

**Gate B — only the sanctioned direct-entry use remains.** The sole `current_entry.get()` in
the two node files is `graph_expand`'s, and it carries the explanatory comment:
```bash
grep -rn "current_entry.get()" hiroserver/hirocli/src/hirocli/runtime/agent_graph/base.py hiroserver/hirocli/src/hirocli/services/knowledge/agent/graph.py
# expect: exactly the graph_expand line(s)
```

**Gate C — import health:**
```bash
python -c "import hirocli.runtime.agent_graph.ledger, hirocli.runtime.agent_graph.base, hirocli.services.knowledge.agent.graph"
```

**Gate D — ⭐ characterization ledger-row assertions pass unchanged (the prime directive).** Run
the characterization suites; the `RecordingLedgerSink` assertions (`.nodes()`, `.decisions()`,
`.row(...)`, `.has_usage(...)`) must pass **without editing them** (there is no golden file —
the rows are asserted inline):
```bash
pytest hiroserver/hirocli/src/hirocli/runtime/tests -k "characterization or ledger or observe"
pytest hiroserver/hirocli/src/hirocli/services/knowledge -k "characterization or ledger"
git diff -- "**/test_*characterization*.py"   # expect: NO assertion edits in these files
```
If a row assertion fails: you merged two blocks into one `observe`, dropped a field, changed a
`max_len`, or reordered `fail` vs `decision`. Find the node, diff against the original block,
fix the translation. **Do not** edit the assertion to match.

**Gate E — full suite green** (no regressions elsewhere): `pytest hiroserver/hirocli`.

---

## 7. Definition of done

- [ ] `observe()`, `substep_scope()`, `record_child()` live in `ledger.py`, exported, all
      no-op without an entry.
- [ ] Every node in §4.1/§4.2 converted; Gate A returns zero matches.
- [ ] The only `current_entry.get()` in node bodies is the sanctioned `graph_expand` block,
      commented (Gate B).
- [ ] `test_ledger_observe.py` added and green.
- [ ] **Characterization ledger-row assertions pass unchanged** (Gate D) — the non-negotiable.
- [ ] No node logic, event emission, or row shape changed.

---

## 8. Gotchas & cues

- **One block → one `observe`.** Never merge two separate guard blocks into a single call;
  field timing/overwrite could shift a row. Keep the same number of write points.
- **Don't touch logic.** If you find yourself "improving" a decision string or a preview while
  converting — stop. P3 is mechanical; behavior changes belong to their own PR.
- **`add_usage` count must match.** A node that called `add_usage` once must `observe(usage=…)`
  once. Multiple usage calls (rare) → multiple `observe(usage=…)` calls in the same order.
- **`graph_expand` is the only exception** — resist "cleaning up" its kept `current_entry`
  read; the flush + sidecar genuinely need the object.
- **Work incrementally.** Convert one node group, run Gate D, commit. A 20-node big-bang makes
  a snapshot diff impossible to localize.
- **Reflecting-build-updates:** internal refactor only — no server restart / workspace reset /
  config change. State this in the PR summary.

---

## 9. TL;DR

- **Decision (resolves the open P3 question):** build the **`observe()` family**
  (`observe` + `substep_scope` + `record_child`) in `ledger.py`, **not** a `NodeResult` return
  — three patterns (pre-`raise` usage, per-tool child loops, substep nesting) can't be a return
  value. Rationale in §1.1.
- **Do:** add the 3 no-op-safe facade fns; mechanically convert ~20 nodes in `base.py` +
  knowledge `graph.py` via the §3 patterns; keep the **one sanctioned** `graph_expand` entry
  use.
- **Refined exit criterion:** zero `if entry := current_entry.get():` guard blocks; zero direct
  `current_substep.set` / `spawn_child` in nodes.
- **Prove it:** Gate A (no boilerplate), Gate B (only `graph_expand` direct use), Gate C (imports),
  **Gate D — characterization `RecordingLedgerSink` assertions pass unchanged** (the prime
  directive; no golden files — rows asserted inline), Gate E (full suite); plus `test_ledger_observe.py`.
- **Stay in lane:** no logic / shape / event changes, no node-group split (that's P4).
