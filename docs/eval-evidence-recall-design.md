# Evidence Recall — Ground-Truth Retrieval Scoring for the Memory Eval

> **Design doc (proposed).** Add an **objective, ground-truth retrieval metric** to the memory-eval
> track: for LoCoMo-style corpora that ship per-question **evidence episodes**, measure how well our
> `recall` actually surfaced those episodes — both **how much** (coverage) and **how high** (rank).
> This is the ground-truth counterpart to the judge's *subjective* `recall_sufficient` flag, and it
> separates **retrieval** failures from **reasoning** failures on a per-question, per-run basis.
>
> **Companions:**
> [`eval-corpus-tracks-design.md`](eval-corpus-tracks-design.md) (memory vs knowledge tracks, the
> answer+judge scoring),
> [`locomo-conv43-eval-analysis.md`](locomo-conv43-eval-analysis.md) (where an **external** LoCoMo
> harness already computed evidence recall — 37.9% overall; temporal **52.9% evidence recall vs 3% F1**,
> proving the *answering* leg, not retrieval, was the temporal bottleneck), and
> [`eval-recall-tables-split-design.md`](eval-recall-tables-split-design.md) (the recalled
> facts/entities/episodes tables this scores over).
>
> **Mode:** initial development — **no backward compatibility / no migration / no wrappers**
> (repo rule, explicitly abided).
>
> **Status:** **Proposed** — not yet implemented. The id-plumbing and sidecar loading already exist
> (see §3); this doc specifies the metric definitions, the linking rules, and where they plug in.

---

## 1. The one-paragraph version

LoCoMo corpora ship a sidecar (`*.locomo.yaml`) with, per question, the **evidence episodes** that
contain the answer (`evidence.episode_ids` / `dia_ids`). Our memory `recall` already returns a
mixed, ranked list of **facts / entities / episodes**, each carrying a back-pointer to its source
episode. So we can **trace each recalled item back to a source episode id** and compare that set to
the question's evidence — yielding an **objective Evidence Recall** (did we surface the supporting
turns?) that doesn't depend on the LLM judge. Because the answerer is grounded **only** in the
recalled context, with a **top-k cap** and attention that favors earlier items, *where* the evidence
landed matters as much as *whether* it landed — so we also report a **rank-aware** companion
(MRR / first-evidence-rank, optionally nDCG@k). Today this number only exists from an **offline**
external harness; bringing it in-house makes the **retrieval-vs-reasoning** diagnostic a first-class,
per-run signal next to the judge's correctness mark.

---

## 2. Motivation — what the current signals can't tell us

We already grade each memory question with three signals:

| Signal | Source | What it means | Blind spot |
|---|---|---|---|
| **Correct / Score** | LLM judge vs ideal answer | did the model **answer** right | conflates retrieval + reasoning |
| **`recall_sufficient`** flag | judge quotes a line from *what we recalled* | judge **believes** the context held the answer | **subjective**, relative to what was recalled — can't see what was *missed* |
| **Evidence Recall** *(this doc)* | recalled source-episodes ∩ **ground-truth** evidence | did retrieval actually surface the supporting turns | only where a sidecar exists |

The first two can't answer *"was this a retrieval miss or a reasoning miss?"* — the exact question the
[analysis doc](locomo-conv43-eval-analysis.md) had to answer with an **external** harness. Evidence
Recall answers it directly and per-run: low evidence recall + wrong answer ⇒ **retrieval** problem;
high evidence recall + wrong answer ⇒ **answering** problem.

---

## 3. What already exists (so this is small)

- **Ground-truth evidence:** `eval/<id>.locomo.yaml` → `questions[qid].evidence.{episode_ids,dia_ids}`,
  plus an `episodes` map (`episode_id → dia_id`). Only LoCoMo corpora have it.
- **Id plumbing:** a corpus episode `id` (`locomo_conv_43_d1_9`) becomes the Graphiti **episode uuid**
  at ingest, and recall hits carry it back — episode hits as `uuid`, fact hits as `chunk_id`
  (= `episodes[0]`). See `graphiti_search.py` fact-row build and `graphiti_conversation.search`.
- **Trace code:** [`eval_locomo.py`](../hiroserver/hirocli/src/hirocli/services/knowledge/eval_locomo.py)
  already loads the sidecar and maps a row's recalled hits → evidence ids (`_context_dia_ids`,
  `episode_to_dia`) for the LoCoMo **export**. We reuse this mapping for **scoring**.
- **Recall payload:** each hit (`RecalledFact` in `knowledge-events.ts`) has `kind`, `score`,
  `chunk_id`, `uuid` — the fields we need.

