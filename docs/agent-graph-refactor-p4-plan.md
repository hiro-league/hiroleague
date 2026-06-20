# P4 — Decompose the God Class into Node Groups over `AgentServices`

> **Execution plan (single source) for Stage P4** of
> [`agent-graph-refactor-design.md`](agent-graph-refactor-design.md), following
> [`P1`](agent-graph-refactor-p1-plan.md), [`P2`](agent-graph-refactor-p2-plan.md),
> [`P3`](agent-graph-refactor-p3-plan.md). This is the **largest** stage — a structural rewrite,
> not a mechanical translation. It is split into **6 independently-green sub-stages** so a
> junior can land it incrementally with the characterization net catching every step.
>
> **Preconditions:** **P1–P3 landed and green.** The §5.2 characterization net (events + final
> state + `RecordingLedgerSink` row assertions, fakes in `runtime/tests/graph_fakes.py`) is the
> safety rail for *every* sub-stage. After P3, node bodies are already declarative (`observe()`),
> which makes them safe to relocate.
>
> **Mode:** initial development — **no backward compatibility / no wrappers**. `BaseAgentGraph`
> is **deleted**, not shimmed.
>
> **Status:** _Ready to build, sub-stage by sub-stage._
>
> **Post-P1/P2/P3 reconciliation (read first — verified against the landed tree):**
> - **`base.py` is NOT "empty of nodes" once nodes move — it still holds 20 module-level helper
>   functions** the nodes call (e.g. `_llm_decision`, `_trim_chat_history`, `_format_history`,
>   `_memory_results_preview`, `_memory_text`, `_last_human_message_preview`, `_tool_*` (7),
>   `_audio_item_preview`, `_image_item_preview`, `_serialize_knowledge_sources`, `_error_slug`,
>   plus the wrap helpers `_is_graph_node_method`/`_node_label`). **"Delete `base.py`" (P4.5)
>   requires relocating all 20 first** (now an explicit P4.5 step): wrap helpers →
>   `node_group.py`; media-only (`_audio_item_preview`/`_image_item_preview`) → `nodes/media.py`;
>   the rest → `nodes/conversation.py`, with any used by **both** groups (notably `_error_slug`)
>   in a small `nodes/_helpers.py`. Move each helper with the node(s) that use it.
> - **The Gate-A `BaseAgentGraph` sweep must reach 4 spots P4.5 originally missed** (all verified):
>   `test_agent_manager.py` (constructs `BaseAgentGraph(...)` ×2 **and** imports `_trim_chat_history`
>   — repoint to its new home), `test_agent_manager_stt_reload.py` (`mgr._graph = BaseAgentGraph(...)`),
>   `test_knowledge_graph_decoupled.py` (the P1 guard — see next), and the **`graph_kit.py`
>   docstring** which names `BaseAgentGraph` (scrub it, or Gate A's grep reads non-zero).
> - **`test_knowledge_graph_decoupled.py` (added in P1) goes moot/inverted.** Its
>   `assert not issubclass(KnowledgeAgentGraph, BaseAgentGraph)` can't survive base's deletion, and
>   P4.6 makes Knowledge inherit `NodeGroup`. **Decision:** if P4.6 is done → repoint to
>   `assert issubclass(KnowledgeAgentGraph, NodeGroup)` (keep its "imports no `agent_graph.base`"
>   check); if P4.6 is skipped → delete the file (its premise is satisfied once the god class is gone).
> - **Still accurate (re-verified):** the 3 `make_*_node` closures, `__init_subclass__`, `_emit`,
>   the four prefs accessors, AgentManager's construction (`self._graph = ChatAgentGraph(` ≈line 194,
>   `self._graph: BaseAgentGraph | None` ≈line 139), and the **5** `retry=` sites in `chat.py`
>   (`stt`, `vision`, `memory_search`, `memory_out`, `tts` — Gate C target). `emit` is from **P1**
>   (graph_kit), not P3.

