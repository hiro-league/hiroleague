# Memory: Eval vs Chat — Parity Analysis & Gaps

> **Status:** Research note (no code changes). Goal: bring the live **chat** conversation-memory
> experience up to the quality the **memory-eval** track already reaches.
>
> **⚠️ Jun 2026 update:** the eval recall leg was rebuilt around an **agentic retrieval loop**
> (`services/memory/agent/`); chat was **not** changed. The *"Current reality"* section below
> reflects today's code (which **takes precedence over docs**). The original *"Key insight"*
> analysis further down **predates the loop and is now stale** — kept only for the
> output-formatting gaps it catalogs, which still apply.
>
> Related: [`memory-graphiti-replacement-design.md`](memory-graphiti-replacement-design.md),
> [`eval-corpus-tracks-design.md`](eval-corpus-tracks-design.md),
> [`agentic-memory-retrieval-implementation.md`](agentic-memory-retrieval-implementation.md).

## Current reality (Jun 2026) — supersedes the analysis below

**Eval** runs a full agentic retrieval loop (`run_retrieval`): the LLM decomposes the question
into parallel sub-queries, searches across several turns, accumulates a deduped/time-sorted fact
set, then drafts an answer that the answerer + judge consume. **Chat** still does **one**
`memory.search()` call and folds the raw hits into the persona prompt via a flat `memory_block`.

The loop engine is **already surface-neutral** — the only eval-bound parts are the *preferences
namespace* (`graph.eval.*`), the *call site* (`runner_memory.py`), and *what's consumed from the
result*. So adopting it in chat is **lift-and-share, not a rewrite**.

### Today: both flows, with reuse highlighted

```mermaid
flowchart TB
    %% ================= EVAL today =================
    subgraph EVAL["EVAL — today · services/eval/runner_memory.py"]
        direction TB
        EQ["Question"] --> ERA["_recall_via_agent"]
        ERA --> LP["Retrieval model + EVAL prompt + caps<br/>(graph.eval.*)"]
        LP -->|"bind search_memory tool"| TURN{"turn ≤ max_agent_turns?"}
        TURN -->|"tool call: 1..N sub-queries"| SMT["SearchMemoryTool"]
        SMT --> MS1["memory.search → search_chunk_ids"]
        MS1 --> ACC["Accumulator<br/>dedup by (kind,uuid) · time-sort · provenance"]
        ACC -->|"only NEW items fed back"| TURN
        TURN -->|"no tool call / budget hit"| DRAFT["answer_text (draft)"]
        ACC --> PRES["present_accumulator +<br/>accumulated_item_to_recall_row"]
        PRES --> RR["recalled_rows"]
        RR --> AFC["answer_from_context<br/>(grounding prompt)"]
        DRAFT --> AFC
        AFC --> JUDGE["judge_answer → verdict"]
    end

    %% ================= CHAT today =================
    subgraph CHAT["CHAT — today · runtime/agent_graph/nodes"]
        direction TB
        CU["user_text"] --> MSN["memory_search_node"]
        MSN --> MS2["memory.search()  ◄── SINGLE SHOT"]
        MS2 --> HITS["hits · top_k=8"]
        HITS --> RM["retrieved_memories"]
        RM --> CC["compose_context_node"]
        CC --> MB["memory_block<br/>flat list · text[:500] · drops temporal/relation/SUPERSEDED"]
        MB --> PERSONA["call_model (persona) → reply"]
    end

    %% ============ reuse / insertion mapping ============
    SMT -. "REUSE the loop here<br/>(gather-only mode)" .-> MS2
    PRES -. "REUSE present + rich rows" .-> MB

    classDef reuse fill:#d6f5d6,stroke:#2e7d32,stroke-width:2px,color:#000;
    classDef insert fill:#ffe0b2,stroke:#e65100,stroke-width:2px,color:#000;
    classDef unchanged fill:#eceff1,stroke:#607d8b,color:#000;
    class LP,TURN,SMT,MS1,ACC,PRES,RR reuse;
    class MS2,MB insert;
    class CU,MSN,HITS,RM,CC,PERSONA,EQ,ERA,DRAFT,AFC,JUDGE unchanged;
```

**Legend** — 🟩 green = **reuse from eval** (the loop engine, untouched) · 🟧 orange = **chat
insertion points** (the two places that change) · ⬜ grey = unchanged.
The two dashed arrows are the whole job: swap chat's single `memory.search()` for the **loop**
(gather-only), and upgrade `memory_block` to render the **rich rows** `present_*` already produces.

### Target chat flow (after adoption)

