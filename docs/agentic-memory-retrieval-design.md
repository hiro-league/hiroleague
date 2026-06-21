# Agentic Memory Retrieval — Decompose-and-Search Recall Loop

> **Design doc (proposed).** Replace the memory track's **single-shot recall search** with a
> **bounded agentic loop**: the LLM is given a *narrow* `search_memory` tool, may issue **several
> searches**, inspects what comes back, and decides whether to **search again** (different query/knobs)
> or **answer** — capped at a hard search limit. The motivation is an evidence-recall analysis
> (BEAM-128k units 13 & 14) showing the bottleneck is **retrieval reaching the wrong axis**, not
> ingestion or extraction. The design is deliberately **benchmark-agnostic and un-baked**: no
> question-type catalog, no per-category logic, no examples drawn from any eval corpus.
>
> **Companions:**
> [`eval-evidence-recall-design.md`](eval-evidence-recall-design.md) (the ground-truth retrieval
> metric this is optimizing),
> [`memory-graphiti-replacement-design.md`](memory-graphiti-replacement-design.md) (the
> `GraphitiConversationMemory` recall leg this wraps),
> [`memory-eval-vs-chat-parity.md`](memory-eval-vs-chat-parity.md) (why the eval path and the chat
> path must stay aligned),
> [`rag-optimize.md`](rag-optimize.md) (retrieval-tuning levers, which §5 explains are **not** the fix here).
>
> **Mode:** initial development — **no backward compatibility / no migration / no wrappers**
> (repo rule, explicitly abided).
>
> **Status:** **Proposed** — not yet implemented. Grounded in the units 13/14 trace analysis (§3).

---

## 1. The one-paragraph version

