# P6 — Structure the Graph State (typed Sends, sectioning, checkpoint guard)

> **Execution plan (single source) for Stage P6** of
> [`agent-graph-refactor-design.md`](agent-graph-refactor-design.md). Makes the state's
> invariants live in **types and one authoritative docstring** instead of scattered comments —
> *without* breaking LangGraph's channel/reducer semantics.
>
> **Preconditions:** **P1–P4 landed and green** (P5/P7 optional — P6 is independent of them).
> The §5.2 characterization net (events + final state + `RecordingLedgerSink` rows; fakes in
> `runtime/tests/graph_fakes.py`) is the safety rail. **Do not land P6 inside the P4 PR** — both
> are heavy on node bodies/state; keeping them separate keeps any characterization failure
> localizable.
>
> **Mode:** initial development — **no backward compatibility / no wrappers**. No behavior change.
>
> **Status:** _Ready to build._ Resolves the design doc's open "state shape" decision (§1.1) —
> and **reverses its lean** on technical grounds.

---

## 1. The decision that reshapes P6

The design doc leaned toward **nested `TypedDict` slices**. After checking how LangGraph merges
state, **broad nesting is unsafe here** — so P6 keeps the state **flat** and wins on *typing +
documentation + a guard test* instead.

### 1.1 Why nesting is unsafe (verified against the graph's own semantics)

LangGraph merges state **per top-level key (channel)**: a node returning `{"k": v}` reduces the
`k` channel via its declared reducer, and **two branches writing the same non-reducer channel
concurrently raise `InvalidUpdateError`**. The state's own docstring already encodes this:
*"Reducers concatenate parallel branch outputs so two STT items running in parallel cannot race
on the parent dict."* Nesting collides with that two ways:

| Field group | Nestable? | Why |
|---|---|---|
| `messages` (`add_messages`), `transcripts` / `visions` / `errors` (`operator.add`) | ❌ **No** | Reducers are keyed on the **top-level** channel. Nest them and parallel `Send` branches return `{"media": {"transcripts": [...]}}` → default dict-overwrite, **lost transcripts + races**. |
| Parallel-written scratch: `retrieved_memories` (memory_search) vs `knowledge_context`/`knowledge_sources` (knowledge_retrieve) | ❌ **No** | These two nodes run **concurrently** and join at `context_build`. Under one `retrieval` parent they'd both write `retrieval` at once → `InvalidUpdateError`. |
| Write-once inputs (`inbound_id`, `chat_channel_id`, `thread_id`, …) | ⚠️ *Safe but not worth it* | No concurrency, but nesting them rewrites **every** `state.get("inbound_id")` across ~20 nodes for modest gain — disproportionate churn for the riskiest stage. |

**Recorded decision:** keep `GraphState` **flat** (channels intact). Achieve the design's
*intent* — "invariants in code/types, not comments" — via **(P6-A)** explicit typed `Send`
sub-states, **(P6-B)** sectioning + one authoritative checkpoint docstring + type-tightening,
and **(P6-C)** a checkpoint-surface guard test. This makes P6 **smaller and far lower-risk**
than the doc implied.

---

## 2. P6-A — Explicit typed `Send` sub-states