So the work is: load evidence per question, compute the metrics from `recalled_rows`, stamp + persist,
and surface in the Report.

---

## 4. Linking evidence to facts / entities / episodes

Evidence is **episode-granular**; the three recall kinds link to a source episode differently:

| Recall kind | Source-episode link | Rule |
|---|---|---|
| **Episode** | ✅ direct | hit `uuid` **==** corpus episode id → exact match |
| **Fact** | ✅ via provenance | the edge stores the episodes it was extracted from; hit exposes `chunk_id = episodes[0]` (first only today — **widen** to the full `episodes` list) |
| **Entity** | ⚠️ none precise | spans many episodes; no specific source episode → **excluded** from evidence matching |

```text
recalled hits ──► source episode id(s) ──► ∩ evidence_episode_ids ──► coverage / rank
  episode  → { uuid }
  fact     → { edge.episodes }      (today only episodes[0]; widen to full list)
  entity   → { }  (skip — no precise provenance)
```

**Decisions:**
- **D1 — Widen fact provenance.** Surface the fact edge's full `episodes` list (available in
  `graphiti_search` before truncation) as `episode_ids` on the hit, so a fact covers *all* its
  supporting episodes, not just the first. Lower-risk alternative: keep `episodes[0]` and accept a
  slight under-count (documented).
- **D2 — Exclude entities** from evidence matching (expanding to "all episodes mentioning the entity"
  adds noise). Entities still count for *answering*, just not for *episode-level* evidence recall.
- **D3 — Match on `episode_ids` directly** (corpus episode id == recall `uuid`/`chunk_id`); no need to
  hop through `dia_ids` for scoring (the export still uses dia for LoCoMo-format output).

---

## 5. The metrics

Let `E` = the question's evidence episode set, and `R` = the **ordered** list of recalled items
(each resolved to its source episode id(s) per §4). Let `hit(e)` = the set of recalled items whose
source episodes include `e`.

### 5.1 Coverage (binary) — the headline

- **Evidence Recall@k** = `|E ∩ recalled_episodes(top-k)| / |E|` — fraction of evidence surfaced in
  the top-k recalled items. `k` defaults to the recall `top_k` (so it reflects what the answerer
  actually saw); we may also report `@all`.
- Per question it's a 0–1 fraction; aggregate as a mean (and as a count `covered/total` per bucket).

### 5.2 Rank-aware — "did important evidence surface higher?"

Because top-k + attention favor early items, reward surfacing evidence high:

| Metric | Definition | Reads as |
|---|---|---|
| **First-evidence rank** | rank of the first recalled item in `hit(e)` for any `e∈E` | "the top evidence hit landed at #r" |
| **MRR** | `1 / first-evidence-rank` (0 if none) | one number; high = evidence near the top |
| **nDCG@k** | position-discounted gain over all `e∈E` | rewards getting **all** evidence high |

For nDCG, gain for evidence episode `e` = `1` at the **best (min) rank** among `hit(e)`, discounted by
`1/log2(rank+1)`; IDCG = perfect ordering of `|E|` evidence at ranks `1..|E|`.

### 5.3 The multi-lane wrinkle (important)

Recall is **three separate ranked lanes** (Facts / Entities / Episodes), each scored independently —
there is no single global rank. So "rank" needs a definition:

- **Option A — Unified by score (recommended):** merge all kinds into one list ordered by `score`,
  rank there. Closest to "what the model sees first," but cross-lane scores aren't perfectly
  comparable.
- **Option B — Episodes lane only:** rank within episode hits. Cleanest for episode-granular
  evidence, but ignores answer-bearing facts that *are* the evidence's content.

Recommendation: **Option A** for the headline rank-aware number, computed over the union (facts +
episodes; entities excluded), with the raw per-lane ranks available in the per-question detail for
debugging.

### 5.4 Worked example

`E = {d1_9, d6_15, d11_17}`, `top_k = 8`. Recalled (score order):
`1 fact→d6_15 · 2 episode d1_9 · 3 entity(John) · 4 fact→d4_3 · 5 episode d11_17 · …`
→ covered `{d6_15, d1_9, d11_17}` ⇒ **Recall@8 = 3/3 = 100%**; first-evidence rank **1** ⇒ **MRR = 1.0**;
best ranks `{d6_15:1, d1_9:2, d11_17:5}` ⇒ **nDCG@8 ≈ 0.92**.

---

## 6. Where it plugs in

