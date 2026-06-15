# LoCoMo conv-43 — Memory Eval Failure Analysis (Rounds 1–2)

Working analysis of the memory-track eval on the `locomo_conv_43` corpus (680 turns, 242 questions
in round 2 / 57 in round 1). All claims below were verified against the run byproducts — persisted
results (`<workspace>/knowledge/eval_results.db`), per-stage retrieval traces
(`<workspace>/logs/retrieval_trace/*.jsonl`), and direct Kuzu graph queries (server stopped) — not
from samples. Date: 2026-06-11.

---

## 1. Round history

| | Round 1 (57 q) | Round 2 (242 q) |
|---|---|---|
| Correct | 5/57 = **9%** | 119/242 = **49%** |
| Score (partial = ½) | 24% | **56%** |
| Correct excl. adversarial | — | 108/178 = **61%** |
| Abstains | 34/57 (60%) | 15/242 (**6%**) |
| Dominant failure | abstain (recall starvation) | wrong answer (concentrated in adversarial) |

Round-2 changes that produced the jump:
- `graph.sim_min_score` 0.6 → **0.3** (revived the cosine/meaning candidate leg — in round 1 it was
  effectively dead: ≤3 candidates for 36/57 questions, so retrieval ran on BM25 alone)
- `graph.search_scope` `edges_and_nodes` → **`edges_nodes_episodes`** (raw turn text now recalled)
- `graph.k_hop` 2 → **3** (note: round 1 actually ran at k_hop=2 per traces; hops were never the
  bottleneck — hop expansion saturated its cap in every trace)
- Relaxed answer prompt (commit / partial answers / resolve relative dates / paraphrase OK)

Reference points: published graphiti LoCoMo ≈ 60–70%. Standard LoCoMo scoring **excludes**
adversarial (category 5) — our 61%-excl-adversarial is the comparable number. External LoCoMo
harness on round-1 output: QA F1 5.88%, evidence recall 37.9% (temporal: 52.9% evidence recall vs
3.0% F1 → proved the answering leg, not retrieval, was the temporal bottleneck).

## 2. Round-2 results by category

| Category | n | pass | partial | fail | abstain | correct% |
|---|---|---|---|---|---|---|
| single_hop | 107 | 85 | 6 | 14 | 2 | **79%** |
| temporal | 26 | 13 | 7 | 5 | 1 | **50%** (was 19%) |
| multi_hop | 31 | 8 | 19 | 3 | 1 | 26% (mostly partials now) |
| open_domain | 14 | 2 | 3 | 7 | 2 | 14% (knowledge-gated, see §5) |
| adversarial | 64 | 2 | 0 | **53** | 9 | **17%** ← biggest drag |

Difficulty: medium 79% · hard 25%.

## 3. Failure taxonomy — all 123 failing rows classified (no sampling)

| # | Pattern | Rows | Stage | Example evidence |
|---|---|---|---|---|
| P1 | **Negative controls answered** (43 invented/wrong-source + 10 explicit John→Tim transfer) | **53** | answer | "Which team did Tim sign with?" → "John signed with the Minnesota Wolves" |
| P2 | **Incomplete lists** — items present in recalled context, answer names a subset | **~17** | answer | q022 gold Seattle/Chicago/NY → answered NY+Chicago; Seattle WAS in context |
| P3 | **Wrong-item selection** — right fact in context, model answered a related-but-wrong one | **~12** | answer | q087 Skype topic → answered NYC pic; q165 French vs Spanish; q057 answered the *mention* date (Dec) for a *start* date (Aug) |
| P4 | **Unresolved relative dates** — answer is "Next month." / "Last week." / "Last summer." / "Friday." where gold wants an absolute date | **7–9** | answer | q061: answered **"Last Friday before 2023-12-11"** — anchor date literally in the output, one arithmetic step short. 7 of 13 temporal non-passes |
| P5 | **True recall misses** — gold genuinely absent from the ~58 recalled items | **25** | retrieval | q025 Chicago, q041 NC/Tennessee |
| P6 | **Knowledge-gated open_domain** (overlaps P5) — answer requires world knowledge the grounding guard forbids | ~7 | by design | Hatha Yoga, John Williams, House of MinaLima |

