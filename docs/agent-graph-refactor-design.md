# Agent Graph Refactor — Composition, Cohesion, and a Test Spine

> **Tracker doc (single source).** Design + staged plan to refactor the two LangGraph
> graph classes — the live chat agent (`ChatAgentGraph`) and the knowledge RAG graph
> (`KnowledgeAgentGraph`) — off a 1,734-line god base class and onto a **composition**
> model, while **growing a test spine that keeps each stage provably solid**. The central
> rule of this plan: *no structural change lands without a test that pins the behavior it
> touches* — characterization tests first, finer-grained tests added at each new seam.
>
> **Companions:** [`context-assembly.md`](context-assembly.md) (the already-clean block
> assembler this refactor uses as its template), [`langgraph_tips.md`](langgraph_tips.md).
>
> **Mode:** initial development — **no backward compatibility / no migration / no wrappers**
> (repo rule, explicitly abided). We delete the old base inheritance outright rather than
> shimming it.
>
> **Status:** _Proposed._ No code yet. Stages P1–P3 are the first slice (highest leverage,
> contained blast radius); P4–P8 follow.

---

## 1. The one-paragraph version

Two graphs share one base. `ChatAgentGraph` legitimately uses every node on
`BaseAgentGraph`; `KnowledgeAgentGraph` **inherits the same base but `is-a` nothing** of it
— it nulls every injected service, uses none of the inherited nodes, and reaches into the
base's `_private` helpers via aliased imports. The base is therefore a **god object** (DI
container + ~15 nodes + ~40 helpers + two node styles), the `build()` contract is fictional
(each subclass diverges from its signature), and **ledger bookkeeping is hand-poked inside
every node** (~60 `if entry := current_entry.get(): …` sites, ~40% of each node body). The
fix is to **replace inheritance-as-code-sharing with composition**: an injected
`AgentServices` container, cohesive node groups, a shared public `graph_kit` for helpers, and
a **declarative ledger** so nodes stop poking ContextVars. Because the graph's *observable*
contract (events emitted, final state, ledger rows) is well-defined, we can wrap it in
**characterization tests first** and refactor underneath them with confidence.

---

## 2. Current design — top down

### 2.1 Layering

```mermaid
flowchart TB
    subgraph CONSUMERS
        AM["AgentManager<br/>builds ChatAgentGraph per character/model<br/>nests knowledge retrieval subgraph"]
        CLI["CLI / HTTP / Ask / Eval<br/>builds full knowledge answer graph"]
    end

    subgraph GRAPHS
        CHAT["ChatAgentGraph<br/>agent_graph/chat.py<br/>build() wires chat flow"]
        KNOW["KnowledgeAgentGraph<br/>services/knowledge/agent/graph.py<br/>build() + build_retrieval()"]
        BASE["BaseAgentGraph<br/>agent_graph/base.py — 1,734 lines<br/>DI container · ~15 nodes · ~40 helpers · auto-wrap"]
    end

    subgraph SUBSTRATE["Cross-cutting substrate (agent_graph/*)"]
        STATE["state.py — GraphState + Send sub-state types"]
        LEDGER["ledger.py — 40 KB<br/>ContextVar instrumentation · @graph_logged · LedgerSink · CSV cost"]
        EVENTS["events.py — GRAPH_* domain events → StreamWriter"]
        CTX["context_assembly.py — ContextBlock + ContextAssembler (clean)"]
        TRACE["tracing.py — LangSmith spans tied to ledger run-id"]
    end

    AM --> CHAT
    CLI --> KNOW
    CHAT -->|inherits| BASE
    KNOW -->|inherits| BASE
    AM -.nests.-> KNOW
    BASE --> STATE
    BASE --> LEDGER
    BASE --> EVENTS
    BASE --> CTX
    BASE --> TRACE
```

### 2.2 Class design — and the inheritance problem