Today the fan-out `Send` payloads are built as ad-hoc dicts in `dispatch_media`, and
`stt_node`/`vision_node` take `sub_state: dict[str, Any]`. The `Send` sub-state is **not** a
checkpointed channel — it's a separate dict LangGraph hands to the fanned-out node — so it is
**safe to give a real type**, and doing so documents *why* `dispatch_media` copies identity
fields into it (the ledger's `_identity_from_state` reads them).

Add to `runtime/agent_graph/state.py` (next to `AudioItem` / `ImageItem`):
```python
class SttSend(TypedDict):
    """Sub-state for one parallel STT branch (carried on langgraph.types.Send).

    NOT a checkpoint channel — a per-branch payload. Identity fields are copied in so the
    ledger (``_identity_from_state``) can attribute the branch row to the turn.
    """
    audio_item: AudioItem
    inbound_id: str
    chat_channel_id: int
    character_id: str
    routing_metadata: dict[str, Any]


class VisionSend(TypedDict):
    """Sub-state for one parallel vision branch (see SttSend)."""
    image_item: ImageItem
    inbound_id: str
    chat_channel_id: int
    character_id: str
    routing_metadata: dict[str, Any]
```

- [ ] `MediaNodes.dispatch_media`: build `SttSend(...)` / `VisionSend(...)` instead of raw dicts.
- [ ] `MediaNodes.stt_node(self, sub_state: SttSend, writer)` and
      `vision_node(self, sub_state: VisionSend, writer)` — type the param (bodies unchanged;
      `SttSend` is a `dict` at runtime, so `sub_state["audio_item"]` / `.get(...)` still work).

---

## 3. P6-B — Section + document `GraphState`, tighten types

Keep all keys top-level; reorganize for legibility and pull the scattered invariant comments
into **one** class docstring.

- [ ] **One authoritative docstring** on `GraphState` stating the three invariants that are
      currently smeared across field comments:
      1. **Checkpoint surface = `messages` only.** Every other field is per-turn scratch,
         overwritten each turn; its cross-turn value is undefined.
      2. **Reducer fields (`messages`, `transcripts`, `visions`, `errors`) must stay top-level**
         — LangGraph keys reducers on channels; never nest them (see this doc §1.1).
      3. **Bytes never enter the checkpoint** — audio/image bodies ride `Send` sub-states only;
         `gather_node` clears `audio_items`/`image_items`.
- [ ] **Section the fields** with comment headers (no nesting): `# --- Inputs (write-once) ---`,
      `# --- Fan-out scratch (reducer-merged) ---`, `# --- Retrieval scratch (parallel) ---`,
      `# --- Reply / voice ---`, `# --- Bookkeeping ---`. Move the per-field rationale comments
      that duplicate the docstring; keep only field-specific notes.
- [ ] **Tighten `Any` where a concrete type exists** (typing intent without nesting):
      - `knowledge_sources: list[Any]` → `list[KnowledgeSource]`.
        ⚠️ **Use a RUNTIME import, NOT `TYPE_CHECKING`.** `GraphState` is a LangGraph `StateGraph`
        schema; LangGraph calls `get_type_hints()` on it at build time, which **evaluates** the
        annotation — so `KnowledgeSource` must resolve at runtime *even with*
        `from __future__ import annotations`. A `TYPE_CHECKING`-only import → `NameError` at
        `build()` time. (Verified: the chat runtime importing `services.knowledge.models` is a
        lightweight data-model import, no cycle.) Add a one-line comment saying why it's runtime.
      - leave `retrieved_memories: list[dict[str, Any]]` (Graphiti hits are dicts),
        `routing_metadata` / `inbound_envelope: dict[str, Any]` as-is (genuinely open shapes).
- [ ] Confirm the reducer annotations are **unchanged** (`Annotated[..., operator.add]`,
      `Annotated[list[BaseMessage], add_messages]`).

---

## 4. P6-C — Light same treatment for `KnowledgeAgentState`

`KnowledgeAgentState` (35 fields) has **no reducers and no `Send` fan-out** (the knowledge graph
is linear), so it has no channel constraints — but it's still a grab-bag.

- [ ] Section it with comment headers grouping the **legs** clearly: `# --- Query in ---`,
      `# --- Rewrite output ---`, `# --- Graph leg (graphiti) ---`, `# --- Vector leg ---`,
      `# --- Assembly / answer ---`, `# --- Identity / bookkeeping ---`.
- [ ] Add a class docstring noting it is **all per-invoke scratch** (the knowledge graph compiles
      **without a checkpointer** — `build_retrieval()`), so no cross-call persistence to reason
      about.
- [ ] Tighten obvious `Any`s where a type exists (`sources: list[Any]` → `list[KnowledgeSource]`,
      `hits: list[Any]` → `list[KnowledgeSearchHit]`); leave genuinely-dynamic ones
      (`qdrant_filter`, `query_vector`) alone. **Do not** restructure the leg routing — that's P8.
      ⚠️ **Same rule as §3 — RUNTIME import, not `TYPE_CHECKING`:** `KnowledgeAgentState` is also a
      `StateGraph` schema, so `get_type_hints()` evaluates these names at `build()`/`build_retrieval()`
      time. (Same-package here, so no layering concern either way.)

---

## 5. Tests this stage adds

### 5.1 `runtime/tests/test_graph_state_contract.py`
- [ ] **Checkpoint-surface guard** (the headline test). Compile the chat graph with an
      `InMemorySaver`, run two turns on the **same `thread_id`**, and assert via
      `compiled.get_state(config).values`:
      - `messages` accumulates across turns (durable); turn 2 sees turn 1's history.
      - after an **audio** turn, `audio_items == []` and `image_items == []` in the persisted
        state (the bytes-never-in-checkpoint invariant — `gather_node` cleared them).
      - per-turn scratch reflects **only the current turn** (turn 2's `user_text` is turn 2's
        text, not carried from turn 1).
- [ ] **`Send` sub-state shape:** `dispatch_media` over an audio+image envelope returns `Send`s
      whose `.arg` matches `SttSend` / `VisionSend` keys (and carries the identity fields the
      ledger needs).
- [ ] **Reducer integrity:** two `{"transcripts": [t]}` partials reduce by concatenation
      (guards against an accidental nesting/annotation regression).

### 5.2 Characterization net unchanged
Sectioning + typing changes no runtime behavior; events + final-state + `RecordingLedgerSink`
row assertions stay byte-stable. Type-only edits must not alter any decision/row.

---

## 6. Self-validation gates

**Gate A — reducer channels stayed top-level (no accidental nesting):**
```bash
grep -nE "transcripts:|visions:|errors:|messages:" hiroserver/hirocli/src/hirocli/runtime/agent_graph/state.py
# expect: each still a top-level Annotated[...] field with its reducer
```

**Gate B — Sends are typed:**
```bash
grep -n "SttSend\|VisionSend" hiroserver/hirocli/src/hirocli/runtime/agent_graph/state.py \
  hiroserver/hirocli/src/hirocli/runtime/agent_graph/nodes/media.py
# expect: defined in state.py; used in dispatch_media + stt_node/vision_node signatures
```

**Gate C — import health / no cycle** (TYPE_CHECKING imports must not become runtime cycles):
```bash
python -c "import hirocli.runtime.agent_graph.state, hirocli.runtime.agent_graph.nodes.media, hirocli.services.knowledge.agent.graph"
```

**Gate D — ⭐ characterization net + new contract test green:**
```bash
pytest hiroserver/hirocli/src/hirocli/runtime/tests -k "characterization or ledger or graph_state_contract or media_nodes"
pytest hiroserver/hirocli/src/hirocli/services/knowledge -k "characterization or ledger"
git diff -- "**/test_*characterization*.py"   # expect: NO assertion edits
```

**Gate E — type check + lint** (this stage's value is types — run them): `ruff check`, and the
project type checker if configured (e.g. `mypy`/`pyright`) on `state.py` + the media nodes.

---

## 7. Definition of done

- [ ] `SttSend` / `VisionSend` defined in `state.py`, used in `dispatch_media` +
      `stt_node`/`vision_node` (P6-A).
- [ ] `GraphState` has one authoritative invariant docstring, sectioned fields, and tightened
      types — **still flat, reducers intact** (P6-B).
- [ ] `KnowledgeAgentState` sectioned + documented as per-invoke scratch; obvious `Any`s tightened
      (P6-C).
- [ ] `test_graph_state_contract.py` added (checkpoint-surface + Send shape + reducer integrity).
- [ ] Characterization net unchanged (Gate D); type-check + lint green (Gate E).
- [ ] **No field nested under a non-reducer parent; no behavior change.**

---

## 8. Gotchas & cues

- **Never nest a reducer field or a parallel-written field** (§1.1). If you "group" `transcripts`
  or `retrieved_memories` under a parent dict, parallel branches silently lose data or raise
  `InvalidUpdateError`. The reducer annotations must remain on top-level keys.
- **`Send` sub-states are not checkpoint channels** — typing them is free and safe; that's the
  one real structural win here.
- **Type-tighten only where a concrete type exists.** `routing_metadata`, `inbound_envelope`,
  `qdrant_filter`, `query_vector` are genuinely open — leave them `Any`. Don't invent types.
- **RUNTIME imports** for `KnowledgeSource`/`KnowledgeSearchHit` — **NOT `TYPE_CHECKING`**.
  These names appear in the `GraphState` / `KnowledgeAgentState` annotations, and LangGraph
  introspects those schemas via `get_type_hints()` at graph-build time, **evaluating** the
  (otherwise-lazy) annotations. A `TYPE_CHECKING`-only import raises `NameError` when the graph
  compiles. Import them at module top with a one-line comment explaining why it must be runtime.
  (This corrects an earlier draft of this plan that said `TYPE_CHECKING`.)
- **The checkpoint test needs a checkpointer** — use `langgraph.checkpoint.memory.InMemorySaver`
  and pass `config={"configurable": {"thread_id": "t1"}}`; read back with `get_state`.
- **Don't touch knowledge leg routing** — that's P8. P6 only sections/types `KnowledgeAgentState`.
- **Move/annotate, don't improve.** No logic changes; behavior changes are a separate PR.
- **Reflecting-build-updates:** internal refactor — no server restart / workspace reset / config
  change. Note it in the PR summary.

---

## 9. TL;DR

- **Decision (reverses the design doc's lean):** keep `GraphState` **flat** — LangGraph keys
  reducers on top-level channels and rejects concurrent non-reducer writes, so nesting the
  reducer fields (`messages`/`transcripts`/`visions`/`errors`) or the parallel-written scratch
  (`retrieved_memories` vs `knowledge_*`) would **lose data / raise**. Nesting write-once inputs
  is safe but not worth the ~20-node churn.
- **Do instead:** (A) explicit typed `Send` sub-states `SttSend`/`VisionSend` (the one safe
  structural win); (B) section `GraphState` + one authoritative checkpoint/invariant docstring +
  tighten `Any`→concrete where a type exists; (C) light sectioning/typing of
  `KnowledgeAgentState`.
- **Prove it:** Gate A (reducers still top-level), Gate B (Sends typed), Gate C (no cycle),
  **Gate D (characterization unchanged)**, Gate E (type-check + lint); plus
  `test_graph_state_contract.py` — the checkpoint-surface guard, Send shape, and reducer
  integrity.
- **Net:** P6 is **smaller and lower-risk** than feared — typing + docs + a guard test, no
  channel restructuring, no behavior change. Leg restructuring stays in **P8**.
