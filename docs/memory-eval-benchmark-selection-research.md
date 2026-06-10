# Memory-Eval Benchmark Selection — Research & Recommendation

> **Research / decision note (2026-06-11).** Which long-term / agent-memory benchmark
> should Hiro's memory eval adopt **next**, beyond the current `locomo_conv_43` corpus?
> Scored on three axes: **(A) actual adoption** (what production memory systems and 2026
> surveys really report on), **(B) supersession-relevance** (Hiro's differentiator: temporal
> KG with `valid_at`/`invalid_at`, latest-wins, stale facts must not surface), and **(C)
> practicality** for a graph-episode ingestion pipeline — strongly preferring an
> **amortizable "one shared corpus, many questions"** structure over **per-question
> haystacks** that rebuild the memory graph for every question.
>
> **Headline:** adopt **MemoryAgentBench** next. It is the only benchmark that clears all
> three bars — amortizable, tests supersession (Conflict Resolution / latest-wins), and is
> actually used (ICLR 2026 + recurs in 2026 surveys). Keep **LoCoMo** (have it) and a
> **LongMemEval** subsample for comparability; steal **Memora/FAMA's** metric for the
> supersession differentiator.
>
> **Method:** two adversarially-verified deep-research passes (3-vote per claim, 2/3 to
> refute) + cost analysis from the live workspace ledger. Sources cited inline; caveats in §7.
>
> **Companions:** [`eval-corpus-tracks-design.md`](eval-corpus-tracks-design.md) (the
> two-track memory/knowledge eval this feeds), [`conversation-memory-stress-corpus-design.md`](conversation-memory-stress-corpus-design.md)
> (the home-grown `helix_memory_stress` corpus this complements).

---

## 1. The one-paragraph version