```mermaid
classDiagram
    class BaseAgentGraph {
        +stt, vision, tts, memory, creds
        +checkpointer, prefs, knowledge_subgraph
        +set_*_service() live swaps
        +build(model, tools, model_id, system_prompt)* abstract
        +ingest/stt/vision/gather/input_gate nodes
        +memory_search/knowledge_retrieve/memory_out nodes
        +make_call_model_node()/make_tools_node() closures
        +~40 module _helpers
    }
    class ChatAgentGraph {
        +build(... +temperature +max_tokens +thinking)
        uses ALL base nodes
    }
    class KnowledgeAgentGraph {
        +__init__(... passes EVERY service = None)
        +build(model=None, tools=None) ignores them
        +build_retrieval()
        uses NONE of base nodes
        imports base._private helpers via alias
        defines own KnowledgeAgentState + node set
    }
    BaseAgentGraph <|-- ChatAgentGraph
    BaseAgentGraph <|-- KnowledgeAgentGraph
    note for KnowledgeAgentGraph "Liskov violation:<br/>inherits Base only to borrow<br/>_emit / _ledger_sink / helpers"
```

`ChatAgentGraph` is an honest subclass. `KnowledgeAgentGraph` is the smell: it extends the
base purely as a *utility namespace*, then has to (a) pass `None` for stt/vision/tts/memory/
creds/checkpointer, (b) import `_estimate_text_tokens as estimate_text_tokens` and friends,
and (c) accept a `build()` signature whose `model`/`tools` it discards.

### 2.3 ChatAgentGraph — per-message flow

```mermaid
flowchart TB
    START([START]) --> ingest
    ingest -->|dispatch_media<br/>Send fan-out| stt["stt (per audio item)"]
    ingest -->|Send fan-out| vision["vision (per image item)"]
    ingest -->|no media| gather
    stt --> gather
    vision --> gather
    gather -->|input_gate: no user_text| media_failed
    gather -->|input_gate: has user_text| trim_history
    trim_history -->|knowledge_fanout| memory_search
    trim_history -->|toggle on| knowledge_retrieve["knowledge_retrieve<br/>(nested subgraph)"]
    memory_search --> context_build
    knowledge_retrieve --> context_build
    context_build --> compose_context["compose_context<br/>(turn_context, ephemeral)"]
    compose_context --> call_model
    call_model -->|should_continue: tool_calls| tools
    tools --> call_model
    call_model -->|should_continue: done| memory_out["memory_out<br/>(store user turn)"]
    memory_out -->|tts_gate| tts
    memory_out -->|tts_gate| finalize
    media_failed -->|tts_gate| tts
    media_failed -->|tts_gate| finalize
    tts --> finalize
    finalize --> END([END])
```

**Invariants worth preserving (the genuinely good parts):**

- **Bytes never enter the checkpoint** — audio/image bodies ride `langgraph.types.Send`
  sub-states; only transcripts/descriptions merge back via reducers. `gather` clears the
  byte fields.
- **`turn_context` is ephemeral** — memory + knowledge + citation are rendered once into
  `turn_context` and injected into the *current user turn* at `call_model`; they never enter
  durable `messages`, so persona stays a stable, cache-friendly system message.
- **Trim once, then fan out** — memory and knowledge read the identical trimmed window.
- **Degrade, never crash** — every external call (STT/vision/memory/LLM/TTS/knowledge) has a
  logged fallback path.

### 2.4 KnowledgeAgentGraph — retrieval legs

```mermaid
flowchart TB
    START([START]) --> parse_query --> rewrite_query
    rewrite_query -->|route_after_rewrite: knowledge_needed=false| build_context
    rewrite_query -->|retrieve| graph_expand
    graph_expand -->|route_after_expand: graphiti + chunk_ids| graph_fetch
    graph_expand -->|vector / soft-fallback| build_filters
    graph_fetch --> build_context
    build_filters --> embed_query --> vector_search --> rerank --> build_context
    build_context -->|route_after_context: no_results| finalize
    build_context -->|has results| call_model
    call_model --> finalize --> END([END])

    subgraph RETRIEVAL_ONLY["build_retrieval() form (nested in chat)"]
        direction LR
        note1["same prefix … → build_context → END<br/>(no call_model / finalize)"]
    end
```