```mermaid
flowchart LR
    CU["user_text"] --> MSN["memory_search_node"]
    MSN --> ENTRY["shared retrieval entrypoint<br/>gather-only mode"]
    subgraph NEW["reused engine + CHAT-specific config"]
        direction TB
        ENTRY --> LOOP2["run_retrieval<br/>CHAT prompt · CHAT caps · CHAT model"]
        LOOP2 --> ACC2["Accumulator"]
        ACC2 --> PRES2["present + rich rows"]
    end
    PRES2 --> MB2["memory_block (upgraded)<br/>kind sections · temporal · no truncation"]
    MB2 --> PERSONA2["call_model (persona) → reply"]

    classDef reuse fill:#d6f5d6,stroke:#2e7d32,stroke-width:2px,color:#000;
    classDef newcfg fill:#bbdefb,stroke:#1565c0,stroke-width:2px,color:#000;
    classDef insert fill:#ffe0b2,stroke:#e65100,stroke-width:2px,color:#000;
    class LOOP2,ACC2,PRES2,ENTRY reuse;
    class MB2 insert;
```

**Reading the target:** the green blocks are the **same eval engine**; only the **config is
chat-specific** (its own prompt, caps, model — blue intent). Chat consumes the **accumulator**
(not the loop's draft answer) and lets the **persona** write the reply → "gather-only" skips the
loop's final synthesis turn. With caps at `turns=1, parallel=1`, this collapses back to today's
single-shot — so it ships safe and tunes up.

### What gets reused vs added

| Eval component | File | In chat? |
|---|---|---|
| `run_retrieval` loop | `services/memory/agent/retrieval_agent.py` | **Reuse** (add gather-only mode) |
| `SearchMemoryTool` | `services/memory/agent/search_tool.py` | **Reuse** as-is |
| `Accumulator` | `services/memory/agent/accumulator.py` | **Reuse** as-is |
| `present_accumulator` / `accumulated_item_to_recall_row` | `services/memory/agent/presentation.py` | **Reuse** as-is |
| Retrieval prompt | `graph.eval.retrieval_agent_prompts` | **New** chat-scoped prompt (tuned for user/characters) |
| Caps / model | `graph.eval.retrieval_agent`, `graph.eval.retrieval_model` | **New** chat-scoped instances |
| Shared entrypoint | _does not exist yet_ | **New** small `MemoryRetriever` seam |
| `memory_block` | `runtime/agent_graph/context_assembly.py` | **Upgrade** to rich rows |
| Answerer / judge | `services/eval/judge.py` | **Not used** — persona answers in chat |

---

## Key insight

> **⚠️ Stale (pre-agentic-loop).** The claim below that "both paths run the exact same recall
> engine" is **no longer true** — see *Current reality* above. The output-formatting gaps it
> documents (sections 3 / O1–O5) still hold and feed the `memory_block` upgrade.

Both paths run the **exact same recall engine**. `create_memory_service` (chat) and
`create_eval_memory_service` (eval) both build the same `GraphitiConversationMemory` over
`GraphitiMemoryService.from_preferences`, reading the same `graph.*` and `memory.search.*`
preferences. The eval was deliberately written to *reproduce* the runtime
(`services/memory/__init__.py:129-130` — *"Eval mirrors the runtime… so the Memory eval
reproduces what the agent will actually see at recall time"*).

So the quality gap is **not** in retrieval configuration. It is in two places: **the inputs
written to memory**, and **how recalled facts are formatted into the answer prompt**.

```
          INGEST                    RETRIEVE (identical)            ANSWER
EVAL   both speakers,            ┌────────────────────┐    format_recall_context →
       real reference_time   →   │ GraphitiMemory     │ →  Facts/Entities/Episodes
       clean turns               │ .search()          │    w/ temporal+rel+SUPERSEDED
                                 │ top_k=8, temporal, │    → grounding-only prompt
CHAT   user half only,           │ recipe, scope,     │    memory_block →
       arrival timestamp,    →   │ sim_min_score —    │ →  flat "- date·score·text[:500]"
       raw user_text query       │ SAME for both      │    → persona chat prompt
                                 └────────────────────┘
```

## 1. Configuration — essentially at parity ✅

| Knob | Eval | Chat | Same? |
|---|---|---|---|
| Recall depth `top_k` | 8 | 8 | ✅ |
| Temporal lens | `graph.temporal_default` | same | ✅ |
| Recipe / scope / k_hop | `graph.search_recipe/scope/k_hop` | same | ✅ |
| Candidate floor `sim_min_score` | 0.3 | 0.3 | ✅ |
| Extraction / small / embedder model | shared `graph.*` | same | ✅ |
| Group isolation | `eval_mem_{set}` | `mem_{user}_{char}` | ✅ (isolation only) |

There is **no retrieval-config gap to close**. The engine the eval validated is the engine
chat uses. (Note: the "eval recalls 20 vs chat 8" intuition is **false** — both read
`memory.search.top_k`, default 8: runtime at `services/memory/__init__.py:71`, eval at
`services/memory/__init__.py:128`.)

## 2. Inputs — ingestion (corrected Jun 2026 after design review)

> **Framing correction.** Earlier notes treated eval as a *mirror* of chat ("eval reproduces
> what the agent sees"). That is **not** the working relationship: **eval is a testbench** — a
> harness to test ingestion/retrieval configurations *before* applying the winners to chat. Eval
> and chat are *allowed* to diverge (the corpus is deliberately two-sided because the benchmarks
> need both speakers as gold turns). The goal is not to make chat identical to eval — it is to
> use eval to find the best chat ingestion, then ship it to chat.

**The ingest engine is fully shared and identical** (confirmed in code): both surfaces build
through `GraphitiMemoryService.from_preferences` and call the same `ingest_episodes`. Shared and
identical across chat & eval:

- Extraction model, embedder, `custom_extraction_instructions`, temporal default — all `graph.*`.
- Observability tier (`graph.observability`: off/ledger/trace) + the per-episode / per-operation
  ledger rows and the trace sidecar (chat folds these under the turn's `memory_out`; eval folds
  them under a dedicated remember run — same machinery, different run topology).
- No document chunking: **1 turn = 1 episode = 1 point_id**.

The only intentional divergence today is the **drawer** (`group_override` → `eval_mem_{set}`). So
every difference below is about **what episodes the caller feeds the engine**, not the engine.

### I1 — the assistant side (the one real gap) → **decided: approach 4A**

| | Eval | Chat (today) |
|---|---|---|
| What's written | Full dialogue: **both speakers**, each turn its own stored episode (corpus fixture) | **User turn only**; assistant reply never written (F7 write-gate / decision D2 anti-echo) |

`F7` is the write-gate mechanism (`ALLOWED_SOURCE_ROLES` in `graphiti_ingest.py`); `D2` is the
policy it enforces — *user-half only, never the assistant reply, so the graph can't become a
stale echo of its own output* (mem0 #4573). Because only user turns are ever stored, graphiti's
internally-injected extraction context is **user-only**, so an anaphoric user turn ("yes, the
second one") has **no antecedent to resolve against**.

**Decided approach — 4A "assistant-as-context, user-only extraction" (chat's default ingestion;
no pref):**

- When ingesting a user turn, **fold the preceding assistant message** (turn N−1 — the reply the
  user is responding to, pulled from conversation history) into the episode body as *context*.
- Set `custom_extraction_instructions` so facts are **extracted/attributed only from the user**;
  the assistant context is disambiguation only.
- The assistant turn is **never stored as its own episode** → no echo. This keeps D2's intent
  while restoring the coreference signal eval gets for free from a two-sided corpus.

Constraints / notes:

- Graphiti's `previous_episodes` is **internally injected** — we control only the *count*, not
  the content — so 4A must **body-fold** the assistant context; it can't go through that channel.
- Fold the **prior assistant reply (N−1)**, *not* the current reply (which is the answer *to*
  this turn and is model output → folding it reintroduces echo and leaks the future).
- Body-fold changes the stored episode text (what BM25 indexes / shows as the episode body) —
  acceptable, but noted.
- **Eval stays two-sided** (unchanged): its benchmarks require the assistant turns as gold
  episodes. Eval is the testbench; it does **not** adopt 4A.

### I2 — timestamps → at parity (no action)

Chat already passes the real turn time (`routing.timestamp`) as `reference_time`; in-turn dated
facts get their own `valid_at` from extraction. The only eval-only trait is *backdating* a
simulated months-long history, which live chat can't and shouldn't reproduce.

### I3 — turn cleanliness → **not a gap** (handled by extraction prompts)

Noisy / multi-topic / greeting turns are absorbed by graphiti's extraction prompt (+
`custom_extraction_instructions`) → "no facts." Dropped from the gap list.

### I4 — query quality → retrieval, not ingestion

Memory query-rewrite is a *recall* concern, tracked with retrieval — not an ingestion input.

### New — chunk guard for chat (oversized turns)

Memory turns aren't chunked (the corpus loader keeps eval bodies under `CHUNK_MIN_TOKENS`), but a
**very long chat user turn is unguarded** and could trip graphiti's internal `should_chunk`,
breaking the pre-seeded `uuid == point_id` invariant (`graphiti_ingest.py:508`). **Action: guard
chat turns against the threshold and expose `chunk_min_tokens` as a chat/memory preference** so it
is tunable.

### Rollout / params

Keep ingestion params **shared today**; add **eval-specific overrides later** (factory seam or a
`graph.eval.ingest.*` namespace) when we want eval to A/B configs independently of chat.

## 3. Outputs — the biggest controllable lever

The same `hits` (same metadata keys) flow to both renderers, but they render very differently:

| # | Eval `format_recall_context` (`eval_judge.py:110-137`) | Chat `memory_block` (`context_assembly.py:157-176`) |
|---|---|---|
| **O1** | Keeps **relationship**, **temporal validity** (`valid X → present`), and **`SUPERSEDED`** markers per fact | **Drops all of it.** Renders only `- {date} · score {s} · {text[:500]}` |
| **O2** | Groups into **Facts / Entities / Episodes** sections with headings | **Flattens** all kinds into one bullet list — a raw episode body looks identical to an extracted fact |
| **O3** | **No truncation** | Truncates each memory to **500 chars** |
| **O4** | Shows the fact's **`valid_at`** validity window | Reads **`created_at`** (ingest time), which fact rows generally don't carry → date often **blank/missing** |
| **O5** | System prompt = strict grounding-only `DEFAULT_MEMORY_EVAL_ANSWER_PROMPT` ("use ONLY the facts… answer every part the facts support"); answer model = knowledge-answering tuning (temp **0.2**) | Memory is one advisory block inside the **persona** prompt + `chat.instructions`; chat model is `balanced_chat` (temp **0.7**) with a tool loop. The grounding/completeness discipline is **never instructed**. |

**O1 is the headline:** the eval answer model reaches its quality partly because it *sees*
`valid → present` and `SUPERSEDED` annotations and can choose the current fact. Chat strips
those before the model ever sees them.

## How to close the gap (proposed, by leverage-to-effort)

1. **Bring `memory_block` to parity with `format_recall_context`** (O1–O4). The metadata is
   already on the `hits` — chat just discards it. Render kind sections, keep relationship +
   `valid_at → invalid_at` + `SUPERSEDED`, use `valid_at` for the date, don't truncate facts.
   *Highest leverage, lowest risk — pure formatting on data already in hand.*
2. **Instruct grounding/completeness in the chat answer** (O5). Adapt the eval's "answer every
   part the facts support" discipline into the persona context so memory is actually used.
3. **Add a memory query-rewrite** (I4) mirroring `knowledge.rewrite.*`, so chat searches memory
   with a standalone question instead of raw anaphoric `user_text`.
4. **Assistant-as-context ingestion (I1) — decided (4A).** Make chat fold the prior assistant
   turn (N−1) into the user episode body as context, with `custom_extraction_instructions`
   restricting extraction to the user. Chat's **default** behavior, no pref; the assistant turn
   is never stored as its own episode (keeps D2's anti-echo intent). **Eval stays two-sided.**
5. **Chunk guard for chat (new).** Guard chat turns against `CHUNK_MIN_TOKENS` and expose it as a
   chat/memory pref, so an oversized turn can't trip graphiti's internal split and break
   `uuid == point_id`.
6. **Timestamp fidelity** (I2) — none; already at parity. Cleanliness (I3) — none; extraction
   prompts handle it.

## TL;DR

- **No config gap.** Eval and chat share one recall engine and the same knobs
  (`top_k=8`, temporal, recipe, scope, `sim_min_score`, models).
- **The gap is in inputs and output-formatting, not retrieval.**
- **Output (biggest lever):** chat's `memory_block` strips temporal/relationship/`SUPERSEDED`
  metadata, flattens kinds, truncates to 500 chars, and shows the wrong date — all of which
  eval's `format_recall_context` keeps. The data is already on the hits.
- **Ingestion:** the engine, observability, tracking and params are shared/identical — the only
  gap is the **assistant side** (chat writes user-only). **Decided fix: 4A** — fold the prior
  assistant turn as context with user-only extraction, as chat's default; **eval stays two-sided**
  (it is a testbench, *not* a mirror). Add a **chunk guard** for oversized chat turns. Timestamps
  already at parity; cleanliness handled by extraction prompts; query-rewrite is a retrieval item.
- **Answer discipline:** eval uses a grounding-only prompt at temp 0.2; chat folds memory into
  a persona prompt at temp 0.7 with no completeness instruction.
- **Recommended order:** (1) `memory_block`↔`format_recall_context` parity, (2) grounding
  instruction, (3) memory query-rewrite, (4) 4A assistant-as-context ingestion + chunk guard.