LoCoMo is fine as a cheap regression but barely tests supersession (rated **0.0 memory
mutations** by Memora's survey) and is only 10 conversations. LongMemEval has excellent
supersession + abstention coverage but is a **per-question haystack** — each of its 500
questions ships its own ~40-session / ~115k-token history, so the graph must be **rebuilt
per question**. On Hiro's measured ingest economics that is **~$1,400–2,600 and days of
ingestion** for `_S` alone — non-viable. **MemoryAgentBench** breaks the tie: it is
**amortizable** ("inject once, query many"), has a dedicated **Conflict Resolution**
competency that is exactly latest-wins supersession, and has real 2026 traction.

## 2. Why we revisited the benchmark choice

Two prior concerns motivated this:

1. **The Zep critique of LoCoMo** ([blog](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)):
   cross-vendor SOTA mis-measurement, data-quality issues, category-5 (adversarial) ground
   truth gaps. Conclusion: LoCoMo is fine as an **internal, judge-graded, retrieval-gated
   regression** (which is how Hiro uses it) but weak as a published leaderboard, and Hiro
   already neutralizes the worst parts (LLM judge, curated abstention ground truth).
2. **The context-window objection:** LoCoMo (~17k tokens) fits in any modern context window,
   so a full-context oracle beats memory on accuracy — memory's value on LoCoMo is
   cost/latency, not accuracy. The benchmark never enters the >context regime memory exists
   for. This pushed us to look for a benchmark that genuinely exceeds context **and** is
   affordable to ingest.

## 3. Selection criteria (and the practicality constraint that decides it)

The deciding axis for Hiro is **corpus structure**, because ingestion is the dominant cost:

| Structure | Cost behavior on Hiro's graph pipeline |
|---|---|
| **Amortizable** (one corpus → many questions) | Ingest once, query many. Fits Hiro's `episodes.jsonl` + `questions.yaml` model. **Cheap.** |
| **Per-question haystack** (one history per question) | N graph build/wipe cycles. Zero amortization. **Expensive, fights the harness.** |

### Measured ingest economics (from the live workspace ledger)

Pulled from `knowledge/eval_results.db` and `logs/graph.log` (workspace `default`, runs dated
2026-06-10):

| Metric | Measured value |
|---|---|
| Ingest cost / episode | **~$0.0035** ($0.1376 for 40 LoCoMo episodes); ~$0.0044 full-pipeline |
| Ingest time / episode | **~8–10 s** (episode node avg 7.8 s) |
| QA / question (recall + answer + judge) | ~$0.004–0.007 (negligible vs ingest) |

### What that implies for LongMemEval_S (per-question haystack, ~1,000 episodes/question)

| | Per question | Full `_S` (500 Q) |
|---|---|---|
| Episodes to ingest | ~1,000 | **~500,000** (range 400k–750k) |
| Ingest cost | ~$3.50 | **~$1,750** (range ~$1,400–2,600) |
| Ingest wall-time | ~2.5 hrs | ~5 days @ 10× parallel / weeks sequential |
| Graph build/wipe cycles | 1 | **500** |

This is why LongMemEval is **not** a drop-in for Hiro despite its semantic fit — and why
amortizability is weighted as heavily as adoption and supersession.

## 4. Ranked shortlist (adoption × supersession × amortizable)

| Benchmark | Adoption | Supersession | Amortizable? | Verdict for Hiro |
|---|---|---|---|---|
| **MemoryAgentBench** | Med, rising (ICLR'26, surveys) | ✅ Conflict Resolution (latest-wins) | ✅ inject-once / query-many | **★ Adopt next** |
| **LoCoMo** | ✅✅ highest (Mem0/Letta/Zep) | ❌ 0.0 mutations | ✅ 10 shared convos | **Keep** as cheap regression |
| **LongMemEval** | ✅✅ highest (Mem0 suite) | ✅ Knowledge Updates | ❌ per-question haystack | **Subsample only** (~40 Q) |
| **BEAM** | ✅ Mem0 official suite | ✅ Knowledge-update + Contradiction + Abstention | ✅ shared conv, ~20 Q each | **Defer** (10M-token scale) |
| **Memora / FAMA** | ❌ ~zero (Apr 2026) | ✅✅ purpose-built (FAMA metric) | ✅ shared persona histories | **Best-for-supersession, unproven** |
| Long-context (RULER, NoLiMa, HELMET, LongBench, InfiniteBench, NarrativeQA) | — | — | — | **Ignore** — context-window, not memory |

## 5. Per-benchmark findings

### MemoryAgentBench — **adopt next**
- **What/where:** arXiv [2507.05257](https://arxiv.org/pdf/2507.05257) (ICLR 2026, UCSD / McAuley lab); code [HUST-AI-HYZ/MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench); public HF data.
- **Structure (amortizable):** README verbatim — *"one long text corresponds to multiple
  questions… split into chunks to simulate real multi-turn interaction"*, *"inject once,
  query multiple times."* No per-question graph rebuild.
- **Supersession:** dedicated **Conflict Resolution** competency — *"detect and resolve
  contradictions between existing knowledge and newly acquired information… prioritize later
  information in case of conflict… reason based on the final memory state"* — backed by the
  **FactConsolidation** dataset (MQUAKE counterfactual edit chains). This is latest-wins.
- **Competencies:** Accurate Retrieval, Test-Time Learning, Long-Range Understanding,
  Conflict Resolution. Built for RAG / external-memory agents → fits Hiro's retrieval-gated,
  LLM-judge harness.
- **Positioning:** its paper explicitly rejects RULER/HELMET/InfiniteBench/NoLiMa/LongBench
  as long-context (not memory) benchmarks.

### LoCoMo — keep as regression
- arXiv [2402.17753](https://arxiv.org/abs/2402.17753); data [snap-research/locomo](https://github.com/snap-research/locomo).
- **Amortizable** (10 shared multi-session conversations, many QA/event-summary tasks each;
  reduced from 50 to keep the longest high-quality dialogues). De-facto adoption standard.
- **But** barely tests supersession — Memora rates it **0.0 memory mutations**; survey
  [2602.05665](https://arxiv.org/pdf/2602.05665) flags that interaction benchmarks "lack
  explicit supervision for memory updates when dealing with conflicting facts."

### LongMemEval — subsample only
- arXiv [2410.10813](https://arxiv.org/abs/2410.10813) (ICLR 2025); code [xiaowu0162/longmemeval](https://github.com/xiaowu0162/longmemeval).
- Five abilities incl. **Knowledge Updates** (address change supersedes old) + **Abstention**
  (30 false-premise instances) — genuine supersession/abstention fit.
- **Per-question haystack** (~40 sessions / ~115k tokens for `_S`, ~500 sessions for `_M`,
  only 1–3 relevant). Structurally the exact cost in §3. Use as a **~40-question stratified
  subsample** (~$150) for the abilities we care about, not the full 500.

### BEAM — defer
- arXiv [2510.27246](https://arxiv.org/abs/2510.27246) (ICLR 2026); code [mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks), [mohammadtavakoli78/BEAM](https://github.com/mohammadtavakoli78/BEAM).
- **Amortizable** (shared conversation, ~20 probing questions each). 100 conversations,
  2,000 questions, size buckets 128K/500K/1M/10M tokens. 10 abilities incl. **Knowledge
  update**, **Contradiction resolution**, **Abstention**, Temporal reasoning, Event ordering.
- In Mem0's official suite (real adoption) but the **10M-token tier needs scale infra**
  beyond the current chat-session harness. Revisit when that infra exists.
- *Verifier note:* "substantially larger than LoCoMo/LongMemEval" was **refuted** as
  overreach — its absolute scale figures hold, the comparative framing does not.

### Memora / FAMA — best for supersession, unproven
- arXiv [2604.20006](https://arxiv.org/html/2604.20006v1) ("From Recall to Forgetting", ACL 2026 Findings).
- **Purpose-built for supersession:** quantifies **memory mutation** (updates/deletions per
  history) — **8.8 (monthly)** vs LoCoMo 0.0, LongMemEval 2.0, PersonaMem 1.2 — and
  introduces **FAMA (Forgetting-Aware Memory Accuracy)**, which *penalizes answers relying on
  stale/invalidated facts* (88.3% agreement with human judgments). **Amortizable**
  (shared per-persona histories), abstention-aware, non-destructive supersession.
- **Catch:** April-2026 preprint, **zero third-party adoption**, numbers are the lab's own.
  **Action:** adopt the **FAMA metric idea into Hiro's judge** now (it directly scores "stale
  fact must not surface"); watch the dataset's adoption before committing to it wholesale.

### What to ignore
- **Long-context benchmarks** (RULER, InfiniteBench, NoLiMa, HELMET, LongBench, NarrativeQA):
  context-window, not memory-system, benchmarks.
- **Watch-list only** (survey enumerations, little cross-lab adoption): MemoryArena,
  MEMTRACK, MemSim, MMRC, StoryBench, RealMem, DialSim, MADial-Bench.

## 6. Industry signal — no single standard

- **Mem0's** official eval suite is exactly three: **LoCoMo + LongMemEval + BEAM**
  ([mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks); reported 91.6 /
  94.8 / 64.1@1M).
- **Letta** runs its **own synthetic Memory Read / Write / *Update*** tasks for its
  leaderboard ([letta.com/blog/letta-leaderboard](https://www.letta.com/blog/letta-leaderboard)),
  where *Memory Update* tests conflicting-fact latest-wins — i.e. supersession. Serious
  memory teams build custom supersession evals. **Hiro's `helix_memory_stress` corpus is the
  same instinct** and should keep growing alongside any adopted benchmark.

## 7. Recommendation

1. **Adopt MemoryAgentBench next** — amortizable + supersession + actually used.
2. **Keep LoCoMo** as the cheap regression; run **LongMemEval only as a ~40-Q subsample** for
   comparability with the field.
3. **For the supersession differentiator:** integrate a **FAMA-style metric** into the judge
   (credit "invalidated fact correctly withheld", not just answer correctness). Optionally
   adopt the Memora dataset once it shows third-party adoption.
4. **Keep investing in `helix_memory_stress`** — a home-grown, amortizable, supersession-
   targeted corpus is the cheapest precise signal and matches what Letta/others do.
5. **Defer BEAM** until extreme-scale ingestion infra exists.

### Open integration question (bounded harness work)
MemoryAgentBench ingests as a **chunked incremental stream**, not LoCoMo's per-conversation
JSON. Before committing: verify FactConsolidation maps onto `episodes.jsonl` + sidecar, and
that Conflict-Resolution scoring (credit *stale-fact suppression*) fits `eval_judge`. This is
the one real adapter task — scope it against `eval_runner` / `eval_judge`.

## 8. Caveats

- **Fast-moving space (2025–2026).** MemoryAgentBench (Jul 2025 / ICLR 2026), BEAM (Oct 2025),
  Memora (Apr 2026) and the two surveys (Feb 2026) are recent; their cross-lab adoption is
  thinner than LoCoMo/LongMemEval.
- **Memora's supersession superiority rests on the originating lab's own table** — design
  intent, not independently validated.
- **Minor verified errors in the research:** EventQA was mis-attributed to MemoryAgentBench's
  Conflict Resolution (it serves Retrieval/Long-Range; CR is FactConsolidation only) —
  non-load-bearing; "canonical" for LoCoMo/LongMemEval is a gloss but enumeration- and
  adoption-supported.
- **Not individually verified:** what Zep/Graphiti, cognee, Memobase, MemMachine, Supermemory
  report on — strongest hard adoption signals are Mem0's three-benchmark suite and the Letta
  leaderboard.

## 9. Sources

- MemoryAgentBench — [paper 2507.05257](https://arxiv.org/pdf/2507.05257) · [code](https://github.com/HUST-AI-HYZ/MemoryAgentBench)
- LoCoMo — [paper 2402.17753](https://arxiv.org/abs/2402.17753) · [code](https://github.com/snap-research/locomo)
- LongMemEval — [paper 2410.10813](https://arxiv.org/abs/2410.10813) · [code](https://github.com/xiaowu0162/longmemeval)
- BEAM — [paper 2510.27246](https://arxiv.org/abs/2510.27246) · [Mem0 suite](https://github.com/mem0ai/memory-benchmarks) · [code](https://github.com/mohammadtavakoli78/BEAM)
- Memora / FAMA — [paper 2604.20006](https://arxiv.org/html/2604.20006v1)
- Mem0 benchmark suite — [mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks)
- Letta Leaderboard — [letta.com/blog/letta-leaderboard](https://www.letta.com/blog/letta-leaderboard)
- 2026 agent-memory surveys — [2602.05665](https://arxiv.org/pdf/2602.05665) · [2603.07670](https://arxiv.org/pdf/2603.07670)
- Zep LoCoMo critique — [blog.getzep.com](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