---

## 1. Goal & scope

**Goal.** Replace inheritance-as-code-sharing with **composition**: an injected `AgentServices`
container, cohesive node-group classes, a single uniform node style, and a thin builder. After
P4 there is no 1,700-line god class.

**Outcomes:**
1. `AgentServices` — one injected container for stt/vision/tts/memory/creds/prefs/checkpointer/
   ledger_sink/knowledge_subgraph (replaces the 8 constructor kwargs + scattered `self._*`).
2. `NodeGroup` base — owns the ledger plumbing (`__init_subclass__` auto-wrap, `_ledger_sink`,
   shared prefs accessors). Moved up out of `BaseAgentGraph`.
3. `MediaNodes` + `ConversationNodes` — cohesive groups; **all** nodes are `*_node` methods
   (the three `make_*_node` closures are eliminated).
4. `ChatAgentGraph` becomes a standalone **builder** composing the groups; `BaseAgentGraph` is
   deleted. The `retry=`→`retry_policy=` deprecation is fixed here.
5. Each node is unit-testable in isolation over fake `AgentServices` — the big coverage jump.

**In scope:** the chat graph (`base.py`/`chat.py`) decomposition + AgentManager wiring + test
migration. **Out of scope:** state restructuring (P6), the centralized prefs accessor (P7 — P4
just *moves* the existing accessors), new behavior of any kind.

### 1.1 Scope decision: knowledge grouping is the optional last sub-stage

`KnowledgeAgentGraph` is already a cohesive standalone class after P1. Folding it onto
`NodeGroup` (to drop its P1-era `_wrap_dynamic_node`/`_emit`/`_ledger_sink` boilerplate) is a
small, low-risk cleanup — included as **P4.6 (optional)**, not part of the core chat
decomposition. Stop after P4.5 if time-boxed.

---

## 2. Three decisions that prevent the obvious mistakes

| # | Decision | Why (the trap it avoids) |
|---|---|---|
| **D1** | **Nodes stay `*_node` methods** on group classes; `NodeGroup.__init_subclass__` auto-wraps them exactly as `BaseAgentGraph` does today. **No `ledger.py` changes** on the chat path. | The ledger wrap machinery is intricate; rebuilding it risks the row contract. Reuse it verbatim — only the *owning class* moves. |
| **D2** | The model-bound group (`ConversationNodes`) is **constructed per `build(config)`**, capturing `model`/`tools`/tuning in `__init__`. The stateless intake group (`MediaNodes`) is constructed from `services`. | This is **why the `make_*_node` closures exist** — per-build capture. A method reading a shared `self._model` would be **overwritten by the next build** and corrupt cached compiled graphs. Constructor-capture per build = same isolation the closures gave, in uniform style. |
| **D3** | `AgentServices` is a **mutable** dataclass; live preference swaps mutate it **in place** (`services.stt = new`), and node groups read `self.services.*` per call. | The preference reactors hot-swap STT/TTS/memory/knowledge at runtime. Nodes already read services per call; a shared mutable container preserves that with zero recompile. |

---

## 3. Target module layout

```mermaid
flowchart TB
    AM["AgentManager<br/>creates AgentServices once · build(ChatGraphConfig) per character/model"]
    SVC["agent_graph/services.py<br/>AgentServices (mutable): stt vision tts memory creds<br/>prefs checkpointer ledger_sink knowledge_subgraph workspace_path"]
    NG["agent_graph/node_group.py<br/>NodeGroup base: __init_subclass__ auto-wrap · _ledger_sink<br/>· shared prefs accessors (moved as-is; P7 centralizes later)"]
    MED["agent_graph/nodes/media.py<br/>MediaNodes(NodeGroup): ingest stt vision gather<br/>dispatch_media input_gate media_failed"]
    CONV["agent_graph/nodes/conversation.py<br/>ConversationNodes(NodeGroup): trim memory_search knowledge_retrieve<br/>context_build compose_context call_model tools memory_out tts finalize<br/>(+ routers should_continue tts_gate knowledge_fanout)"]
    CHAT["agent_graph/chat.py<br/>ChatAgentGraph builder: holds services · build(config) composes groups<br/>· set_*_service live-swap delegators"]
    KN["services/knowledge/agent/graph.py<br/>KnowledgeAgentGraph(NodeGroup) — P4.6 optional"]

    AM --> SVC
    AM --> CHAT
    CHAT --> MED
    CHAT --> CONV
    MED --> NG
    CONV --> NG
    KN -.P4.6.-> NG
    NG --> SVC
    note1["base.py is DELETED in P4.5"]
```