### 6.1 Backend (`eval_runner.py`)
- **Load evidence once per run:** resolve the sidecar (`_sidecar_path`) and build `{qid → set(episode_ids)}`
  + the `episode_to_dia` map by reusing helpers from `eval_locomo.py` (lift the load into a shared
  `eval_locomo` function so both export and scoring use one loader).
- **Per question** (`_memory_question`): after `recalled_rows` is built, resolve each row's source
  episode id(s) (§4), compute `evidence_recall`, `evidence_mrr`, (opt) `evidence_ndcg`, and
  `evidence_total`/`evidence_covered`. Stamp them top-level on the row dict (persists in `row_json`,
  so the merged read path gets them for free — same pattern as `is_negative_control`/`answered_at`).
  When no sidecar evidence exists for the qid → leave the fields **absent** (renders `—`).
- **D1** lives in `graphiti_search` (add `episode_ids` to fact rows); everything else is in the runner.

### 6.2 Aggregation (summary)
- Extend `field_breakdown(_rows)` / the overall summary with evidence means **only over questions that
  have evidence** (denominator = questions-with-evidence, not all questions) — mirrors how `recall_ok`
  is denominated by *judged* rows. Surface `evidence_recall_avg`, `evidence_mrr_avg`, and
  `evidence_n` (how many questions had evidence) per bucket.

### 6.3 Frontend (Report + tabs)
- **Report tables:** add an **Evidence Recall %** column (and optional **MRR**) next to the existing
  judge-based **Recall Accuracy** — so you see *judge-believed* vs *ground-truth* retrieval side by
  side. Show `—` / `n/a` where no bucket question has evidence.
- **Per-question (optional):** a small "evidence X/Y @ r1" cell in Answer Details (and/or a sortable
  column), full breakdown in the row's expanded fold (which evidence episodes were hit / missed and at
  what rank).

---

## 7. Scope & limitations

- **LoCoMo corpora only.** Synthetic corpora (`adam_year`, `helix_*`, …) have no sidecar → metric is
  absent there. (Could be authored later, but out of scope.)
- **Fact provenance.** Until **D1** lands, facts contribute only `episodes[0]`; coverage is a slight
  lower bound. Episode-kind hits are exact regardless.
- **Entities excluded** by design (§4 D2).
- **Cross-lane rank** is an approximation (§5.3) — fine for relative comparison across runs/settings,
  not a calibrated absolute.
- **Not the LoCoMo F1.** This scores *retrieval*, not answer text overlap. Token-level F1 (the
  canonical LoCoMo answer metric) is a **separate** addition (see open questions).

---

## 8. Open questions / decisions to confirm

1. **k for @k:** tie to `memory.search.top_k` (what the model saw) vs a fixed `@10`? → default to
   `top_k`, also expose `@all`.
2. **Rank definition:** Option A (unified by score) vs B (episodes lane). → recommend **A**.
3. **Widen fact provenance (D1)** now, or ship with `episodes[0]` and widen later? → recommend **D1**
   (small, removes the under-count caveat).
4. **Also add token-level F1?** Canonical LoCoMo answer metric for leaderboard comparability; our
   golds are comma-lists so tokenization needs care. → **separate doc**, not this one.
5. **Gate impact:** evidence recall is **reporting-only** (no gate), like difficulty. Confirm.

---

## 9. Phasing

- **Phase 1 — coverage:** evidence loader + `evidence_recall` per question + Report column. Smallest
  useful slice; answers retrieval-vs-reasoning.
- **Phase 2 — rank-aware:** add MRR / first-evidence-rank (+ nDCG), per-question detail in the fold,
  and **D1** (full fact provenance).
- **Phase 3 — (optional)** per-question sortable Evidence column in the tabs; author evidence for a
  synthetic corpus if we want non-LoCoMo coverage.

---

## 10. Verification plan

- **Unit (pure):** a scoring helper `evidence_metrics(recalled_rows, evidence_ids, k)` →
  `{recall, mrr, ndcg, covered, total}` with table-driven cases (full hit / partial / miss / empty
  evidence / rank ordering / fact-vs-episode provenance). No DB.
- **Integration:** run `locomo_conv_43` (a subset) after a graph build; spot-check a handful of
  questions against the sidecar + the retrieval trace (`logs/retrieval_trace/*.jsonl`) to confirm the
  resolved source episodes match what the trace shows.
- **Cross-check:** compare in-house Evidence Recall to the **external** harness number quoted in
  [`locomo-conv43-eval-analysis.md`](locomo-conv43-eval-analysis.md) (≈37.9% overall on round-1
  output) — they should be in the same ballpark.
