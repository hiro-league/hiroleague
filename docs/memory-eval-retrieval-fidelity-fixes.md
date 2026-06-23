# Memory-Eval Retrieval — Fidelity & Reduce Fixes

**Status:** remediation plan (pre-implementation). No redesign, no optimization — fix the defects to
their original design intent, then rerun the eval.

**Origin:** trace inspection of run `beam128k_14` (LangSmith public trace
`63fe3d56-d36f-4364-b401-e1c9152e997f`), questions `ie_01` (happy path) and `msr_01` ("how many
unique movies…", a fail). Dump + tooling: `scripts/dump_langsmith_trace.py`,
`../hiro-traces/trace_beam128k_14.json` (trace dumps live outside the repo; see `$HIRO_TRACE_DIR`).

> **Development mode:** no backward compatibility / no migration / no wrappers (project rule). These
> are corrections to a defective in-development feature.

---

## 1. The core problem

The agentic memory-retrieval leg loses data **as it moves between steps**, and the deterministic
`reduce` layer is broken in three independent ways. The net effect: the model that *drives*
retrieval sees less than the model that *answers*, and for count/duration questions the
"deterministic" safeguard either never fires or computes the wrong number.

Two failure shapes were observed:

- **`ie_01` (pass)** — single atomic fact; happy path; gold fact ranked #1. Worked despite the
  defects because no aggregation/temporal reasoning was needed.
- **`msr_01` (fail)** — "how many unique movies across all marathons." Gold = 13. The agent's own
  answer said 14 (built from real catalog titles in entity summaries), and `eval_answer` said 6.
  Neither the data fidelity nor the reduce safeguard worked.

---

## 2. Data-flow map — where fidelity is lost

```
question
  │
  ▼
[agent turn N]  LLM (gpt-5.4)  ── emits search_memory(queries=[…])
  │
  ▼
search_memory tool  (search_tool.py)
  │   memory.search() → graphiti_search.py builds RICH rows:
  │      fact_rows : fact, name(=relation), stated, score, source, [valid_at/invalid_at/superseded]
  │      node_rows : name, summary, entity_type, score
  │      episode_rows: text, valid_at, score
  │
  ├─►  accumulator.merge(RICH rows)         ← FULL fidelity kept here
  │
  └─►  _serialize_item(...) → items to AGENT ← LOSSY: drops relation, entity_type, stated;
                                                valid_at only if show_expiry             [LOSS #1]
  ▼
[final turn]  LLM (gpt-5.4) "retrieval_final" ── declares reduce {op,args} + free-text answer
  │            (declared from the LOSSY tool view)
  ▼
apply_reduce(accumulator, op, args)   (reduce.py)  ← PURE FUNCTION, not an LLM
  │   • items  → filtered to a single kind for distinct_count       ← drops entities/episodes [LOSS #2 / Bug A]
  │   • summary→ count = len(items), no dedup (edge branch)         ← wrong number          [Bug B]
  │   • summary→ omits "op" key for distinct_count                  ← unrenderable          [Bug C]
  ▼
eval_answer  LLM (deepseek-v4-pro)   (judge.answer_question)
  │   • receives recalled rows rendered in eval format ([stated] fact [RELATION · as of · until], NAME (TYPE))
  │   • receives `computed=` → "## Computed Results" via _format_computed_block — but EMPTY for distinct_count (Bug C)
  ▼
eval_judge  LLM (deepseek-v4-pro)
```

**Key asymmetry:** the accumulator (→ reduce → `eval_answer`) keeps the rich rows, but the **agent**
only ever sees the lossy `_serialize_item` output. The decision-maker is blinder than the answerer.

---

## 3. Field & terminology mapping

The graph layer produces every field; the agent-facing serializer drops most, and the two prompts
use different vocabulary for the same thing.

| Concept | Graph row field | `eval_answer` term (target) | Retrieval agent today | Reaches agent today? |
|---|---|---|---|---|
| relation name | `name` (rel_type, e.g. `LIVES_IN`) | `[RELATION]` | — (absent) | ❌ |
| entity type | `entity_type` | `NAME (TYPE)` | — (absent) | ❌ |
| fact said-date | `stated` | leading `[DATE]` / "stated" | — (absent) | ❌ |
| fact became-true | `valid_at` | `as of` | `valid_at` | only if `show_expiry` |
| fact stopped | `invalid_at` | `until` | `invalid_at` | only if `show_expiry` |
| fact retired flag | `superseded`/`expired_at` | (none — implied by `until`) | `superseded` | only if `show_expiry` |
| episode timestamp | `valid_at` (episode) | "stated" | "one timestamp" | ✅ (as `valid_at`) |

**Decisions baked in:** `superseded` is **dropped** (rely on `until`); agent gets **full field
parity** with `eval_answer` (no field drops); vocabulary unifies on `stated` / `as of` / `until` /
`RELATION` / `TYPE`.

---

## 4. The three reduce bugs (all deterministic code, not model)

`reduce.op` is **chosen** by an LLM (the `retrieval_final` turn) but **executed** by a pure function
(`apply_reduce`, `reduce.py`). All three bugs are in the function — reliably reproducible and
unit-testable.

- **Bug A — kinds dropped.** `_distinct_count` returns only `acc.items_by_kind()[target]`
  (`reduce.py:162`). For `distinct_count{kind:edge}`, entities + episodes vanish before
  `eval_answer`. **Fix:** keep all kinds in the items handed to the answerer; the reduce contributes
  a *summary* alongside the full set (annotate, not replace).
- **Bug B — not actually distinct.** Edge branch returns `count = len(items)` (`reduce.py:168`); only
  the entity branch dedupes by name. **Fix:** dedupe by the resolved object (e.g. movie title) so
  `distinct_count` returns a true distinct count.
- **Bug C — summary unrenderable.** `_distinct_count`'s summary dict omits the `"op"` key, while
  `_format_computed_block` dispatches on `op` (`judge.py:275`) → returns `""` → the
  `## Computed Results` section never appears. (This is why `msr_01`'s `eval_answer` got no computed
  number and recounted to 6.) **Fix:** include `"op": "distinct_count"` in the summary so it renders.

> The summary plumbing already exists (`runner_memory.py:485` passes `computed=`; `judge.py:270`
> renders it with *"Use this exact number"*). "Adding the summary" therefore = making it **correct**
> (B), **renderable** (C), and an **annotation over the full set** (A) — plus a prompt clause so the
> answerer trusts it.

---

## 5. To-do list

| # | Item | Site | Change | Why |
|---|---|---|---|---|
| 1 | Surface **relation** to agent | `search_tool.py` `_serialize_item` edge branch (~92) | emit `relation` from row `name` | agent can't tell `PLANS_TO_WATCH` from `IS_AVAILABLE_ON` → `msr_01` over-count |
| 2 | Surface **entity type** to agent | `_serialize_item` entity branch (~110) | emit `entity_type` (row has it, `graphiti_search.py:596`) | agent can't tell catalog entities from subjects |
| 3 | Surface **stated** to agent | `_serialize_item` edge branch | emit `stated` (row has it, `graphiti_search.py:571`) | agent is otherwise date-blind |
| 4 | **Ungate `valid_at`** from `show_expiry` | `graphiti_search.py:558` | always include `valid_at` + `stated`; gate only `invalid_at` (+ drop `superseded`) | `show_expiry=false` blinded `msr_01` to all dates |
| 5 | **Drop `superseded`** field | `graphiti_search.py:558-561`, `_serialize_item` | remove the boolean; rely on `until` | decision 1a; eval vocabulary has no term for it |
| 6 | **Rename to eval vocabulary** | `_serialize_item` keys | `valid_at→as_of`, `invalid_at→until`, episode `valid_at→stated` | one vocabulary across legs |
| 7 | **Align retrieval-agent prompt** | `preferences.py:783-790` (Element formats), `811-819` (Knobs) | describe `stated`/`as of`/`until`/`relation`/`type` to match `answer_prompts` (`preferences.py:586`) | prompt currently names JSON fields and over-promises a shape the payload lacks |
| 8 | **Reduce keeps all kinds** (Bug A) | `reduce.py` `_distinct_count` (160) + `runner_memory.py:279` | hand `eval_answer` the full deduped set; reduce adds a summary, doesn't replace items | answerer was starved to one kind |
| 9 | **`distinct_count` dedupes** (Bug B) | `reduce.py:168` | count distinct resolved objects, not `len(items)` | can't answer "how many unique" today |
| 10 | **`distinct_count` summary sets `op`** (Bug C) | `reduce.py:166-168` | add `"op": "distinct_count"` | otherwise the computed number never renders |
| 11 | **Answer prompt may use Computed Results** | `DEFAULT_MEMORY_EVAL_ANSWER_PROMPT` (in `answer_prompts` default, `preferences.py`) | add a clause: prefer the `## Computed Results` value over recomputing | prompt currently says "raw elements only", which conflicts with the injected computed block |
| 12 | **Prompt↔payload parity test** | new test | assert `_serialize_item` keys == the fields the retrieval prompt names | prevent silent drift like today's |
| 13 | **Field-fidelity test across hops** | new test | assert relation/type/stated/dates survive search → accumulator → reduce → `eval_answer` | the missing-hop class of bug |

### Implementation status

- **Items 1–5: ✅ done.** `_serialize_item` emits `relation`, `entity_type`, `stated`; `valid_at`
  ungated (always surfaced), `invalid_at` behind `show_expiry`; `superseded` dropped from row builder
  + serializer.
- **Items 6–10: ✅ done.**
  - **6 (vocabulary):** agent-facing keys now match the answerer — edge `valid_at→as_of`,
    `invalid_at→until`; episode `valid_at→stated`.
  - **7 (prompt):** retrieval-agent prompt (`preferences.py` default) Element-formats + Knobs +
    P2/N3 rewritten to `relation` / `stated` / `as of` / `until` / entity `type`; the `superseded`
    references are gone.
  - **8 (Bug A):** `_distinct_count` returns the FULL deduped set (all kinds) — no more starving the
    answerer to one kind.
  - **9 (Bug B):** edges dedupe by resolved object (`_edge_distinct_key` → `target_uuid`, fallback
    normalized fact text); entities by name; episodes are uuid-distinct turns.
  - **10 (Bug C):** the `distinct_count` summary now carries `op` so `## Computed Results` renders.
  - Tests: added/updated in `test_search_tool.py`, `test_graphiti_search.py`, `test_reduce.py`;
    full memory + eval + graph + domain suites green (348 + 134 passed).
- **Item 9 decision (resolves the §8 open item):** "distinct edge" = distinct **relation target**
  (`target_uuid`), i.e. the object the fact is about. This is deterministic and beats `len(rows)`,
  but it is **not type-filtered** — it counts distinct objects of any type, not "distinct movies".
  A typed count (e.g. `distinct_count` scoped to entities of a given type) is a larger change, left
  out of scope. ⚠️ **Consequence:** `msr_01` may still not land exactly on 13 via
  `distinct_count{kind:edge}` — reaching the gold also needs the model to pick the right
  kind/relation (helped by items 6–7) and, ultimately, typed counting. Confirm at rerun (§9).
- **Items 11–13: ✅ done.**
  - **11 (answer-prompt clause):** `DEFAULT_MEMORY_EVAL_ANSWER_PROMPT` now instructs the answerer to
    report a `## Computed Results` value (count/duration/tallies) verbatim instead of recomputing —
    so the deterministic reduce result is actually trusted.
  - **12 (parity test):** `test_serialized_field_names_documented_in_retrieval_prompt` asserts every
    metadata field the agent receives (`relation`/`stated`/`as_of`/`until`/`entity_type`) is
    documented by exact name in the retrieval prompt — guards against the silent prompt↔payload
    drift that caused the original bug.
  - **13 (cross-hop fidelity test):** `test_recall_metadata_survives_search_to_answer_render`
    asserts relation/type/stated/as_of/until and all three element kinds survive accumulator →
    reduce → recall-row → answer render.
- **Polish (findings 1–3 from the code review): ✅ done** — prompt uses literal JSON keys
  (`as_of`/`until`/`entity_type`), "always shown" softened to "when present", and the base
  `"Entity"` type label is dropped as noise.
- **Findings 4 (computational answers feed all kinds): expected, watch at rerun.**
- **Still dead, clean up later (touches prefs + admin UI, so deferred):**
  `RecallRenderOptions.show_superseded` (`judge.py:85`) and the `graph.eval.show_superseded` pref —
  no row carries `superseded` anymore, so the toggle is inert.
- **All 13 items + review polish landed.** Remaining work is the **§9 verification rerun**
  (`ie_01` regression + `msr_01`), not code.

---

## 6. Decisions (from review)

1. **`superseded` → drop** (rely on `until`). *(item 5)*
2. **Full field parity, no drops** — the agent sees the same fields used for answering; no token
   optimization on a defective feature. *(items 1-3, 6)*
3. **Fix to original design, no redesign/optimization** now — correct the defects, then rerun.
4. **Default profile only** — edits target the built-in `default` prompt text; existing saved
   workspace copies are out of scope.
5. **Add the summary** — keep all kinds (annotate) + make `distinct_count` correct + let the answer
   prompt trust the Computed Results. *(items 8-11)*

---

## 7. Out of scope (explicitly)

- No reduce-layer redesign; no new ops; no token/latency optimization.
- No change to the search/rerank engine, retrieval ranking, or the corpus.
- No backward-compat shims (dev mode).
- The other 18 questions / the 20-question aggregate are a **separate** verification pass (see §9),
  not part of this fix.

---

## 8. Open items to confirm before/while implementing

- **Original-design check for Bug A:** confirm in the agentic-memory-retrieval design (the `§6.1` the
  reduce module cites) that "keep all kinds + annotate with summary" matches intent, vs. a deliberate
  single-kind reduction. Decision 5 already chooses annotate; this is a faithfulness check, not a
  re-decision.
- **`distinct_count` dedup key:** what defines "distinct" for an edge — the fact's object entity
  (target node), or a normalized title string? (Affects Bug B fix.)

---

## 9. Verification plan (after fixes)

1. Re-run `ie_01` — must stay pass (regression guard for the happy path).
2. Re-run `msr_01` — with relation/type/stated visible, all kinds kept, and a correct + rendered
   `distinct_count`, the answer should reach the gold (13) deterministically.
3. New unit tests: items 12 and 13.
4. Only then consider the broader 20-question rerun to see if the count/temporal-axis fixes
   generalize.

---

## Appendix — reference sites

- Agent-facing serializer: `services/memory/agent/search_tool.py` `_serialize_item` (86-133)
- Rich row builder + `show_expiry` gate: `services/knowledge/graph/graphiti_search.py` (495-641; gate at 558)
- Reduce primitives: `services/memory/agent/reduce.py` (`apply_reduce` 40; `_distinct_count` 160)
- Reduce wiring + summary pass-through: `services/eval/runner_memory.py` (257-285, 485)
- Computed-block render: `services/eval/judge.py` (`_format_computed_block` 270; assembly 334-343)
- Retrieval-agent prompt default: `domain/preferences.py` (773-884)
- Answer-prompt vocabulary: `domain/preferences.py` (586-593) + `answer_prompts` default