`AgentServices` spec (`services.py`):
```python
@dataclass  # NOT frozen — preference reactors hot-swap fields in place (D3)
class AgentServices:
    workspace_path: Path
    ledger_sink: LedgerSink
    preferences: WorkspacePreferencesRuntime | None = None
    checkpointer: Checkpointer | None = None
    stt: STTService | None = None
    vision: VisionService | None = None
    tts: TTSService | None = None
    memory: MemoryService | None = None
    credentials: CredentialStore | None = None
    knowledge_subgraph: CompiledStateGraph | None = None
```

---

## 4. The uniform node pattern

Every node is a `@graph_logged`-marked `*_node` method on a `NodeGroup` subclass. `NodeGroup`
provides the ledger plumbing once:

```python
# node_group.py
class NodeGroup:
    def __init_subclass__(cls, **kw):           # moved verbatim from BaseAgentGraph
        super().__init_subclass__(**kw)
        # ... same auto-wrap of *_node / node_* methods via wrap_graph_node ...

    def __init__(self, services: "AgentServices") -> None:
        self.services = services
        self._ledger_sink = services.ledger_sink   # the wrapper reads this

    # Shared prefs accessors moved here as-is (P7 will centralize):
    def _current_preferences(self): ...
    def _history_window(self) -> int: ...
    def _chat_instructions(self) -> str: ...
    def _knowledge_cite_in_chat(self) -> bool: ...
```

Stateless intake group:
```python
class MediaNodes(NodeGroup):
    @graph_logged(captures={"usage", "decision"})
    async def stt_node(self, sub_state, writer):
        if self.services.stt is None or not self.services.stt.is_available():
            observe(...); return {"errors": [...]}
        ...
```

Model-bound group — **constructor-capture replaces the closure** (D2):
```python
class ConversationNodes(NodeGroup):
    def __init__(self, services, config: ChatGraphConfig):
        super().__init__(services)
        self._model_id = config.model_id
        self._system_prompt = config.system_prompt
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        self._thinking = config.thinking
        self._tools = config.tools
        self._bound = config.model.bind_tools(config.tools) if config.tools else config.model
        self._tools_by_name = {getattr(t, "name", ""): t for t in config.tools}
        self._assembler = ContextAssembler()

    @graph_logged(captures={"usage", "decision"})
    async def call_model_node(self, state, writer):
        # same body as today's closure, reading self._bound / self._model_id / self._tools / …
        ...
```

Builder composes + wires (note `retry_policy=`):
```python
# chat.py
class ChatAgentGraph:
    def __init__(self, services: AgentServices):
        self.services = services

    def build(self, config: ChatGraphConfig) -> CompiledStateGraph:
        media = MediaNodes(self.services)
        conv = ConversationNodes(self.services, config)
        b = StateGraph(GraphState)
        b.add_node("ingest", media.ingest_node)
        b.add_node("stt", media.stt_node, retry_policy=_RETRY_TWICE)   # was retry=
        b.add_node("call_model", conv.call_model_node)
        if config.tools:
            b.add_node("tools", conv.tools_node)
        if self.services.knowledge_subgraph is not None:
            b.add_node("knowledge_retrieve", conv.knowledge_retrieve_node)
        # ... edges identical in shape to today's chat.py ...
        return b.compile(checkpointer=self.services.checkpointer)

    # live-swap delegators (AgentManager + reactors call these unchanged)
    def set_stt_service(self, s): self.services.stt = s
    def set_tts_service(self, s): self.services.tts = s
    def set_memory_service(self, s): self.services.memory = s
    def set_knowledge_subgraph(self, g): self.services.knowledge_subgraph = g
```

