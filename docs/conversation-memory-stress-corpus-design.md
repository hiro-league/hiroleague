# Conversation Memory Stress Corpus Design

Reusable design note for authoring fictional, contamination-free conversation-memory stress
corpora for Graphiti/Zep-style memory.

## Goal

Create a fictional, contamination-free memory corpus that tests more than temporal latest-wins
behavior.

| Target | Value |
|---|---:|
| Episodes | 40 |
| Questions | 100 |
| Format | `*.episodes.jsonl` + `*.questions.yaml` |
| Style | First-person conversational turns from one named speaker |
| Domain | Invented names, places, projects, tools, aliases, local rules |
| Purpose | Stress recall, temporal supersession, graph relations, noisy evidence selection, and abstention |

Use this as the template for new memory corpora. The first concrete corpus authored from it is
`eval/helix_memory_stress.*`, which expands the older `eval/helix_station.*` temporal eval from a
narrow set of dated turns into a broader benchmark-style memory set.

## Benchmark Groups

Use the major groups from LongMemEval and LoCoMo, adapted for a fictional local domain where the
model cannot rely on general knowledge.

| Group | Benchmark pattern | Corpus version |
|---|---|---|
| Direct recall | LongMemEval single-session user/assistant; LoCoMo single-hop | One fact, but phrased indirectly or surrounded by noise |
| Preference recall | LongMemEval single-session preference | Stable or changing user preference, often inferred from repeated behavior |
| Single-hop | LoCoMo single-hop | One relation between two remembered entities |
| Multi-hop | LongMemEval multi-session; LoCoMo multi-hop | Combine two or more facts across turns |
| Temporal ordering | LongMemEval/LoCoMo temporal | Before/after, first/last, sequence, duration |
| Point-in-time state | Temporal reasoning | Answer as of a specific date, not current state |
| Latest state | Knowledge update plus temporal | Current valid fact after corrections or replacement |
| Knowledge update | LongMemEval knowledge update | Earlier fact is superseded, corrected, renamed, or invalidated |
| Event recall | LoCoMo event QA / summarization-adjacent | Recover what happened around a dated episode |
| Causal reasoning | LoCoMo long-range causal dynamics | Explain why a decision changed using scattered evidence |
| Local-domain reasoning | Replacement for open-domain | Apply fictional in-corpus rules to remembered facts |
| Entity disambiguation | Adversarial/misleading style | Similar names, aliases, reused labels, false friend entities |
| Abstention | LongMemEval abstention; LoCoMo adversarial | Correct answer is not enough information |

References:

- [LongMemEval](https://arxiv.org/abs/2410.10813): information extraction, multi-session reasoning,
  temporal reasoning, knowledge updates, and abstention.
- [LoCoMo](https://aclanthology.org/2024.acl-long.747/): long multi-session conversations with QA,
  event summarization, multimodal dialogue generation, and long-range temporal/causal dynamics.
- [Zep benchmark notes](https://www.getzep.com/research/): reports LongMemEval across six question
  types and LoCoMo across single-hop, multi-hop, temporal, and open-domain categories.

## Question Distribution

Target 100 questions with enough breadth to avoid a temporal-only benchmark.

| Category | Count |
|---|---:|
| `direct_recall` | 8 |
| `preference_recall` | 8 |
| `single_hop` | 8 |
| `multi_hop` | 12 |
| `temporal_order` | 8 |
| `temporal_point_in_time` | 7 |
| `temporal_latest_state` | 8 |
| `knowledge_update` | 10 |
| `event_recall` | 8 |
| `causal` | 7 |
| `local_domain_reasoning` | 6 |
| `misleading_entity` | 5 |
| `abstention` | 5 |
| Total | 100 |

## Corpus Design Rules

1. Use invented proper nouns only: people, rooms, tools, projects, rituals, codes, teams, places.
2. Split important facts across turns. Avoid one sentence that contains every answer component.
3. Include dense but plausible noise: side tasks, minor preferences, irrelevant names, repeated
   routines, abandoned plans.
4. Use aliases and paraphrases: `Mira`, `M. Voss`, `the blue-folder person`, `the slate lead`.
5. Include corrections and supersession: "I thought X, but later found out Y"; "we renamed it";
   "that rule changed."
6. Avoid exact lexical matching between questions and evidence where possible.
7. Keep answers grounded: every expected answer must be supported by at least one episode, and
   harder questions should usually require two or more.
8. Add false trails, but make the gold answer unambiguous.
9. Make current-state questions depend on timestamps, not wording like "currently" alone.
10. Include abstention questions where the corpus genuinely lacks the answer.

## Episode Shape

Each entry should be a dated conversational turn, roughly 3-6 sentences.

```json
{"id":"memset_001","timestamp":"2215-01-04T09:12:00Z","speaker":"Taren Vale","type":"text","body":"It's Taren Vale. I moved the blue-folder work out of Nara Bay today. Mira keeps calling it the tide packet, but the actual label in my notes is Orison. I also learned that Kade's old badge color was amber, not green; green belongs to Rell's crew. Not urgent, but I should stop mixing those two up."}
```

## Difficulty Mix

| Level | Share | Meaning |
|---|---:|---|
| Medium | 45% | One or two facts, paraphrased, some distractors |
| Hard | 40% | Multi-turn, temporal, alias, or supersession required |
| Very hard | 15% | Multiple constraints, misleading neighbors, or abstention |

Exclude the most trivial questions. A basic substring search should not reliably retrieve the
answer without also pulling competing distractors.

## Output Files

When the corpus is authored, use:

| File | Purpose |
|---|---|
| `eval/<corpus_id>.episodes.jsonl` | 40 first-person fictional conversation turns |
| `eval/<corpus_id>.questions.yaml` | 100 categorized questions with ideal answers |

Question rows should follow the existing eval bank shape:

```yaml
- id: q_multi_hop_01
  category: multi_hop
  difficulty: hard
  question: "Which project owner is tied to the room I stopped using after the blue-folder move?"
  expected_answer: "Mira Voss, because the blue-folder work became Orison and later moved away from Nara Bay."
  requires: [graph]
```

Use `requires: [temporal]` for ordering, point-in-time, latest-state, and update questions. Use
`requires: [graph]` for relation chains. Use `requires: [world]` only if the "world" is explicitly
defined inside the fictional corpus.

Tag each row with a `difficulty` of `medium`, `hard`, or `very_hard`, matching the Difficulty Mix
table above (target 45% / 40% / 15%). The field is **reporting-only** — the eval harness surfaces a
**by-difficulty** pass-rate table beside the by-category one, so you can see whether the model is
failing the *hard* rows specifically. It does not affect the PROCEED/PIVOT gate, and it is optional
(unlabeled rows bucket as `unspecified`).
