# Memory: Eval vs Chat — Parity Analysis & Gaps

> **Status:** Research note (no code changes). Goal: bring the live **chat** conversation-memory
> experience up to the quality the **memory-eval** track already reaches.
>
> Related: [`memory-graphiti-replacement-design.md`](memory-graphiti-replacement-design.md),
> [`eval-corpus-tracks-design.md`](eval-corpus-tracks-design.md).

## Key insight

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

## 2. Inputs — real gaps

| # | Aspect | Eval | Chat | Impact |
|---|---|---|---|---|
| **I1** | **Whose turns are written** | Every episode — **both speakers** | **User half only** (decision D2/F7, `graphiti_conversation.py:13`) | Facts stated by the *other party* enter eval memory but never chat memory. Eval corpus is a full dialogue; chat sees one side. **Biggest input asymmetry.** |
| **I2** | **Timestamp fidelity** | Real `reference_time` (true event time) | Message **arrival** time; "now" if absent (`graphiti_conversation.py:160,168`) | Dated facts ("I started last March") get stamped *now* in chat → weaker `valid_at`, weaker supersession reasoning. |
| **I3** | **Turn cleanliness** | Curated single-statement turns | Raw user text (greetings, multi-topic, noise) | Extraction quality more variable in chat. |
| **I4** | **Query quality** | Standalone, well-formed question | Raw `user_text`, possibly anaphoric. **No memory query-rewrite** (knowledge has `knowledge.rewrite.*`; memory has none) | Chat recall is searched with a worse query than eval ever uses. |

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
4. **Reconsider one-sided ingestion** (I1) — decide whether chat should also remember salient
   assistant-asserted facts (or extract facts spanning both turns), since the eval's quality bar
   was measured on a two-sided transcript. Collides with the anti-echo D2/F7 decision → design
   call, not a tweak.
5. **Timestamp fidelity** (I2) — lower priority; only matters for explicitly dated statements.

## TL;DR

- **No config gap.** Eval and chat share one recall engine and the same knobs
  (`top_k=8`, temporal, recipe, scope, `sim_min_score`, models).
- **The gap is in inputs and output-formatting, not retrieval.**
- **Output (biggest lever):** chat's `memory_block` strips temporal/relationship/`SUPERSEDED`
  metadata, flattens kinds, truncates to 500 chars, and shows the wrong date — all of which
  eval's `format_recall_context` keeps. The data is already on the hits.
- **Inputs:** chat writes only the user half, uses arrival time, and searches with raw
  anaphoric `user_text` (no memory query-rewrite).
- **Answer discipline:** eval uses a grounding-only prompt at temp 0.2; chat folds memory into
  a persona prompt at temp 0.7 with no completeness instruction.
- **Recommended order:** (1) `memory_block`↔`format_recall_context` parity, (2) grounding
  instruction, (3) memory query-rewrite, (4) revisit one-sided ingestion.