Two compiled forms from one node set: `build()` (full Ask/CLI/HTTP answer) and
`build_retrieval()` (retrieval-only subgraph, nested per chat turn so its `knowledge/*` rows
fold into the chat run's ledger). The `graph_mode` legs (`off` flat vs `graphiti`) are
encoded across five nodes via the `route_after_*` static methods.

### 2.5 The ledger — a dual instrumentation mechanism

The reason nodes are large. Each node is wrapped *declaratively* by the framework **and**
pokes the ledger *imperatively* from inside its own body.

```mermaid
sequenceDiagram
    participant LG as LangGraph
    participant W as wrap_graph_node (auto)
    participant N as node body
    participant CV as current_entry (ContextVar)
    participant SINK as LedgerSink (CSV)

    LG->>W: invoke(state)
    W->>SINK: open_entry(node, state)
    W->>CV: set(entry)
    W->>N: fn(state, writer)
    Note over N,CV: node body calls current_entry.get()<br/>~60× across the two graphs
    N->>CV: entry.set_input_preview(...)
    N->>CV: entry.set_decision(...)
    N->>CV: entry.add_usage(...)
    N->>CV: entry.set_output_preview(...)
    N-->>W: return state_update
    W->>SINK: write_rows(entry.rows())
    W->>CV: reset(token)
```

The wrapper already owns row open/close/write. The in-body `if entry := current_entry.get():`
blocks are pure boilerplate that bloats every node — the single biggest readability tax and
the thing P3 removes.

---

## 3. Problems (the refactor targets)

| # | Problem | Evidence | Impact |
|---|---------|----------|--------|
| 1 | `BaseAgentGraph` god object | 1,734 LOC: DI + ~15 nodes + ~40 helpers | navigate/test/extend cost |
| 2 | `KnowledgeAgentGraph` inherits a base it isn't | nulls all services; aliased `_private` imports | Liskov violation, fragile |
| 3 | Fictional `build()` contract | Chat *adds* tuning args; Knowledge *ignores* model/tools | leaky abstraction |
| 4 | Imperative ledger inside nodes | ~60 `if entry := …get()` sites | ~40% boilerplate per node |
| 5 | Two node styles | bound-method nodes vs `make_*_node` closures | inconsistent, two wrap paths |
| 6 | Mega-nodes | `tts_node` ~160 LOC, `call_model` ~90, `graph_expand` ~120 | low cohesion, hard to test |
| 7 | Monolithic state | `GraphState` 30 fields, `KnowledgeAgentState` 35; invariants in comments | silent-drop bugs |
| 8 | Scattered access | inline imports + per-method `try/except` prefs accessors | duplication |

---

## 4. Target architecture — composition

```mermaid
flowchart TB
    SVC["AgentServices (frozen dataclass / DI)<br/>stt · vision · tts · memory · creds · prefs<br/>checkpointer · ledger_sink · knowledge_subgraph"]

    subgraph NODEGROUPS["Cohesive node groups (small classes over AgentServices)"]
        MEDIA["MediaNodes<br/>ingest · stt · vision · gather · input_gate · media_failed"]
        CONV["ConversationNodes<br/>trim · memory_search · memory_out · compose_context · call_model · tools"]
        KN["KnowledgeNodes<br/>parse · rewrite · expand · fetch · embed · search · rerank · build_context · answer"]
    end

    subgraph BUILDERS
        CB["chat builder (chat.py)"]
        KB["knowledge builder (knowledge graph.py)"]
    end

    KIT["graph_kit (public, was base._helpers)<br/>normalize_content · usage_payload · trim_history<br/>preview formatters · emit() · observe()"]

    SVC --> MEDIA
    SVC --> CONV
    SVC --> KN
    MEDIA --> CB
    CONV --> CB
    KN --> KB
    KN -.retrieval-only.-> CB
    MEDIA --> KIT
    CONV --> KIT
    KN --> KIT
```

Key shifts vs today: **no shared base class**; services are *injected data*, not inherited
attributes; helpers are *public and shared*, not `_private` and aliased; nodes are *grouped
by domain* and *uniform in style*; the ledger is a `graph_kit.observe(...)` call that no-ops
without an entry, not a hand-rolled guard block.

---

## 5. The test spine (the heart of this plan)

The refactor is only as safe as the net under it. We build that net **before** moving code,
then thicken it at each new seam.

### 5.1 Test pyramid

```mermaid
flowchart TB
    E2E["Characterization / golden — FEW, built FIRST<br/>compile graph w/ fakes → invoke canned inbound →<br/>assert event sequence + final state + ledger rows.<br/>Internals-agnostic = the safety net; survives every stage."]
    WIRE["Builder / wiring tests — graph topology<br/>nodes present · edges · conditional routes (input_gate, route_after_*)"]
    NODE["Node-group unit tests — MANY<br/>each node over fake AgentServices; one behavior per test"]
    PURE["Pure helper + observe() contract tests — MOST, fastest<br/>graph_kit functions; ledger row shape from observe()"]

    E2E --> WIRE --> NODE --> PURE
```

### 5.2 Characterization first — lock behavior before touching it

Before P1, add `test_chat_graph_characterization.py` and
`test_knowledge_graph_characterization.py` that treat each graph as a black box:

- **Fakes, not mocks of internals.** Build a `conftest` with `FakeSTT`, `FakeVision`,
  `FakeTTS`, `FakeMemory`, `FakeKnowledgeSubgraph`, and a `FakeChatModel`
  (`langchain_core.language_models.fake_chat_models.FakeMessagesListChatModel` returning a
  canned `AIMessage`, including a tool-call turn for the loop). These already align with the
  existing pattern of constructing graphs with `None`/stub services
  (`test_agent_graph_input_gate.py`, `test_graph_ledger.py`).
- **Assert the observable contract**, not the call sequence:
  1. **Events** — the ordered `GRAPH_*` list captured via the `_collect_events()` writer
     stub (already an established pattern).
  2. **Final state** — `reply_text`, `reply_id`, `messages` cleanliness (no `turn_context`
     leaked into history), `audio_items`/`image_items` cleared.
  3. **Ledger rows** — snapshot the CSV rows the run writes (node names, `decision_kind`,
     usage columns) via a temp `LedgerSink`. This is the contract P3 must preserve exactly.
- **Cover the branches that matter:** text-only turn; audio+STT-success; audio-only+STT-fail
  (→ `media_failed`); tool loop (one round); knowledge toggle on/off; knowledge flat leg vs
  graphiti leg; `no_results` → `finalize`.

These tests **do not change** as we refactor internals — a diff that turns them red is a
regression, full stop.

### 5.3 Per-stage test evolution

Each stage ships its own tests *and* must leave §5.2 green.

| Stage | What changes | Tests added this stage | Exit criteria |
|-------|--------------|------------------------|---------------|
| **P1** Extract `graph_kit`, kill knowledge→base inheritance | move ~40 helpers public; `KnowledgeAgentGraph` stops extending `BaseAgentGraph` | pure-fn unit tests for every moved helper; an **import-boundary test** asserting `services/knowledge/**` no longer imports `runtime.agent_graph.base` private names | characterization green; no `_private` cross-imports remain |
| **P2** Per-graph config objects | `ChatGraphConfig` / `KnowledgeGraphConfig` replace fictional `build()` | builder tests: config in → compiled graph with expected nodes; type tests for the configs | both graphs compile from configs; old `build()` signature gone |
| **P3** Declarative ledger (`observe()` / `NodeResult`) | remove in-body `current_entry` pokes | **ledger-row snapshot** tests assert rows identical before/after for each characterization scenario; `observe()` no-op test (no entry → silent) | row snapshots byte-stable; nodes contain zero `current_entry.get()` |
| **P4** Split god class into node groups | `MediaNodes`/`ConversationNodes`/`KnowledgeNodes`; one node style | node-group unit tests per node (the big coverage jump); wiring tests assert builders compose groups | each node unit-tested in isolation over fakes |
| **P5** Slim mega-nodes | extract `resolve_voice→synthesize→meter`; `graphiti_session()` CM | unit tests for extracted helpers incl. the CM's open/close + ContextVar reset on error | `tts_node`/`graph_expand` are orchestration-only |
| **P6** Structure state | sectioned/nested `GraphState`; explicit `Send` sub-state type | typed-state tests; a **checkpoint-surface test** asserting only `messages` survives a thread round-trip | invariants in code/types, not comments |
| **P7** Centralized prefs accessor | one typed accessor + single fallback policy | accessor unit tests (present / absent / malformed prefs → documented fallback) | per-method `try/except` removed |
| **P8** First-class knowledge legs | flat vs graphiti as named sub-pipelines / stage spec | leg-routing tests; per-leg retrieval tests | `graph_mode` branching localized |

### 5.4 What the refactor *buys* testing

Today, unit-testing a node means constructing the whole graph object and threading the
`current_entry` ContextVar; the eager-import fragility in the agent package
(`reference_agent-package-test-placement.md`) is a symptom. After P3–P4, a node is a small
callable over a `FakeAgentServices` with a `NodeResult` return — **pure-ish, ContextVar-free,
trivially unit-testable**. Coverage is expected to climb most at P4 precisely because the
seams finally exist.

### 5.5 Running + gating

- **Local:** `pytest hiroserver/hirocli/src/hirocli/runtime/tests -k "agent_graph or ledger"`
  and `pytest hiroserver/hirocli/src/hirocli/services/knowledge -k "agent or retriev or rerank or rewrite"`.
- **Placement rule (must-honor):** knowledge graph tests go in the **parent**
  `services/knowledge/` dir, **never** inside `services/knowledge/agent/` — a collected test
  there corrupts `agent.graph` for later monkeypatch tests (full-suite-only failure). See
  `reference_agent-package-test-placement.md`.
- **Gate:** characterization + ledger-snapshot suites are the merge gate for every stage.

---

## 6. Sequencing & risk

```mermaid
flowchart LR
    C["§5.2 Characterization net"] --> P1 --> P2 --> P3
    P3 --> P4 --> P5
    P4 --> P6
    P3 --> P7
    P4 --> P8
    P1 -.lowest risk.-> P1
    P3 -.highest obs. risk → snapshot gate.-> P3
```

- **First slice = P1 → P2 → P3.** Most of the readability/testability win, contained blast
  radius, and it stands on the characterization net.
- **Highest-risk stage = P3** (it touches the cost/observability ledger every node feeds).
  Mitigation: the byte-stable ledger-row snapshot gate in §5.3.
- **No-backward-compat:** P1 *deletes* the knowledge→base inheritance and the old `build()`
  rather than shimming. Expected breakage is compile-time and caught immediately by the
  builder/characterization suites.
- **Rollback:** each stage is an independent PR behind the same green gate; revert is one PR.

---

## 7. Open decisions

- **P3 shape:** thin `observe(decision=…, input=…, output=…, usage=…)` helper (smaller diff,
  nodes still call it) **vs** a `NodeResult` return that the wrapper unwraps (purer nodes,
  larger diff). _Leaning `NodeResult`_ for the testability win, but `observe()` is a valid
  cheaper first step. **Needs a call before P3.**
- **Node style (P4):** parametrized node **classes** with `__call__` vs keeping factory
  closures. _Leaning classes_ for a single uniform wrap path.
- **State (P6):** nested `TypedDict` slices vs a documented flat layout with one
  checkpoint-surface docstring. _Leaning nested slices._

---

## 8. TL;DR

- **Goal:** move both graphs off the 1,734-line `BaseAgentGraph` god class onto
  **composition** — injected `AgentServices`, cohesive node groups, a shared public
  `graph_kit`, and a **declarative ledger** — without regressing the observable contract.
- **Why now:** `KnowledgeAgentGraph` inherits a base it `is-a` nothing of (nulls every
  service, imports `_private` helpers), `build()` is fictional, and ~60 in-body ledger pokes
  bloat every node.
- **Test spine (the ask):** **characterization/golden tests first** (events + final state +
  ledger-row snapshots, internals-agnostic), then **per-stage tests at each new seam** —
  pure-fn tests at P1, builder tests at P2, **byte-stable ledger snapshots at P3**, the big
  node-group unit-test jump at P4, and so on. Every stage must leave the characterization net
  green; that net is the merge gate.
- **Sequencing:** **P1 → P2 → P3** first (best leverage, lowest risk); P3 is the
  highest observability risk and is gated by ledger snapshots. P4–P8 follow.
- **Honor:** the knowledge **test-placement rule** (tests in `services/knowledge/`, not
  `…/agent/`) and **no-backward-compat** (delete, don't shim).
- **Open calls before P3/P4:** `observe()` vs `NodeResult`; node classes vs closures; nested
  vs flat state.
- **Status:** _Proposed_ — written, no code yet. Say the word and I'll start P1 with its
  characterization net in the same PR.