The memory recall leg today issues **one** similarity search (`query`, `top_k`, `temporal`) and hands the
top-k facts to the answerer. An evidence-recall analysis of BEAM-128k units 13 & 14 shows this surfaces
only **~44% of gold episodes**, and — critically — **92% of the missed gold already exists as extracted
facts in the graph**; it simply never ranks into the top-k for the *verbatim question*. The questions and
the stored facts live on **different axes**: a question expresses an **intent/operation** ("how did my
plan change", "have I ever…", "suggest X" under a standing rule), while the facts express **content**.
Widening the nets (lower `sim_min_score`, higher `top_k`) only adds topically-similar **distractors** —
the gold was never topically similar. The fix is to let an LLM **decompose the question into one or more
targeted searches**, choosing a *small* set of retrieval knobs, **observe** the returns, and **iterate**
until it has enough or hits a cap — then answer (or honestly abstain). All multi-search complexity
collapses back into the **one** `recalled` set + **one** `answer` the eval already consumes.

---

## 2. The needs that drove this scope

These are the explicit requirements that shaped the design (recorded verbatim-in-spirit so future readers
know *why* the scope is what it is):

1. **Improve retrieval, regardless of answers.** The immediate goal is to raise how much of the
   ground-truth evidence the recall leg actually surfaces — measured objectively against gold evidence
   episodes, independent of whether the final answer was judged correct.
2. **mem eval today, chat afterwards.** The first target is the **memory-eval recall leg**. The same
   mechanism must port cleanly to **live chat conversation** later — so the design is built for chat from
   the start, but only the eval path is wired now.
3. **No knowing the question type.** In real conversation we just get a question. The system must **not**
   depend on recognizing a fixed set of question categories.
4. **Never bake the benchmark.** No tailoring results to a benchmark, no per-category answer shaping, no
   few-shot examples lifted from any eval corpus, no thresholds tuned to a specific suite. Benchmarks are
   **held-out diagnostics**, never targets.
5. **Expose only a narrow, LLM-relevant set of search knobs.** The model should control *only* the
   parameters it can meaningfully reason about:
   - **temporal lens** — `current` vs `historical`, depending on whether the question is about the present
     state or change over time;
   - **number of results** — so a hard search that comes back empty/thin can ask for *more* data, capped
     to a sane min/max;
   - **expansion hops** — `1` = no hops, `2` = one hop, `3` = two hops (for multi-hop questions), and no
     more than that;
   - **show superseded / `expired_at` in results** — when looking at an event that keeps changing over
     time, or when validity itself matters.
   Everything else (rerank recipe, search scope, similarity floors, reranker min-score, group id) is **not
   exposed** — the LLM has no useful basis to set it; it stays at admin-pref defaults.
6. **Multiple searches, model-paced.** The model may run several searches and **decide for itself**
   whether to search more or stop and answer — **up to a hard limit**.
7. **Collapse many returns into one.** The eval (and later chat) expects a single recalled context and a
   single answer. Multiple search returns must accumulate into **one** deduped context — one-in/one-out
   preserved.

---

## 3. Why: the evidence (BEAM-128k units 13 & 14)

Tracing all **111 gold-episode slots** across both units through the pipeline (using the `ingest_trace`
sidecars for what each chunk *persisted*, and the `retrieval_trace` sidecars for what each leg returned):

```
111 gold-episode slots
   ├─ ingested?              111 / 111  (100%)  → nothing lost at ingest
   ├─ converted to facts?    106 / 111  (95%)   → extraction mostly works
   └─ recalled (top-20)?      49 / 111  (44%)   → the cliff
```

| Fate of gold episode | Count | Meaning |
|---|---:|---|
| Recalled (in the top-k pool) | 49 | reached the answerer |
| **Ingested, facts extracted, NOT recalled** | **57** | **facts exist in the graph; retrieval never surfaced them** |
| Ingested, 0 facts extracted, NOT recalled | 5 | extraction gap (mostly standing instructions collapsing to a bare entity) |
| Not ingested | 0 | no data loss |

**The bottleneck is retrieval, not the earlier pipeline.** And it is not a *ranking-strength* problem
fixable by widening candidates — it is an **axis** problem. Two mismatch classes, both confirmed in the
traces (the search query is the **verbatim question** — there is no rewrite on this path):

- **Speech-act mismatch.** Q "Can you suggest some good audiobooks?" vs gold *"Always include audiobook
  narrator details when I ask about audiobook recommendations."* The gold is a **rule** that *governs* the
  request; it shares one noun with the question and none of its defining words. No vector/BM25/keyword
  signal links a request to the rule that constrains it.
- **Abstraction mismatch.** Q "list the **order** in which I **brought up** different **aspects**…" — the
  distinctive words describe an **operation over the conversation**, not the content of any episode, so the
  episodes that *constitute* the answer don't resemble the question. For one ordering question, **4 of 5**
  gold episodes were not candidates in *any* leg.

Conclusion: relevance here is defined by **role / time / completeness**, which similarity cannot see.
The query must be **transformed onto the right axis** before retrieval — and sometimes more than one
search is needed. That is what the loop does.

---

## 4. What was rejected (and why)

| Option | Verdict | Reason |
|---|---|---|
| Widen retrieval (`sim_min_score↓`, `top_k↑`, `k_hop↑`, recipe A/B) | **Rejected as the fix** | Adds topically-similar **distractors**; the gold was never topically similar, so it stays out *and* precision drops. (Still fine as background defaults.) |
| Fixed **intent classifier → canned decomposition** (route into the 10 diagnostic groups) | **Rejected** | The 10 groups were a **diagnosis**, not a routing table. A classifier over benchmark-derived categories is **baking** (need #4) and brittle on open chat turns (need #3). |
| Static **plan-then-execute** with eval-derived examples | **Rejected** | Examples from the eval corpus are leakage; a one-shot plan can't react to empty/thin returns (need #6). |

The 10-group taxonomy survives **only as a thinking tool** for reviewers — never as code.

---

## 5. The design

### 5.1 Loop

```
                        ┌────────────────────── question (verbatim) ───────────────────────┐
                        ▼                                                                    │
            ┌───────────────────────┐                                                       │
            │  RETRIEVAL AGENT (LLM) │  system prompt = role + tool spec + GENERAL knob      │
            │  sees: question +      │  guidance (NO category rules, NO eval examples)       │
            │  all prior tool results│                                                       │
            └───────────┬───────────┘                                                       │
                        │ emits ONE of:                                                      │
          ┌─────────────┴─────────────┐                                                      │
          ▼                           ▼                                                       │
   tool call:                    final answer  ───────────────► stop                         │
   search_memory({…}) + goal          │                                                       │
          │                           └── (or "No information available.")                    │
          ▼                                                                                    │
   ┌──────────────────┐                                                                        │
   │ EXECUTOR (code)  │  runs graphiti search with the LLM's 4 knobs + hidden admin defaults   │
   │  • dedup by id vs ACCUMULATOR                                                              │
   │  • tag each new item with {search_id, goal}                                                │
   │  • keep validity fields if include_history                                                 │
   └────────┬─────────┘                                                                         │
            │ returns: {search_id, returned, new, accumulated_total, facts[]}                   │
            ▼                                                                                    │
   ACCUMULATOR (dedup-by-id set, grows each round) ── appended to agent context ────────────────┘
            │
            └── on stop → ACCUMULATOR = `recalled`,  final message = `answer`   (capped at MAX_SEARCHES)
```

### 5.2 The tool surface (only the four knobs from need #5)

```text
search_memory(
  query:           str,                          # always
  temporal:        "current" | "historical",     # current = valid-now; historical = include past/changed
  limit:           int   = 10,                    # capped [MIN=5, MAX=50]; raise when a search is empty/thin
  hops:            1 | 2 | 3 = 1,                 # 1 = no expansion, 2 = one hop, 3 = two hops
  include_history: bool  = false                  # annotate results with valid_at / invalid_at / superseded
)
```

**Hidden from the LLM** (stay at admin-pref defaults): `recipe`, `search_scope`, `sim_min_score`,
`reranker.min_relevance`, `group_id`. The LLM has no useful basis to set these.

**Semantics & interactions:**
- `temporal` selects which facts are *candidates*; `include_history` controls whether superseded
  candidates are *surfaced with their validity dates*. `include_history` only adds meaning when
  `temporal="historical"` — under `current`, everything returned is valid-now (no expiry to show).
- `limit` is the model's "find me more data" lever for hard/empty searches; it is **clamped** to
  `[MIN, MAX]` server-side regardless of what the model asks.
- `hops` is bounded to `{1,2,3}` by construction.

**Wiring note (no-backward-compat):** `temporal` and `limit`(=`num_results`) are already per-call on
`search_chunk_ids`. **`hops` (today `graph.k_hop`) and `include_history` are global admin prefs and must be
lifted to per-call arguments**, defaulting to the admin pref when the model omits them. The tool is exposed
per the **Tools Architecture** (new `search_memory` tool over `GraphitiConversationMemory`); it is **not**
auto-attached to the chat agent surface yet (eval-only for now).

### 5.3 Prompt shape (system)

No category catalog — role + general guidance on the four knobs. The generality (need #3) and the
no-baking rule (need #4) live *here*: we teach the **method**, not the answers.

```text
You answer the user's question from a memory of past conversation facts. You cannot read the
memory directly — retrieve it with search_memory. You may call it several times, then answer.
Stop as soon as the retrieved facts are enough, or after {MAX_SEARCHES} searches.

  query           → phrase as a STORED FACT, not as the user's question (drop "can you",
                    "how many", "walk me through").
  temporal        → "current" for the state that holds now; "historical" when the question is
                    about change over time, or "ever / never".
  limit           → start small; if a search is empty or thin and you still need the answer,
                    search again with a higher limit (max {MAX}).
  hops            → 1 direct; 2 if the answer links one entity to another; 3 for two links.
  include_history → true to see when each fact became valid / invalid (timeline / change questions).

After each result decide: do I have enough to answer correctly? If not, what is missing and which
knob surfaces it? If the memory genuinely lacks the detail, say so — do not guess.
```

### 5.4 Response shape (per step) — native tool call + free-text `goal`

```json
{ "tool": "search_memory",
  "args": { "query": "monthly book and subscription budget",
            "temporal": "historical", "limit": 10, "hops": 1, "include_history": true },
  "goal": "find the current budget and any earlier value it replaced" }
```

`goal` is **free text**, used only as a **provenance label** for the accumulator and the trace — never a
key into canned logic. (See §6 on intent.)

### 5.5 Tool-result shape (fed back to the agent)

```json
{ "search_id": 2, "returned": 7, "new": 4, "accumulated_total": 11,
  "facts": [
    { "id":"…", "fact":"Monthly budget is $50.", "valid_at":"2024-02-10", "invalid_at":null,        "superseded":false },
    { "id":"…", "fact":"Monthly budget is $40.", "valid_at":"2024-01-05", "invalid_at":"2024-02-10", "superseded":true  }
  ] }
```

---

## 6. Accumulation — many returns, one context (need #7)

A single **accumulator** (dedup-by-`id` set) grows across iterations:

- Each search's results are **deduped against the accumulator**, so the agent sees only *new* facts
  (context stays lean). The `returned` / `new` / `accumulated_total` counters are the model's signal that a
  search added nothing → change a knob or stop.
- Every item retains **provenance** (`search_id`, `goal`) and, when `include_history`, its **validity
  fields**.
- On stop, the accumulator **is** the `recalled` set and the final message **is** the `answer` — so N
  searches collapse to the **one-in/one-out** shape the eval expects.
- **Deterministic post-work is intent-agnostic on purpose** (no baking): the executor does only
  **dedup-by-id** and, when `include_history`, **sort-by-`valid_at` + expose superseded markers**. It does
  **not** do per-category counting/diffing/ordering — that would re-encode the benchmark. The *semantic*
  work (counting distinct items, comparing current-vs-old, narrating a timeline) is the **model reasoning
  over the clean, deduped, time-annotated set**.
- **Anti-truncation rule:** never merge by "concatenate all returns, then global top-k" — that re-creates
  the original bug (a dense facet drowning a rare critical fact). Because each search is a *separate* tool
  call with its own `limit`, each contributes its own results directly into the accumulator; there is no
  global re-rank that can evict another search's findings.

---

## 7. Do we still extract "intent"? — No closed-set classification (needs #3, #4)

We do **not** extract a categorical intent and switch on it. Intent stays **latent**, expressed two ways:

1. **Implicitly**, through the query rewrite + which knobs the model sets (`historical + include_history`
   *is* the model saying "this is a change-over-time question," without naming a category).
2. **A free-text `goal`** per search, used only as a provenance/merge label.

The model gets the benefit of reasoning about what it's after (better phrasing, right knobs) with **zero**
fixed taxonomy and nothing tuned to any benchmark.

---

## 8. Scope: eval today, chat later

**Now — memory eval.** The loop replaces the single recall search in the eval's recall+answer leg. Outputs
are unchanged: a `recalled` fact set (the accumulator) and an `answer` (the final message), so the judge,
the evidence-recall metric ([`eval-evidence-recall-design.md`](eval-evidence-recall-design.md)), and the
retrieval/ingest traces keep working.

**Later — chat.** The same loop and tool drop into the chat `memory_search` node. Only three additions,
none of which touch the core loop:
- a **need-memory gate** in front (most turns skip retrieval entirely — latency/cost);
- **coreference** resolution against recent dialogue *before* the first `query` (eval questions are
  self-contained; chat turns are not);
- the **answerer becomes the persona** (assistant voice/character) instead of the eval's terse format.

Keeping the retrieval loop identical across both is the parity requirement in
[`memory-eval-vs-chat-parity.md`](memory-eval-vs-chat-parity.md).

---

## 9. Anti-baking guardrails (need #4)

- Prompt teaches **general method**, not categories; **no** few-shot examples from any eval corpus.
- **No per-category answer formatting** — the answerer receives a clean fact set, not a benchmark recipe.
- Benchmarks (BEAM, LoCoMo) are **held-out diagnostics**. If we ever change behavior because of a *specific*
  benchmark item, that is the line we don't cross.
- Retrieval reasoning runs on a **capable model**; the local extraction model may not strategize well —
  that is a model-routing decision, not a prompt hack.

---

## 10. Risks & open questions

- **Non-determinism vs eval reproducibility.** An agentic loop makes the eval score noisier. Acceptable
  because the goal is **live quality**, not a reproducible number — but pin **low temperature** and a
  **hard `MAX_SEARCHES`** for stability. Open: do we want a fixed seed / cached-plan mode for regression
  runs?
- **`MAX_SEARCHES`, `MIN/MAX limit` values.** Need calibration on units 13/14 + a stress corpus
  ([`conversation-memory-stress-corpus-design.md`](conversation-memory-stress-corpus-design.md)). Start
  conservative (e.g. `MAX_SEARCHES=4`, `limit∈[5,50]`).
- **Cost/latency per question.** Up to `MAX_SEARCHES` LLM round-trips + searches. Tolerable in eval; the
  chat need-memory gate handles the live-traffic common case.
- **Model tool-use discipline.** Weak models may loop without converging or never escalate. Mitigation:
  hard cap + a **verbatim-search fallback** so a degenerate trajectory is never *worse* than today's single
  search.
- **`hops=3` cost.** Two-hop BFS can be expensive on a dense graph
  ([`kuzu-bfs-path-explosion-design.md`](kuzu-bfs-path-explosion-design.md)); keep the per-query timeout
  guard.

---

## 11. Implementation sketch (for a follow-up plan, not this doc)

1. Lift `hops` and `include_history` to per-call params on `search_chunk_ids` (default to admin pref).
2. Add the `search_memory` Tool over `GraphitiConversationMemory` (the four knobs; clamp `limit`, bound
   `hops`); **not** agent-default.
3. Build the retrieval-agent node (LangGraph V1 `create_agent`) with the §5.3 prompt, the accumulator
   (§6), and the `MAX_SEARCHES` cap + verbatim fallback.
4. Wire it as the memory-eval recall leg; emit the accumulator as `recalled` and the final message as
   `answer`.
5. Measure **evidence recall** on units 13 & 14 (and the broader BEAM-128k set) as a held-out diagnostic;
   compare against the 44% baseline — **without** tuning to it.

> **To get up to speed after implementing:** changing `graph.k_hop` semantics to per-call needs a **server
> restart**; no re-ingest is required (this is all retrieval-time). No workspace reset needed.
