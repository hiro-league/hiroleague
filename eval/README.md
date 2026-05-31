# L3 prototype eval

The Phase 4 proceed-or-pivot gate for the knowledge graph prototype
(see [`docs/knowledge-l3-prototype-plan.md`](../docs/knowledge-l3-prototype-plan.md)).

Runs a fixed set of personal-data questions against ingested synthetic
content twice — `use_graph=False` (today's flat hybrid+rerank) vs
`use_graph=True` (the new L3 path) — scores both, prints a side-by-side
table, and ends with a single PROCEED / PIVOT verdict.

## Files

| File | Purpose |
|---|---|
| `l3_synthetic/*.md` | Generated personal corpus — family / places / events / two-Ahmeds / Arabic. Designed so flat RAG struggles on multi-hop while staying answerable end-to-end. |
| `l3_questions.yaml` | ~12 questions with `expected_fragments` + `requires_graph` flags. The `requires_graph: true` subset is what the gate measures. |
| `l3_synthetic_eval.py` | Self-contained harness — ingests the corpus, builds the graph, runs each question twice, prints the table + gate. |
| `test_l3_synthetic_eval.py` | Pure-logic unit tests (scoring / rendering / gate math). Run with `pytest eval/`. |

## Prerequisites

The harness makes real LLM calls — it needs a workspace with providers
configured:

1. A registered Hiro workspace (just need its path; the harness doesn't
   look at the registry).
2. `knowledge.answering.model` (or `llm.default_chat`) set in the
   workspace's `preferences.json` to a catalog chat model id, e.g.
   `openai:gpt-5-mini`.
3. The matching provider API key configured for the workspace (the
   harness will fail loud with a clear message if it can't resolve the
   model — no silent degradation).
4. Default knowledge embedder works as-is (FastEmbed MiniLM downloads
   ~220MB on first ingest).

## Run

From the repo root:

```bash
# First run — ingests the corpus + builds the graph + runs all questions.
python eval/l3_synthetic_eval.py --workspace /absolute/path/to/your/workspace

# Subsequent runs against the same workspace — skip the (expensive) ingest:
python eval/l3_synthetic_eval.py --workspace /path --skip-ingest

# See every full answer (long output):
python eval/l3_synthetic_eval.py --workspace /path --skip-ingest --show-answers
```

The harness will:

1. **Ingest** every `eval/l3_synthetic/*.md` into the workspace's
   knowledge index via the standard `KnowledgeService.ingest_and_wait`.
2. **Build the graph** by running `GraphIngestService.ingest_chunks` on
   each document's chunks (one LLM extraction call per chunk + optional
   per-mention disambiguation calls). Watch the per-doc stats line for
   token usage. Per-chunk ledger rows land in `workspace/logs/graph.log`
   (and in the admin Graph Runs view) — see plan §2b.
3. **Ask every question twice** — `use_graph=False` and `use_graph=True`
   — both with `rewrite=True` (graph_expand needs the rewrite step's
   `entities[]` output).
4. **Print** a side-by-side `flat | graph | Δ` table plus a summary that
   answers: did graph-on win on the `requires_graph: true` subset?

## Cost expectation

Tiny corpus (~7 docs, ~15–25 chunks total) plus ~12 × 2 questions.
With `openai:gpt-5-mini`:

- **Ingest** (one-time per workspace): ~$0.05–$0.20 — dominated by the
  one extraction call per chunk.
- **Per question run** (per mode): ~$0.001–$0.01 — dominated by the
  answer LLM call. So a full 12-question × 2-mode run is sub-cent to a
  few cents.

Re-runs with `--skip-ingest` only cost the question pass.

## Reading the output

```
▲ | id                            | category                        | question                                                | flat | graph | Δ
--+-------------------------------+---------------------------------+---------------------------------------------------------+------+-------+----
▲ | relational_2hop               | relational/multi-hop            | What does my sister's husband do for work?              | ✗    | ✓     | +3
  | relational_1hop_alias         | relational/1-hop+alias          | Who is Lina's husband?                                  | ✓    | ✓     | 0
▲ | alias_bare_kinship            | alias                           | Where does mom live?                                    | ✗    | ✓     | +3
…
```

The `▲` column marks questions tagged `requires_graph: true` — those are
the ones the L3 thesis actually predicts the graph should win.

| Mark | Meaning |
|---|---|
| ✓ | All expected fragments found in the answer |
| ◐ | Some fragments found (partial answer) |
| ✗ | No expected fragments — wrong answer, or `no_results` when an answer was expected |
| 🛇 | Abstained — correct on negative-control rows (no expected fragments) |

The gate at the bottom:

```
GATE — thesis holds if `graph passing > flat passing` on the requires_graph subset.
       result: graph=N flat=M  →  ✅ PROCEED   or   ❌ PIVOT
```

PROCEED means the graph augmentation measurably won on questions designed
to need it — move on to harder L3 work (richer extraction, retrieval
quality, larger corpora). PIVOT means root-cause first: was it extraction
quality (check `workspace/logs/graph.log` — see plan §2b)? Resolution
(branch counts on resolve rows)? Expansion (chunk count on graph_expand
rows in the Ask trace)?

## Wiping between runs

If you change the corpus or want a clean state, delete the workspace's
knowledge artifacts:

```
rm -rf <workspace>/knowledge/qdrant   # vector store
rm <workspace>/knowledge/knowledge.db  # SQL catalog
rm -rf <workspace>/knowledge/graph     # L3 graph DB
```

Then re-run without `--skip-ingest`.
