# Eval corpora

Corpora for the admin **Eval** panel (Knowledge → Eval tab). The eval runs **in-process** (the old
standalone `l3_synthetic_eval.py` CLI harness was retired); design + UI live in
[`docs/eval-corpus-tracks-design.md`](../docs/eval-corpus-tracks-design.md).

Two tracks, selected by corpus shape:

- **Memory** — turn/chat-log corpora exercise the conversation-memory engine (`remember` → `recall`).
- **Knowledge** — document/chunk corpora exercise the knowledge engine (ingest + retrieval).

## Layout & naming

A corpus pairs with its question bank by **stem**; the stem is also the eval drawer suffix
(`eval_mem_<id>` / `eval_kb_<id>`):

| Track | Corpus | Question bank |
|---|---|---|
| Memory | `<id>.episodes.jsonl` (one JSON episode per line: `id`, `timestamp`, `body`, optional `speaker`) | `<id>.questions.yaml` |
| Knowledge | `<id>/` (a folder of `.md` docs) | `<id>.questions.yaml` (sibling of the folder) |

Bundled here:

| File | Purpose |
|---|---|
| `adam_year.episodes.jsonl` + `adam_year.questions.yaml` | Memory corpus — a year of dated turns, with temporal supersession + negative-control questions. |
| `l3_synthetic/*.md` + `l3_synthetic.questions.yaml` | Knowledge corpus — a small personal corpus where flat RAG struggles on multi-hop. |

`*.episodes_bak.jsonl` files are backups and are skipped by the corpus picker.

## Question bank format

Each row: `id`, `question`, and **either** `expected_fragments` (lowercase substrings the scorer
looks for) **or** `expected_kind: abstain` (negative control — declining is correct). Optional:
`category`, `subcategory`, `requires` (`graph`/`temporal`/`world` → flips the `requires_graph` gate
subset), and `expected_answer` (an **unscored** gold answer shown beside recalled facts in the
memory recall inspector).

## Running

From the admin UI: **Knowledge → Eval**, pick a **track** sub-tab, point the **Folder** field at
this `eval/` directory (or any folder), choose a **Corpus**, select the **questions** to run, then
**Run**. The engine settings that drive the run are shown at the top with a link to workspace
Settings. Activity + Results stream live and persist across navigation.

Scoring note: the **knowledge** track scores marks (✓ / ◐ / ✗ / 🛇) and a PROCEED/PIVOT gate; the
**memory** track is a single recall leg with **scoring deferred** (it shows the recalled facts for
eyeballing — see the design doc).