**~70% of all failures (P1–P4, ~85 rows) are answer-stage** and addressable in one prompt revision
with no re-ingest. P5 is the retrieval-bridging frontier. P6 is a scoring-scope decision.

## 4. Verified findings (the load-bearing facts)

1. **Ingestion & extraction are healthy.** 680/680 episodes ingested contiguously. Direct Kuzu
   queries (server stopped) show even implicit references extracted — "I even have the whole
   collection!" → fact `John owns the whole Harry Potter movie collection`. The round-1 "missing"
   gold facts (sneakers, jerseys, soup, honey-garlic chicken, Alchemist, Nike/Gatorade,
   California/London/Smoky) all exist in the graph.
2. **Round-1 root cause was candidate starvation, not ingestion**: `sim_min_score=0.6` killed the
   cosine leg (the exact value `graphiti_search.py`'s docstring warns about); gold facts existed but
   never entered the reranker pool. Fixed in round 2.
3. **Passes are genuine.** All 110 round-2 passes verified: 105 have gold content token-present in
   the recalled context; the 5 outliers eyeballed = legitimate derivations (e.g. "2018" computed
   from "surfing five years" + 2023 context; "≈3.5 months" from an Aug-21 start). No hallucinated
   passes found.
4. **`recall_sufficient` is unreliable as currently produced.** Round 2: 69/110 passes flagged
   `recall_sufficient=False` (logically inconsistent); round 1 had ~25–30% false "sufficient" claims
   (judge asserted facts were in context when they weren't — worst on counting, multi-item list, and
   date golds). Treat as advisory until the quote-verify fix (§6.3) lands.
5. **Adversarial questions are an entity trap by design**: all 64 ask about *Tim* doing things
   *John* did. The model retrieves John's real fact and transfers it. Cross-person leakage also
   appears in answerable rows (q107 Edinburgh, q137 wrong speaker).
6. **Decline-phrase mismatch with the LoCoMo convention**: our prompt's exact decline is
   "I don't know"; LoCoMo's adversarial gold is "No information available in the conversation."
   Internal abstain detection keys on `startswith("i don't know")`
   (`eval_judge.answer_from_context`), so changing the phrase requires updating that detector too.

## 5. Open decision — open_domain scoring

open_domain golds (Hatha Yoga, John Williams, Good Sports…) are not in the corpus; answering them
requires world knowledge the grounding guard forbids **by design**. Options: (a) keep the guard and
report open_domain as its own out-of-scope line (recommended — protects the integrity of every other
category), or (b) relax grounding for that category only (reintroduces the hallucination class).

## 6. Proposed fixes — ordered by rows closed per unit cost

### 6.1 Answer-prompt revision (targets P1–P4, ~85 rows; one edit, no re-ingest)

> **IMPLEMENTED 2026-06-12 (P1 + P4 + 6.2).** Deep re-analysis of all 53 P1 rows split them into
> 27 cross-person transfers, ~18 same-person premise-upgrades, ~7 conversational-role inflations —
> with 39/53 answers stripping the subject to hide the mismatch; root cause was the prompt's own
> "decline only when NOTHING relates" + unconditional-commit pair. All 8 P4 rows had the anchor
> date on the same line as the relative phrase (pure answer-stage). The default answer prompt is
> now a markdown instruction block (Objective / Core / Positive+Negative Calibrators / Formatting /
> Validation) with support gates, absolute-date rules, and SYNTHETIC calibrator examples (never
> benchmark rows), placed in the USER message followed by `## User Question` and
> `## Recalled Memory Elements` (### Relevant Facts / Entities / Messages); the system prompt is a
> hardcoded two-line role. Decline phrase is now "No information available." and the abstain
> detector accepts both phrases (6.2 done). P2's list re-scan and 6.3/6.4 remain open.

Current prompt already *says* "resolve relative time" and "collect every item" — demonstrably too
soft. Make the rules hard:

1. **Date output rule (P4):** never answer with a relative time phrase ("next month", "last week",
   "Friday"); always convert using the item's date and state the absolute date or month + year.
2. **Entity gate (P1):** before using an item, confirm it is about the person asked; if no item
   shows that person doing/having what's asked, reply exactly **"No information available."**;
   never transfer one person's action/deal to another.
3. **No-invention (P1):** never state a name, number, date, or place that appears in no item.
4. **Mandatory re-scan for lists (P2):** before finalizing a list/count answer, re-scan ALL items
   once for additional matches; include every supported item.
5. **Question precision (P3):** answer the exact thing asked — the event (not when it was talked
   about), the person asked (not the other speaker), the specific item (not a related one).

Keep: grounding guard, partial answers, commit behavior. The decline trigger is entity-conditional —
not the round-1 blanket decline.

### 6.2 Decline-phrase alignment

Switch decline string to "No information available." in the prompt **and** update the abstain
detector in `eval_judge.answer_from_context` to recognize both phrases. Same semantics, LoCoMo
convention, keeps the ledger decision correct.

> **Judge updates 2026-06-12.** (a) DeepSeek THINKING mode 400s on the forced tool_choice that
> langchain's default `with_structured_output` sends ("Thinking mode does not support this
> tool_choice"); fixed via `model_factory.with_structured_output_compat`, which falls back to
> `method="json_mode"` for DeepSeek-thinking models (verified live). json_mode never sees pydantic
> field descriptions, so the judge prompt's `## Output Fields` section is load-bearing.
> (b) `DEFAULT_MEMORY_EVAL_JUDGE_PROMPT` rewritten in the same markdown structure as the answer
> prompt (Objective / Verdicts / Core Instructions / Output Fields / Validation); the judge human
> message is now Question / Ideal Answer / Negative Control / Model Answer, with the recalled
> elements LAST; abstain wording keys on "No information available.".

### 6.3 Judge quote-and-verify (makes validation trustworthy; no score impact)

Add one `evidence: str` field the judge must fill with the exact recalled line supporting its
verdict; code verifies the quote is a substring of the shown context, else forces
`recall_sufficient=False`. Optional cheap calibration borrowed from the reference LoCoMo judge:
date tolerance (right month = match), paraphrase = match, evidence-only-to-accept. No bigger judge
model, no reasoning mode — not warranted by the evidence.

### 6.4 Retrieval bridging (P5, 25 rows; design-first before touching the recall path)

Facts exist in the graph but paraphrase-distant/aggregation queries don't surface them ("piano
theme" ↛ Philosopher's Stone fact). Options to design: multi-query recall (entity-anchored
subqueries, merge + rerank); reuse the knowledge track's rewrite-node pattern for memory recall;
chronological ordering of recalled items in the answer prompt (cheap); near-duplicate dedup of
recalled items (cheap). All knobs land as admin prefs per repo convention.

### 6.5 No action needed

Extraction/ingestion (verified healthy). k_hop (saturates; not the bottleneck). Judge model
upgrade (errors were grounding, not grading).

## 7. Reproduction notes

- Per-question rows: `knowledge/eval_results.db` → `memory_eval_results.row_json`
  (recalled facts/entities/episodes + answer + judge mark/reason + recall_sufficient + gold).
- Per-stage retrieval traces: `logs/retrieval_trace/memory_eval_q-locomo_conv_43-*.jsonl`
  (candidate counts per leg: bm25 / cosine / bfs / hop / rank / temporal — this is where the
  round-1 cosine starvation was proven).
- Graph ground truth: `knowledge/graph/graphiti_kuzu.db`, group `eval_mem_locomo_conv_43`
  (server must be stopped; tables: `Episodic`, `Entity`, `RelatesToNode_`).
- Corpus: `eval/locomo_conv_43.episodes.jsonl` (+ `.questions.yaml`); first line is a `#` comment.
- **Evidence recall (UI, since 2026-06-12):** the Answer Details table shows an `Ev` column = X/Y gold
  evidence episodes the recall covered (LoCoMo calculation — a gold episode counts if any recalled
  item maps to it via `chunk_id`/`episode_id`/`source_episode_id`/`uuid`, i.e. raw episode OR a
  derived fact/entity), and the expanded fold lists each gold episode (text + matched/missed + via).
  Computed on the read path (`GET /knowledge/eval/results`) from saved `recalled` + the
  `.locomo.yaml` sidecar — no re-run needed; aggregate over the round-2 saved set = **213/343 ≈
  62%** (vs the external harness's round-1 37.9%). Code: `eval_locomo.compute_evidence_recall_map`.