---

## 5. Sub-stages (each ends green)

> **Golden rule:** run the characterization suites after **every** sub-stage. Commit only when
> events + final-state + `RecordingLedgerSink` row assertions pass **unchanged**.

### P4.1 — Introduce `AgentServices` (pure DI, no node moves)
- [ ] Add `services.py` with `AgentServices` (§3).
- [ ] Change `BaseAgentGraph.__init__` to take `services: AgentServices` and set
      `self._stt = services.stt` … (or read `self.services.*` directly — minimal: store
      `self.services` and add temporary properties so node bodies stay unchanged this sub-stage).
- [ ] AgentManager (≈line 190): build an `AgentServices(...)` and pass it. Keep `set_*_service`
      delegating to `self.services.*`.
- [ ] Green.

### P4.2 — Extract `NodeGroup` base
- [ ] Add `node_group.py`; **move** `__init_subclass__`, `_ledger_sink` setup, and the prefs
      accessors (`_current_preferences`, `_history_window`, `_chat_instructions`,
      `_knowledge_cite_in_chat`) out of `BaseAgentGraph` into `NodeGroup`.
- [ ] Move the `TRIMMED_MESSAGE_LIMIT` constant too (`_history_window`'s fallback) into
      `node_group.py`, and repoint its `agent_graph/__init__.py` re-export to the new home.
- [ ] Make `BaseAgentGraph(NodeGroup)` temporarily (so nodes still resolve). Green.

### P4.3 — Extract `MediaNodes`
- [ ] Create `nodes/media.py`; **move** `ingest_node`, `stt_node`, `vision_node`, `gather_node`,
      `dispatch_media`, `input_gate`, `media_failed_node` into `MediaNodes(NodeGroup)`. Replace
      `self._stt`→`self.services.stt`, `self._vision`→`self.services.vision`, `self._emit`→the
      free `emit` (from `graph_kit`, established in P1).
- [ ] Bring the **media-only helpers** `_audio_item_preview` / `_image_item_preview` into
      `nodes/media.py` (used only by `ingest`/`stt`/`vision`).
- [ ] In `chat.py` `build`, construct `media = MediaNodes(self.services)` and wire `media.*`.
- [ ] Green (this is the first cross-group wiring — watch the `dispatch_media`/`input_gate`
      conditional edges).

### P4.4 — Extract `ConversationNodes` (the big one — converts the closures)
- [ ] Create `nodes/conversation.py`; **move** `trim_history_node`, `memory_search_node`,
      `knowledge_retrieve_node`, `context_build_node`, `memory_out_node`, `tts_node`,
      `finalize_node`, `_store_turn_memory`, routers (`should_continue`, `tts_gate`,
      `knowledge_fanout`), and `_reply_knowledge_sources`/`_knowledge_scope_filters`.
- [ ] **Convert the 3 closures to methods** (D2): `make_compose_context_node` →
      `compose_context_node`; `make_call_model_node` → `call_model_node`; `make_tools_node` →
      `tools_node`. Move the captured state into `ConversationNodes.__init__(services, config)`
      (`self._bound`, `self._tools_by_name`, `self._assembler`, tuning fields) per §4.
- [ ] Bring the **conversation helpers** with these nodes into `nodes/conversation.py`:
      `_llm_decision`, `_trim_chat_history`, `_format_history`, `_memory_results_preview`,
      `_memory_text`, `_last_human_message_preview`, the 7 `_tool_*`, `_serialize_knowledge_sources`
      — and put `_error_slug` (also used by `MediaNodes`) in `nodes/_helpers.py`.
- [ ] In `build`, construct `conv = ConversationNodes(self.services, config)` and wire `conv.*`.
- [ ] Green. **The ledger rows for `call_model`/`tools`/`compose_context` must match exactly** —
      this is where a captured-field mistake shows up.

### P4.5 — Delete `BaseAgentGraph`; finalize the builder
- [ ] Rewrite `chat.py` `ChatAgentGraph` as the standalone builder (§4) — holds `services`,
      `build(config)` composes both groups. Remove the `BaseAgentGraph` inheritance.
- [ ] **Relocate the 20 module-level helpers out of `base.py` first** (see the reconciliation
      note) — `base.py` is not empty of code just because the nodes moved. Wrap helpers
      (`_is_graph_node_method`, `_node_label`) → `node_group.py`; `_audio_item_preview`/
      `_image_item_preview` → `nodes/media.py`; the conversation helpers (`_llm_decision`,
      `_trim_chat_history`, `_format_history`, `_memory_results_preview`, `_memory_text`,
      `_last_human_message_preview`, the 7 `_tool_*`, `_serialize_knowledge_sources`) →
      `nodes/conversation.py`; shared-by-both (`_error_slug`) → a small `nodes/_helpers.py`.
- [ ] **Delete `base.py`** (only after the helpers are relocated). Remove its exports from
      `agent_graph/__init__.py`.
- [ ] **Scrub the `graph_kit.py` docstring** mention of `BaseAgentGraph` (else Gate A's grep
      reads non-zero) — reword to "…without depending on the chat graph classes."
- [ ] **Fix the deprecation:** all **5** `add_node(..., retry=_RETRY_TWICE)` (`stt`, `vision`,
      `memory_search`, `memory_out`, `tts`) → `retry_policy=` (LangGraph ≥1.0; flagged in P2).
- [ ] AgentManager: `self._graph: ChatAgentGraph | None` (≈line 139); constructs
      `ChatAgentGraph(services)` (≈line 194).
- [ ] **Migrate every test that referenced `BaseAgentGraph`** (the full set — Gate A must hit zero):
      - `test_agent_graph_input_gate.py` → construct `MediaNodes(services)`; test
        `input_gate` / `media_failed_node` on it.
      - `test_graph_ledger.py` → `LedgerProbeGraph(NodeGroup)` (pass a minimal `AgentServices`
        with a `RecordingLedgerSink`).
      - `test_agent_graph_preferences.py` → import the prefs accessors from `NodeGroup` (or a
        concrete group instance).
      - `test_agent_manager.py` → it constructs `BaseAgentGraph(...)` ×2 **and** imports
        `_trim_chat_history`; repoint both (group instance + helper's new home in
        `nodes/conversation.py`).
      - `test_agent_manager_stt_reload.py` → `mgr._graph = ChatAgentGraph(services)` instead of
        `BaseAgentGraph(...)`.
      - `test_knowledge_graph_decoupled.py` → if P4.6 done, repoint to
        `assert issubclass(KnowledgeAgentGraph, NodeGroup)` + keep the no-`agent_graph.base`-import
        check; if P4.6 skipped, **delete the file** (premise moot once the god class is gone).
- [ ] Green.

### P4.6 — (optional) `KnowledgeAgentGraph(NodeGroup)`
- [ ] Make `KnowledgeAgentGraph` inherit `NodeGroup`; **delete** its P1-era `_wrap_dynamic_node`,
      `_emit`, and the manual `self._ledger_sink = LedgerSink(...)` (now from `NodeGroup`).
      Adjust `__init__` to build an `AgentServices` (or a minimal one with just `workspace_path`
      + `ledger_sink`) and call `super().__init__(services)`. Its nodes keep their explicit
      `_wrap_dynamic_node` registration (prefixed `knowledge/*` names) — that helper now comes
      from `NodeGroup`.
- [ ] Green (knowledge characterization + ledger tests unchanged).

---

## 6. New tests this stage adds (the coverage jump)

Now that nodes are isolated callables over fake services, unit-test them directly (reuse
`graph_fakes.py`):

### 6.1 `runtime/tests/test_media_nodes.py`
- [ ] `MediaNodes(services).ingest_node` splits a `make_inbound_envelope(text=…, audio=…)` into
      the right `audio_items`/`image_items`/`text_inputs`; honors `voice_input_allowed`.
- [ ] `stt_node` with `FakeSTT(mode="ok"/"fail"/"unavailable")` → transcript vs `errors` row.
- [ ] `vision_node` likewise with `FakeVision`.
- [ ] `gather_node` orders text/transcripts/visions and clears byte fields.
- [ ] `input_gate` routing; `media_failed_node` canned replies (port the existing
      `test_agent_graph_input_gate.py` cases here).

### 6.2 `runtime/tests/test_conversation_nodes.py`
- [ ] `ConversationNodes(services, config)` with `ScriptedChatModel([ai_text("hi")])` →
      `call_model_node` returns the AIMessage and emits `GRAPH_LLM_USAGE`.
- [ ] Tools loop: `ScriptedChatModel([ai_tool_call("echo_tool", {...}), ai_text("done")])` +
      `echo_tool` → `tools_node` produces the `ToolMessage` and a `tools/echo_tool` child row.
- [ ] `compose_context_node` renders memory+knowledge into `turn_context` (no `messages` write).
- [ ] `memory_search_node` / `memory_out_node` with `FakeMemory` (search hits, store count,
      disabled-pref skip).
- [ ] `tts_node` with `FakeTTS`; `tts_gate` routing.

### 6.3 `runtime/tests/test_chat_graph_builder.py` (extend P2's)
- [ ] `ChatAgentGraph(services).build(config)` composes both groups; `tools=[]` omits `tools`;
      `services.knowledge_subgraph=None` omits `knowledge_retrieve` (reuse the introspection cue
      from the P2 plan).

### 6.4 The characterization net is unchanged
P4 moves code; it must not move behavior. The §5.2 assertions (incl. `RecordingLedgerSink`
rows) stay byte-stable across all six sub-stages.

---

## 7. Self-validation gates

**Gate A — god class is gone:**
```bash
test -f hiroserver/hirocli/src/hirocli/runtime/agent_graph/base.py && echo "FAIL: base.py still exists" || echo "ok: base.py deleted"
grep -rn "BaseAgentGraph" hiroserver/hirocli/src/hirocli --include="*.py"   # expect: zero
```

**Gate B — one node style (no closures):**
```bash
grep -rn "make_call_model_node\|make_tools_node\|make_compose_context_node\|_wrap_dynamic_node" \
  hiroserver/hirocli/src/hirocli/runtime/agent_graph   # expect: zero
```

**Gate C — deprecation fixed:**
```bash
grep -rn "add_node(.*retry=" hiroserver/hirocli/src/hirocli   # expect: zero (use retry_policy=)
```

**Gate D — import health / no cycle:**
```bash
python -c "import hirocli.runtime.agent_graph.services, hirocli.runtime.agent_graph.node_group, hirocli.runtime.agent_graph.nodes.media, hirocli.runtime.agent_graph.nodes.conversation, hirocli.runtime.agent_graph.chat, hirocli.runtime.agent_manager"
```

**Gate E — ⭐ characterization net green, unchanged** (the prime directive, run after EVERY
sub-stage):
```bash
pytest hiroserver/hirocli/src/hirocli/runtime/tests -k "characterization or ledger or media_nodes or conversation_nodes or builder or input_gate or preferences"
pytest hiroserver/hirocli/src/hirocli/services/knowledge -k "characterization or ledger"
git diff -- "**/test_*characterization*.py"   # expect: NO assertion edits
```

**Gate F — full suite** before the final PR: `pytest hiroserver/hirocli`.

---

## 8. Definition of done

- [ ] `AgentServices`, `NodeGroup`, `MediaNodes`, `ConversationNodes` exist; `ChatAgentGraph` is
      a standalone builder; `base.py`/`BaseAgentGraph` **deleted** (Gate A).
- [ ] All nodes are `*_node` methods; the 3 closures + `_wrap_dynamic_node` are gone on the chat
      path (Gate B).
- [ ] `retry=`→`retry_policy=` fixed (Gate C).
- [ ] AgentManager builds `AgentServices` once; live-swap delegators preserved; preference
      reactors still hot-swap correctly.
- [ ] `test_media_nodes.py` + `test_conversation_nodes.py` added (the coverage jump); migrated
      tests pass.
- [ ] Characterization net unchanged across all sub-stages (Gate E).
- [ ] (If P4.6 done) `KnowledgeAgentGraph(NodeGroup)` with its P1-era shims removed.

---

## 9. Gotchas & cues

- **Per-build construction is mandatory for `ConversationNodes`** (D2). If you make `call_model`
  read a shared mutable `self._model`, a second `build()` for a different model silently
  corrupts the first cached compiled graph. Capture in `__init__` per build.
- **`AgentServices` is mutated in place, never replaced** — reactors do `services.stt = x`. If
  AgentManager ever rebinds the whole object, cached graphs keep the old one. Mutate fields.
- **Don't touch the ledger wrap machinery** (D1). `NodeGroup.__init_subclass__` is the *same*
  code moved up; node methods stay `*_node`; rows stay identical. If a row drifts, you renamed a
  node or changed a body — not the wrap.
- **Edges are owned by the builder**, and they cross groups (e.g. `media.input_gate` →
  `conv`/`media`'s `media_failed`, `media.gather` → `conv.trim_history`). Keep the **edge shape
  identical** to today's `chat.py`; only the node *references* change.
- **Move, don't rewrite.** Each node body is already declarative after P3 — relocate it
  verbatim, swapping only `self._stt`→`self.services.stt` and `self._emit`→`emit`. Resist
  "improving" logic; behavior changes are their own PR.
- **One sub-stage per commit.** A six-group big-bang makes a characterization failure impossible
  to localize. P4.1→P4.6 each land green.
- **Prefs accessors move as-is** to `NodeGroup`; **do not** centralize them here — that's P7.
- **Reflecting-build-updates:** internal refactor — no server restart / workspace reset / config
  change needed; note it in the PR summary.

---

## 10. TL;DR

- **Do:** introduce `AgentServices` (mutable DI container) + a `NodeGroup` base (ledger plumbing
  moved up) + `MediaNodes`/`ConversationNodes` groups; convert the 3 `make_*_node` closures to
  `*_node` methods via **per-build constructor-capture**; make `ChatAgentGraph` a standalone
  builder; **delete `BaseAgentGraph`**; fix `retry=`→`retry_policy=`.
- **Three decisions that avoid the traps:** D1 reuse the auto-wrap machinery unchanged; D2
  construct the model-bound group **per `build(config)`** (closures existed for per-build
  capture); D3 `AgentServices` is **mutable**, swapped in place for live preference reloads.
- **Land it in 6 green sub-stages** (P4.1 DI → P4.2 NodeGroup → P4.3 MediaNodes → P4.4
  ConversationNodes → P4.5 delete base + fix deprecation + migrate tests → P4.6 optional
  knowledge), characterization net green after each.
- **Coverage jump:** new `test_media_nodes.py` + `test_conversation_nodes.py` unit-test each
  node over fakes — the payoff of the whole refactor.
- **Prove it:** Gate A (base gone), B (no closures), C (no `retry=`), D (no cycle), **E
  (characterization unchanged — every sub-stage)**, F (full suite).
- **Out of lane:** state restructuring (P6), prefs centralization (P7) — not here.
