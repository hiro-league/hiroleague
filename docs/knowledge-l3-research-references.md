# Knowledge L3 — Research References (Graph-RAG / Personal KG Pipelines)

> **Purpose.** Raw research dossier captured to ground the L3 *content-routing* design
> ([`knowledge-l3-content-routing-design.md`](knowledge-l3-content-routing-design.md)) in
> tried-and-true, production-proven techniques rather than first-principles invention. This is
> a **reference document**, not a design/spec — it records *what existing systems do, how, and
> with what trade-offs*, with sources. A later turn folds the relevant pieces into the L3 design.
>
> **Method.** Five parallel deep-dive research passes (May 2026), each mining one framework
> family at source level (repo code, papers, docs) for **reusable techniques**, judged against
> our target: a **single-user, local-first (Windows-primary), personal-data** corpus — family,
> places, objects, events, chats, photo descriptions, voice transcripts.
>
> **Stance.** We are **not adopting** any of these frameworks wholesale (see the Graphiti-as-
> reference decision and the "don't recreate the Mem0 drama" constraint). We extract proven
> *methods* and reimplement the good ones on our own stack (`model_factory`, Qdrant hybrid
> retrieval, our ledger/credentials, an embedded graph DB).

## Reading guide

- §1 Graphiti / Zep — the temporal agent-memory KG engine (write-side crown jewel).
- §2 LightRAG — the cheap single-call extraction + dual-level retrieval engine.
- §3 Microsoft GraphRAG + LazyGraphRAG (+ nano-graphrag, KET-RAG, E2GraphRAG) — what to borrow and what to avoid.
- §4 Cognee + Mem0 + Entity Resolution — architecture, the bleed-bug postmortem, and the ER recipe.
- §5 Embedded graph-DB storage — skeptical Windows/embedded comparison.
- §6 Cross-cutting convergence — what *all* systems agree on (the trust signal).
- §7 Consolidated "borrow / avoid" + open decisions.

---

# §1 — Graphiti / Zep

Reverse-engineering of *methods* from the current `graphiti_core` source (`main`) and the Zep
paper ([arXiv 2501.13956](https://arxiv.org/html/2501.13956v1)). Where live code diverges from
the paper, it is flagged — the code has evolved significantly (e.g. it now does deterministic
dedup *before* the LLM, which the paper does not describe).

## 1.1 The "episode" ingestion model

**What it is.** One ingestion abstraction (`EpisodicNode`) wraps three source kinds —
`message`, `text`, `json` — behind a single `add_episode()` entry point. The raw payload is
preserved verbatim as a node; extracted entities/facts are *derived* and linked back to it.

**Mechanics** (`graphiti_core/nodes.py`, paper §2.1):
- `EpisodeType` enum = `message | json | text` (`nodes.py:74-76`). Only the extraction *prompt*
  differs by type; everything downstream is unified.
- `EpisodicNode` fields: `source: EpisodeType`, `source_description: str` (free-text provenance
  label, e.g. "podcast", "voice note"), `valid_at: datetime` (the **reference time** = when the
  event happened), `created_at` (ingestion time), and `entity_edges: list[str]` (UUIDs of facts
  derived from it) (`nodes.py:318-348`).
- `add_episode(name, episode_body, source, source_description, reference_time, group_id,
  entity_types, edge_types, edge_type_map, previous_episode_uuids, update_communities, uuid)`.
- **Provenance is bidirectional and non-lossy.** Every extracted entity gets a `MENTIONS` edge
  from the episode (`EpisodicEdge`, `edges.py:143`); every derived fact (`EntityEdge`) stores
  `episodes: list[str]` (`edges.py:267`) — the list of source episode UUIDs. So you can traverse
  episode→facts (forward) and fact→episodes (backward). When a fact is re-derived from a new
  episode, the new episode UUID is *appended* to that list rather than creating a duplicate fact
  (`edge_operations.py`, `resolved.episodes.append(episode.uuid)`).
- **`group_id`** is the namespace/partition key — the multi-tenant boundary.
- **Context window.** Extraction is fed the current episode plus the last *n* previous episodes
  (paper says n=4; code pulls `previous_episodes` via `retrieve_episodes`) for
  coreference/continuity, but entities are extracted *only* from the current message (previous
  are "for context only").

**Applicability.** **Strong.** A photo description, a voice transcript, a chat turn, and a
structured "event" JSON all become episodes with a `source_description` and a `reference_time`.
The append-only `episodes[]` provenance list gives "where did the system learn this?" for free —
important for a personal corpus where trust/explainability matters. Use `source` to drive
type-specific extraction prompts; use `reference_time` as the temporal anchor (a photo's EXIF
date, a transcript's recording date).

## 1.2 Entity & relationship extraction

**What it is.** A **multi-pass, multi-call** LLM pipeline per episode: nodes first, then edges,
with separate calls for classification, attributes, and timestamps. Structured output via
Pydantic, with an injectable **custom ontology** (entity types + edge types) — but it also works
"type-free" (everything is just `Entity`).

**Pipeline order** (`graphiti.py add_episode`):
1. `extract_nodes` → entities
2. `resolve_extracted_nodes` → dedup/resolve against graph (see §1.3)
3. `extract_edges` → facts between resolved entities
4. `resolve_extracted_edges` → dedup + invalidation (see §1.3/§1.4)
5. `extract_attributes_from_nodes` → hydrate entity attributes/summaries
6. save + optional community update

**Extraction prompt design** (`prompts/extract_nodes.py`):
- Per-source system prompts. The `message` extractor's rule set is aggressive about **not
  polluting the graph**: NEVER extract pronouns, abstract concepts/feelings, generic common
  nouns ("stuff/things/food/time"), generic media nouns ("photo/pic/video") unless uniquely
  named, bare kinship/pet terms.
- **Coreference at extraction time:** "Pronoun references such as he/she/they... should be
  disambiguated to the names of the reference entities."
- **Possessive qualification rule** (very relevant to personal data): bare relational terms must
  be qualified with the possessor — extract `"Nisha's dad"` not `"dad"`, `"Jordan's cat"` not
  `"cat"`. A deliberate disambiguation strategy.
- **Specificity preservation:** "wool coat" not "coat", "road cycling" not "cycling", brand names
  retained.
- **Speaker is always entity #0** for message episodes (the part before `:`).

**Structured output schema** (`prompts/extract_nodes.py`):
```python
class ExtractedEntity(BaseModel):
    name: str
    entity_type_id: int          # index into the injected ontology
    episode_indices: list[int]   # which episode(s) in the batch it came from
```
Custom entity types are injected as a `<ENTITY TYPES>` block; the LLM returns the type *id*.
Types are plain Pydantic `BaseModel`s passed as `entity_types: dict[str, type[BaseModel]]`. Type
fields become extractable attributes (hydrated in step 5).

**Edge/fact schema** (`prompts/extract_edges.py`):
```python
class Edge(BaseModel):
    source_entity_name: str      # must match a name from the ENTITIES list (else rejected)
    target_entity_name: str
    relation_type: str           # SCREAMING_SNAKE_CASE, e.g. LIVES_IN
    fact: str                    # natural-language paraphrase, MUST preserve concrete details
    valid_at / invalid_at: str | None  # ISO 8601
    episode_indices: list[int]
```
- Facts must connect **two distinct** entities from the provided list; single-entity states
  ("Alice feels happy") are rejected unless anchored to a second entity.
- **Custom edge types** (`<FACT_TYPES>`) are constrained by an
  `edge_type_map: dict[(source_label, target_label) -> [type_names]]` — a typed ontology where
  only certain relation types are legal between certain entity-type pairs. At resolution time the
  code computes the legal edge-type subset from the source/target node labels (`edge_operations.py`
  `label_tuples`/`edge_types_lst`).

**LLM calls per episode.** Minimum (paper) ~4 distinct prompt types; in current code higher and
roughly **O(entities + facts)** because attributes, timestamps, and resolution run per-item
(often batched, often `model_size=small`). Per episode: 1 node-extract + (≤1 batched node-dedup
LLM call for ambiguous names) + 1 edge-extract + N edge-resolve calls (one per surviving fact,
small model) + attribute/timestamp calls. See §1.6.

**Applicability.** **Yes, with simplification.** The node→edge two-stage split and "fact =
natural-language sentence + typed predicate + endpoints" representation are excellent and
portable. The injectable Pydantic ontology with `edge_type_map` signature constraints fits
personal data where the schema is known (Person, Place, Event, Pet, Photo; relations ATTENDED,
LIVES_IN, PHOTOGRAPHED_AT, RELATED_TO). For local-first single-user, **collapse some passes** to
cut cost (§1.6).

## 1.3 Entity resolution / deduplication (the crown jewel)

The live code **substantially exceeds** the paper. The paper describes embedding + full-text +
LLM. The current code adds a **deterministic fast path** that resolves most mentions *without any
LLM call*.

**Algorithm** (`utils/maintenance/dedup_helpers.py` + `node_operations.py`):
```
For each extracted entity:
  1. CANDIDATE RETRIEVAL  (_collect_candidate_nodes)
       - semantic search: embed entity name, cosine search over existing nodes
       - (paper also: BM25 full-text over names + summaries)
  2. DETERMINISTIC RESOLUTION  (_resolve_with_similarity) -- NO LLM
       a. exact normalized-name match (lowercase + collapse whitespace)
          - exactly 1 hit  -> RESOLVE (merge)
          - >1 hit         -> ambiguous -> escalate to LLM
       b. ENTROPY GATE: skip fuzzy match if name is too short / low-entropy
          (Shannon entropy < 1.5, len < 6 and < 2 tokens) -> escalate to LLM
       c. fuzzy match: MinHash (32 perms) over 3-gram shingles + LSH banding,
          Jaccard >= 0.9  -> RESOLVE
       else -> escalate to LLM
  3. LLM RESOLUTION  (_resolve_with_llm) for the unresolved/ambiguous only
       - one batched call: dedupe_nodes.nodes prompt
       - returns duplicate_candidate_id or -1 per entity
  4. TYPE PROMOTION (_promote_resolved_node): if canonical node is generic
     "Entity" and the new mention has a specific type, upgrade the labels.
```

**Key thresholds** (`dedup_helpers.py`): `_NAME_ENTROPY_THRESHOLD=1.5`, `_MIN_NAME_LENGTH=6`,
`_FUZZY_JACCARD_THRESHOLD=0.9`, `_MINHASH_PERMUTATIONS=32`, `_MINHASH_BAND_SIZE=4`.

**The entropy gate is the clever bit:** short/ambiguous names ("Sam", "dad") are *deliberately
not* fuzzy-matched — they go to the LLM, which has the episode context to disambiguate.
High-entropy distinctive names ("Gamecube", "New York City") resolve deterministically and
cheaply.

**The dedup LLM prompt** (`prompts/dedupe_nodes.py`) directly addresses the "two people named
Ahmed" worry. Given previous + current message + new entity + existing candidates + entity-type
descriptions, instructed: *"Entities should only be considered duplicates if they refer to the
same real-world object or concept."* Worked examples encode the hard cases:
- `"Java" (language)` vs `"Java" (island)` → **not** duplicates (same name, different thing).
- `"NYC"` vs `"New York City"` → duplicates (alias).
- `"Marco's car"` vs `"Marco's vehicle"` → duplicates (synonym + same possessor).

**Collision avoidance principle:** **name match is necessary but never sufficient** — the LLM
arbitrates using episode context + type. Aliases/abbreviations resolved by the LLM (entropy gate
routes them there).

**Coreference ("my colleague")** handled at two layers: (a) extraction prompt disambiguates
pronouns and forces possessive qualification, so "my colleague" tends to become a named/qualified
entity before resolution; (b) the dedup prompt's "semantic equivalence: if a descriptive label
clearly refers to a named entity in context, treat as duplicates" merges a descriptive mention
into the named node.

**Merge mechanics.** Merge by `uuid_map` (extracted-uuid → canonical-uuid) plus name/summary
update; canonical node kept, the new mention's facts rewired to it, canonical may absorb a more
specific name or type. No hard delete of the mention's contribution.

**Applicability.** **#1 technique to borrow.** Deterministic-first / LLM-only-for-ambiguous is
exactly what local-first needs: minimizes LLM calls, lets a small/local model handle only the
hard cases. The entropy gate + possessive-qualification rules are practically tailored to family
data ("dad", "Sam", "my cousin").

## 1.4 The bi-temporal model

**What it is.** Every fact (`EntityEdge`) carries **four** timestamps spanning two timelines, and
facts are **never deleted** — superseded facts are *expired/invalidated*, preserving history and
enabling point-in-time queries.

**The four fields** (`edges.py:271-277`, paper §2.2.3):

| Field | Timeline | Meaning |
|---|---|---|
| `created_at` | T′ (transaction) | when Graphiti ingested the fact |
| `expired_at` | T′ (transaction) | when Graphiti learned the fact was no longer true |
| `valid_at` | T (event) | when the fact became true in the real world |
| `invalid_at` | T (event) | when the fact stopped being true in the real world |

`valid_at`/`invalid_at` are LLM-extracted from the fact text relative to the episode's
`reference_time` (`prompts/extract_edges.py` DATETIME RULES; `_extract_edge_timestamps`). Relative
expressions ("last week") resolved against reference time; present-tense facts set
`valid_at = reference_time`; nothing hallucinated (both left null if unstated).

**Supersession / invalidation** (`edge_operations.py`):
1. For a new fact, search existing facts in two buckets: **duplicate candidates** (same endpoints,
   `get_between_nodes` + hybrid search) and **invalidation candidates** (semantically related
   facts, unconstrained endpoints).
2. One LLM call (`dedupe_edges.resolve_edge`, small model) classifies each existing fact as
   `duplicate_facts` and/or `contradicted_facts`, over a *continuous index* across both lists.
   Crucial nuance: a fact can be **both** a duplicate and contradicted — "Alice works at Acme as
   software engineer" vs "...as senior engineer" → contradiction (supersede), *not* a plain dup.
3. `resolve_edge_contradictions` sets the contradicted edge's `invalid_at = new_edge.valid_at` and
   `expired_at = now()` (computes overlap: only invalidate if intervals actually conflict). The
   old edge **stays in the graph**, just marked invalid.

Invalidation = paper's rule verbatim: *"invalidates the affected edges by setting their `t_invalid`
to the `t_valid` of the invalidating edge,"* always prioritizing newer info.

**Point-in-time queries** = filter edges where `valid_at <= t <= invalid_at` (event time) or use
T′ for "what did we believe at ingest time t". Retrieval returns `fact` + `valid_at` + `invalid_at`.

**Note:** `add_episode_bulk` **skips invalidation** — bulk load is for empty-graph seeding only;
incremental `add_episode` maintains temporal correctness.

**Applicability.** **Partial — borrow selectively.** Event-time (`valid_at`/`invalid_at`) is
valuable for personal data (family facts change: "lived in Cairo 2010–2018", "married 2021";
point-in-time "where did we live when the kids were born?"). Keep the T′ pair
(`created_at`/`expired_at`) cheaply for audit/undo (free to store) but you won't query the
transaction timeline often. Gate the contradiction-detection LLM call to mutable predicate types
to save cost.

## 1.5 Retrieval

**What it is.** Hybrid search fusing **three** methods, with pluggable rerankers, returning facts
(edges), entities (nodes), episodes, communities. The graph is used at query time both as a search
surface (BFS) and a reranking signal (node-distance).

**Three search methods** (per object type; `search_config.py`):
- `cosine_similarity` — embeddings (1024-d in paper).
- `bm25` — full-text (Lucene/Neo4j).
- `bfs` (breadth-first) — graph traversal from origin nodes (`edge_bfs_search`, `node_bfs_search`),
  with `bfs_max_depth`. "Contextual similarity" — facts/entities reachable from a seed.

**Rerankers** (`search_config.py`, `search_utils.py`):
- `rrf` — Reciprocal Rank Fusion, `score += 1/(rank+k)` (default).
- `mmr` — Maximal Marginal Relevance (diversity, `mmr_lambda`).
- `cross_encoder` — LLM/cross-encoder scoring (highest quality, costliest).
- `node_distance` — rerank by graph hop-distance from a `center_node_uuid` (personalize around a
  focal entity).
- `episode_mentions` — rerank by how many episodes mention the node (frequency/salience prior).

**Query-time graph usage** (the "resolve query entities → traverse → gather" pattern):
- `bfs_origin_node_uuids` seed the BFS. In agent retrieval you resolve the query's entities to node
  UUIDs, then BFS from them and fuse with semantic/BM25 hits.
- `node_distance_reranker` re-sorts candidates by shortest path to the focal node — results near
  the asked-about entity float up.

**Recipes** (`search_config_recipes.py`): `COMBINED_HYBRID_SEARCH_RRF`,
`EDGE_HYBRID_SEARCH_NODE_DISTANCE`, `EDGE_HYBRID_SEARCH_EPISODE_MENTIONS`, `..._CROSS_ENCODER` —
mix-and-match `{search methods} × {reranker}` per object type.

**Applicability.** **Yes.** RRF over (semantic + BM25) is a low-effort, high-value baseline (BM25
catches exact names/places embeddings miss — "Aunt Salma", "Villa 12"). `node_distance` reranking
around a resolved query-entity fits "tell me about X". BFS optional for v1; the fusion+rerank layer
is the must-have. Cross-encoder optional given local-first cost (use a small local reranker — we
already have local rerank models).

## 1.6 Cost characteristics

**LLM calls per episode (current code):**
- 1× node extraction
- 0–1× node dedup (LLM) — **only for ambiguous/low-entropy names**; deterministic path (exact +
  MinHash/LSH) resolves the rest with **zero** LLM cost.
- 1× edge extraction
- ~1× per surviving fact: edge resolve/dedup/contradiction (small model)
- attribute + timestamp extraction (batched, small model)

Dominant cost scales with **number of *new, ambiguous* entities + number of facts**, not corpus
size.

**Incremental-update strategy (how batch recompute is avoided):**
- Everything per-episode and incremental — new episodes resolve against *existing* graph state.
- **Resolution search space bounded:** edge dedup constrained to edges *between the same entity
  pair* (`get_between_nodes`) — paper §2.2.2 calls this the key complexity reduction. Node dedup
  bounded to semantic+fuzzy candidates, not the whole graph.
- **Deterministic fast paths** (exact-name, verbatim-fact reuse, MinHash) short-circuit before any
  LLM call.
- **Community detection incrementally extended** (paper §2.3): a new node assigned to the
  **plurality community of its neighbors** via label-propagation's dynamic extension, deferring a
  full propagation run. In code, `update_communities=False` by default — communities opt-in.
- **Bulk path trades correctness for throughput:** `add_episode_bulk` skips invalidation.

**Measured benefit (paper, Table 2):** vs full-context baseline, ~115k→1.6k context tokens and
~28.9s→2.58s latency on LongMemEval with gpt-4o.

## 1.7 "Low-confidence chatter shouldn't pollute the graph"

There is **no explicit confidence score**. Pollution is controlled by **aggressive prompt-level
gatekeeping + deterministic guards**:
1. **Extraction exclusion lists** (`prompts/extract_nodes.py`): hard bans on pronouns, feelings,
   abstract concepts, generic nouns, bare media/event nouns, fragments, adjectives. "When in
   doubt, do NOT extract."
2. **The "Wikipedia test":** extract only entities "specific enough to be uniquely identifiable".
3. **Two-distinct-entity rule for facts** (`prompts/extract_edges.py`): single-entity emotional
   states rejected unless anchored to a concrete second entity.
4. **`excluded_entity_types`** parameter — blocklist whole types.
5. **Entropy gate** (`dedup_helpers.py`): low-information names not trusted to deterministic match.
6. **Detail-preservation rule** prevents over-generalization diluting real facts.

**Applicability, and an extension.** For voice transcripts/chats (high chatter ratio), the
exclusion-list + two-entity-rule model is right — but add what Graphiti lacks: a **per-source
extraction policy** (aggressive for "event" JSON / photo captions, conservative for casual chat)
and optionally a **salience signal** using `episode_mentions` (a fact mentioned once in idle
chatter ranks below one corroborated across episodes). The append-only `episodes[]` list already
gives corroboration count for free.

## 1.8 Graphiti — techniques worth borrowing (ranked)

1. **Deterministic-first entity resolution** (exact-name → MinHash/LSH fuzzy → LLM only for
   ambiguous), gated by name-entropy. Biggest cost saver; solves duplicate-name/alias/coreference.
2. **Unified "episode" ingestion with append-only bidirectional provenance** (`episodes[]`,
   `MENTIONS`). One pipeline for chat/text/JSON/caption/transcript; explainable origin.
3. **Fact = (source, target, typed predicate, natural-language sentence) + RRF hybrid retrieval**
   (semantic + BM25) with `node_distance`/`episode_mentions` rerankers.
4. **Bi-temporal facts with non-destructive supersession** (`valid_at/invalid_at` event +
   `created_at/expired_at` txn; contradiction → old `invalid_at = new.valid_at`, never delete).
5. **Prompt-level pollution control** (exclusion lists, uniquely-identifiable test, two-entity
   rule, possessive qualification) — cheapest quality lever for chatter-heavy sources.
6. **Bounded incremental updates** (edge dedup constrained to same-endpoint pairs; per-episode;
   no global recompute) — makes small/local-model operation feasible.
7. **Injectable Pydantic ontology with `edge_type_map` signature constraints** (kept optional so
   unknown things land as generic `Entity`).

**Drop / simplify for local-first:** cross-encoder reranking (use local rerank models);
community detection (opt-in, low value single-user); proliferation of small-model calls (collapse
into fewer combined prompts); transaction-timeline *queries* (keep columns for audit, skip query
paths for T′ initially).

**Key source files:** `graphiti_core/nodes.py`, `edges.py`, `prompts/extract_nodes.py`,
`prompts/extract_edges.py`, `prompts/dedupe_nodes.py`, `prompts/dedupe_edges.py`,
`utils/maintenance/dedup_helpers.py`, `utils/maintenance/node_operations.py`,
`utils/maintenance/edge_operations.py`, `search/search_utils.py`,
`search/search_config_recipes.py`; paper [arXiv 2501.13956 §2–§3](https://arxiv.org/html/2501.13956v1).

---

# §2 — LightRAG

Grounded in the actual `HKUDS/LightRAG` source (`main`, May 2026) + EMNLP 2025 paper. The current
upstream code has grown beyond the paper's minimalist design (gleaning loops, map-reduce
summarization, source-id limiting, chunk-tracking KV, rebuild-from-cache); the **paper's core**
is separated from **production hardening** since for single-user local the core is what matters.

## 2.1 Entity & relationship extraction — single LLM call per chunk

**What it is.** One LLM call per chunk extracts entities *and* relationships *and* relationship
keywords together, in one structured response. The headline efficiency claim vs GraphRAG.

**Mechanics** (`lightrag/operate.py: extract_entities` → `_process_single_content`,
`lightrag/prompt.py`):
- The prompt (`entity_extraction_system_prompt`) emits two record types in one response:
  - Entity row (4 fields): `entity{d}entity_name{d}entity_type{d}entity_description`
  - Relation row (5 fields): `relation{d}source{d}target{d}relationship_keywords{d}relationship_description`
- Delimiters are atomic sentinel tokens, not commas: `tuple_delimiter = "<|#|>"`,
  `completion_delimiter = "<|COMPLETE|>"`. The prompt explicitly forbids putting content inside
  the delimiter and gives wrong/correct examples — robustness trick surviving messy LLM output.
- **Relationship keywords extracted at index time, inside the same call** (comma-separated within
  field 4). Load-bearing: each edge carries its own high-level keywords → enables high-level
  (global) retrieval later without re-reading text.
- `entity_type` constrained to a guidance list (default 11: Person, Creature, Organization,
  Location, Event, Concept, Method, Content, Data, Artifact, NaturalObject; fallback `Other`).
  Injected via `{entity_types_guidance}` and **fully overridable** via `addon_params` — important
  for a personal domain (Contact, Project, Message, Place, Purchase).
- Two output modes: delimiter-text (default) and `entity_extraction_use_json` (JSON object with
  `entities[]` / `relationships[]`). JSON trades token overhead for easier parsing.
- **"Gleaning"** (`entity_extract_max_gleaning`, default `1`): an optional *second* call replaying
  the first call's messages, asking "what did you miss / mis-format?". Default 1 ⇒ **2 calls per
  chunk worst case**, not 1. Set to 0 for true single-call. Token-budget guard
  (`MAX_EXTRACT_INPUT_TOKENS`, default 20480) skips gleaning if the replay overflows context.
- Prompt: decompose n-ary statements into binary relations; treat relations as undirected unless
  stated; third-person, no pronouns; entities first then relations; cap rows (`max_total_records=100`,
  `max_entity_records=40`).

**Applicability.** **HIGH** — the single most portable technique. One structured prompt returning
typed entities + typed edges + edge-keywords. For personal data, override the entity-type list,
keep gleaning at 0 to start. Copy the atomic-delimiter discipline (sentinels + wrong/right
examples) verbatim — it's why cheap-model extraction stays parseable.

## 2.2 Dual-level retrieval — low-level vs high-level keywords

**What it is.** At query time a single LLM call splits the query into two keyword sets targeting
two *different* indexes:
- **low_level_keywords** → specific entities/proper nouns/jargon → **entity** vector DB.
- **high_level_keywords** → overarching themes/intent → **relationship** vector DB.

**Mechanics** (`get_keywords_from_query` → `keywords_extraction` prompt; `_perform_kg_search`;
`kg_query`):
- `keywords_extraction` returns strict JSON: `{"high_level_keywords": [...],
  "low_level_keywords": [...]}`. Told to prefer multi-word phrases ("latest financial report",
  "Apple Inc.") over unigrams, and return empty arrays for nonsense queries.
- Four KG modes (a fifth, `naive`, is plain vector RAG over chunks):

| Mode | LL keywords → entities_vdb | HL keywords → relationships_vdb | raw chunk vector search |
|---|---|---|---|
| `local` | ✅ | — | — |
| `global` | — | ✅ | — |
| `hybrid` | ✅ | ✅ | — |
| `mix` | ✅ | ✅ | ✅ (`_get_vector_context`) |
| `naive` | — | — | ✅ |

- Guard logic in `kg_query`: if both keyword sets empty and query short (`<50` chars), fall back to
  using the raw query as a low-level keyword; else bail with a fail response.
- `mix` mode is the practical default: unions graph-derived context with direct chunk vector hits,
  degrades gracefully when the graph is sparse.

**Applicability.** **HIGH (concept), MEDIUM (as-is).** Route specific terms→entities, thematic
terms→relationships. For personal data, `local` (entity-centric) is usually highest-value, `mix`
the safe default (sparse personal graph → keep chunk-vector backstop). The extra LLM call per
query for keyword splitting is negligible/cacheable for a single user.

## 2.3 Aligning vector search with graph structure (retrieval flow)

The most reusable *mechanism*. Vectors find entry points; the graph supplies structural context.

**Local path** (`_get_node_data`, `_find_most_related_edges_from_entities`,
`_find_related_text_unit_from_entities`):
```
LL keywords --embed--> entities_vdb.query(top_k=40)        # vector entry points
   -> entity_names
   -> graph.get_nodes_batch + node_degrees_batch           # hydrate from graph
   -> graph.get_nodes_edges_batch(entity_names)            # ONE-HOP neighbor edges
   -> graph.get_edges_batch + edge_degrees_batch
   -> sort edges by (degree_rank, weight) desc             # structural importance
   -> for each entity: source_id field = "<SEP>"-joined chunk-ids
        -> pull those text chunks (VECTOR or WEIGHT pick)  # back to raw text
```

**Global path** (`_get_edge_data`, `_find_most_related_entities_from_relationships`,
`_find_related_text_unit_from_relations`):
```
HL keywords --embed--> relationships_vdb.query(top_k=40)   # vector entry points = edges
   -> (src,tgt) pairs
   -> graph.get_edges_batch                                # hydrate edges
   -> collect endpoint entities (src + tgt)                # ONE-HOP to nodes
   -> graph.get_nodes_batch
   -> edges keep vector-similarity order; pull related chunks
```

Mechanical details worth borrowing:
- **Entities and edges store provenance inline**: `source_id` is a `<SEP>`-joined list of chunk-ids
  (`GRAPH_FIELD_SEP = "<SEP>"`). Retrieval hops from a graph element back to verbatim text without
  a separate join table — cheap and local-friendly.
- **Ranking blends graph + vector signals**: local relations sorted by `(node_degree_rank, weight)`;
  global edges keep cosine order. Degree acts as a free importance prior.
- **Chunk selection pluggable** (`kg_chunk_pick_method`: `VECTOR` re-ranks candidate chunks by
  cosine; `WEIGHT` uses occurrence-frequency polling). `related_chunk_number` default 5.
- VDB record contents are embedding-friendly: entity content = `name + "\n" + description`;
  relation content = `keywords \t src \n tgt \n description`. The relationship embedding is
  dominated by keywords + description — what makes high-level thematic matching work.
- `cosine_better_than_threshold` default `0.2` filters weak vector hits before the graph hop.

**Applicability.** **VERY HIGH.** "Vector for entry, graph for one-hop expansion, inline
`source_id` to get back to text" is storage-agnostic. For single-user you can do the one-hop
expansion in memory and skip the batching machinery.

## 2.4 Incremental update — merge without re-indexing

**What it is.** New documents extracted into entities/edges and **merged into the existing graph in
place**. No community recomputation, no full re-index.

**Mechanics** (`merge_nodes_and_edges` → `_merge_nodes_then_upsert` / `_merge_edges_then_upsert`):
- **Two-phase merge**: Phase 1 all entities, Phase 2 all relationships (may lazily create missing
  endpoint nodes), Phase 3 per-doc entity/relation lists. Concurrent under a semaphore.
- **Entity merge** (`_merge_nodes_then_upsert`):
  - Read existing node (if any). Merge by **entity name as the dedup key** (names normalized to
    title-case at extraction — that normalization *is* the cross-document dedup; no
    embedding-similarity entity resolution).
  - `entity_type` resolved by **majority vote**: `Counter(new + existing).most_common` → first.
  - `description`: existing + new concatenated (`<SEP>`-joined), deduped preserving order.
  - `source_id` / `file_path`: merged, capped (`max_source_ids_per_entity` default 300; FIFO or
    KEEP-oldest policy).
- **Relationship merge** (`_merge_edges_then_upsert`):
  - Edge key is the **sorted (src,tgt) pair** → undirected dedup.
  - `weight` = **sum** of all occurrence weights (each extraction contributes 1.0) → frequent
    relations rank higher.
  - `keywords` = set-union of comma-split keywords.
  - `description` aggregated like entities.
- **Description aggregation with LLM only when needed** (`_handle_entity_relation_summary`): if a
  merged description list has `< force_llm_summary_on_merge` (default **8**) fragments AND
  `< summary_context_size` (12000) tokens, just concatenate — *no LLM call*. Above threshold, a
  **map-reduce summarization** kicks in (chunk → summarize → recursively summarize) targeting ~600
  tokens. The cost-control valve: most merges cost zero LLM calls.
- After merge, re-embed and upsert into the VDBs.

**Applicability.** **VERY HIGH** for personal data (grows incrementally: new emails, notes,
messages daily). Name-normalization-as-dedup is simple/cheap but **brittle** ("Bob" vs "Robert
Smith" won't merge) — add lightweight alias/embedding resolution on top. The lazy-summarization
threshold (concatenate until N fragments, only then summarize) is an excellent cost lever.

## 2.5 Storage architecture — four stores, pluggable, kept in sync

**Four storage roles** (`lightrag/lightrag.py` defaults; registry in `lightrag/kg/__init__.py`):

| Role | Default impl | Holds | Alt backends |
|---|---|---|---|
| **KV store** | `JsonKVStorage` | full docs, text chunks, LLM response cache, per-doc entity/relation lists, chunk-tracking | Redis, Mongo, Postgres, OpenSearch |
| **Vector store** | `NanoVectorDBStorage` | 3 collections: `entities_vdb`, `relationships_vdb`, `chunks_vdb` | Milvus, Qdrant, Faiss, Chroma, PGVector, Mongo, OpenSearch |
| **Graph store** | `NetworkXStorage` (in-memory + pickle) | nodes + edges with all attributes | Neo4j, Memgraph, AGE/PGGraph, Mongo, OpenSearch |
| **Doc-status store** | `JsonDocStatusStorage` | per-doc pipeline status (pending/processing/done/failed) | Redis, Mongo, Postgres, OpenSearch |

**How stores stay in sync** (indexing path):
- **Deterministic content-hash IDs are the synchronization key.** `compute_mdhash_id`:
  chunk → `chunk-<md5>`; doc → `doc-<md5>`; entity → `ent-<md5(name)>`; relation →
  `rel-<md5(src+tgt)>`.
  Because the entity VDB id derives from the *entity name* (same dedup key as the graph), an upsert
  to `entities_vdb` and to the graph node always address "the same" entity. Same for
  `rel-<md5(src+tgt)>`. **No cross-store foreign keys — the hash is the join.**
- After a merge, the orchestrator writes in lockstep: graph `upsert_nodes_batch` /
  `upsert_edges_batch`; vector `asyncio.gather(entities_vdb.upsert, relationships_vdb.upsert)`
  with content = name+description / keywords+endpoints+description; deletes legacy reverse-direction
  `rel-` ids so undirected edges don't duplicate.
- Storage selected by class-name string (`graph_storage="NetworkXStorage"`), validated against
  `STORAGE_IMPLEMENTATIONS` + `STORAGE_ENV_REQUIREMENTS`. Swapping is a one-line config change.

**Applicability.** **HIGH for the pattern; default stack ideal for local-first.** Default
(JSON KV + NanoVectorDB + NetworkX pickle) is *exactly* a single-user local-first profile. Reusable
idea: **content-hash IDs as the cross-store join key** (eliminates a sync table, idempotent
upserts). The four-role split (KV / vector / graph / status) is clean even if you don't adopt the
code.

## 2.6 Cost — why ~10× (and the real numbers)

**Index time:** LightRAG = **1 LLM call/chunk** for extraction (+1 optional gleaning by default →
up to 2; +occasional summarization only above threshold). No community-detection / report stage.
GraphRAG = multiple extraction passes per chunk **plus** Leiden **plus** an LLM report per
community.

**Query time:** LightRAG = 1 keyword-extraction call + retrieval + 1 answer call; retrieval
overhead **<100 tokens**. GraphRAG global search = **~610,000 tokens and hundreds of API calls**
per query (paper comparison) — the ~6,000× retrieval-overhead figure rounded to "~10× cheaper"
once answer generation is included.

**Incremental update:** LightRAG = merge-in-place, no community rebuild → near-zero extra LLM cost.
GraphRAG = must regenerate community reports — paper estimates **~1,399 communities × 2 × ~5,000
tokens**. The largest cost gap and the strongest argument for LightRAG's design.

**Sources for cost figures:** [learnopencv LightRAG](https://learnopencv.com/lightrag/),
[ragdollai cost analysis](https://www.ragdollai.io/blog/lightrag-vector-rags-speed-meets-graph-reasoning-at-1-100th-the-cost),
[gitpicks token-cost](https://gitpicks.dev/featured/lightrag-vs-graphrag-token-cost-performance),
[arXiv 2410.05779](https://arxiv.org/abs/2410.05779). Code claims from the cloned repo:
`lightrag/operate.py`, `lightrag/prompt.py`, `lightrag/lightrag.py`, `lightrag/constants.py`,
`lightrag/kg/__init__.py`.

## 2.7 LightRAG — techniques worth borrowing (ranked)

1. **Single-call typed extraction** (entities + relations + edge-keywords together). Copy
   atomic-delimiter discipline + overridable entity-type list. Gleaning 0 initially. *Effort low,
   value very high.*
2. **Vector-entry + one-hop-graph-expansion retrieval with inline `source_id` provenance.** Core
   graph-augmentation mechanic; storage-agnostic; trivial in-memory for one user.
3. **Content-hash IDs as the cross-store join key** (`ent-<md5(name)>`, `rel-<md5(src+tgt)>`).
   Eliminates a sync table; idempotent upserts; keeps graph/vector/KV consistent for free.
4. **In-place incremental merge** with name-normalization dedup + summed edge weights + lazy
   (threshold-gated) description summarization. (Add alias/embedding ER — name-only is too brittle.)
5. **Dual-level query keyword split** (low→entities, high→relationships) with `mix` fallback to raw
   chunk vectors. `local` + `mix` cover most personal-data needs.
6. **Four-role pluggable storage** with a local-first default (JSON KV + NanoVectorDB + NetworkX).
7. **Degree-as-importance ranking + `cosine_better_than_threshold` pre-filter.** Cheap priors.

**Open decision (from this pass):** entity-resolution strategy (name-normalization too weak —
alias tables vs embedding-similarity merge) and whether to keep gleaning (recall vs 2× extraction).

---

# §3 — Microsoft GraphRAG + LazyGraphRAG (and cheaper variants)

Concrete methods from MS GraphRAG and successors/variants (LazyGraphRAG, nano-graphrag, KET-RAG,
E2GraphRAG), plus incremental alternatives (LightRAG, Graphiti). Verdicts anchored to a single-user
local corpus of hundreds–thousands of docs — **not enterprise gigabytes**.

## 3.1 The indexing dataflow — chunking, extraction, gleaning, claims

```
Documents
  → TextUnits (chunk, default 1200 tokens)
  → Entity extraction       (LLM call per chunk)
  → Relationship extraction (same call)
  → GLEANING loop           (1..max_gleanings extra LLM calls per chunk)
  → Merge same-title/type entities & relationships across chunks
  → Entity description summarization      (LLM call per merged entity)
  → Relationship description summarization (LLM call per merged rel)
  → Claim/covariate extraction (OPTIONAL, off by default)
  → Leiden community detection (no LLM)
  → Community report generation (LLM call per community, all levels)
```

- **Chunking (TextUnits):** default **1200 tokens**. Docs note the trade-off — *"a 600-token chunk
  extracts nearly twice as many entity references as a 2400-token chunk"* — smaller = higher recall
  but more LLM calls. [default_dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/)
- **The gleaning loop (key technique):** after the first extraction, re-prompt with a CONTINUE_PROMPT
  ("MANY entities were missed — add them") plus a LOOP_PROMPT yes/no "should we continue?". Pre-v2.2
  forced a single-token YES/NO via `logit_bias: {YES:100, NO:100}, max_tokens:1`; reasoning models
  broke this so it's now a prompted judgment. Runs up to `max_gleanings` times.
  [graphrag #615](https://github.com/microsoft/graphrag/issues/615) ·
  [neo4j integrating GraphRAG](https://neo4j.com/blog/developer/global-graphrag-neo4j-langchain/)
- **Claim/covariate extraction:** optional, **off by default**, because it "generally requires
  prompt tuning to be useful." [default_dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/)

**Why expensive — the "75% before any query" problem:** graph extraction (the first ~4 LLM steps)
≈ **75% of total indexing cost**, spent before a single query. With gleaning, a single chunk can
incur **3–6+ LLM calls** (1 extract + N gleanings, then per-entity/per-relationship summarization).
[graph-praxis: five papers](https://medium.com/graph-praxis/five-papers-quietly-killing-the-llm-tax-in-graphrag-5ff2e75923f9) ·
[KET-RAG arXiv 2502.09304](https://arxiv.org/abs/2502.09304)

| Component | Verdict | Reason |
|---|---|---|
| Chunking into TextUnits | **BORROW** | universal; tune chunk size to recall needs |
| Entity + relationship extraction | **BORROW (selectively)** | core value, but gate it |
| Gleaning loop | **BORROW, cap at 0–1** | 2nd+ pass multiplies cost for marginal recall on a small corpus |
| Description summarization | **MOSTLY AVOID** | per-entity LLM summarization is major cost, little payoff at small scale |
| Claim/covariate extraction | **AVOID** | off by default even in MS's pipeline; needs prompt tuning |

## 3.2 Community detection + hierarchical summarization

**What it is.** **Hierarchical Leiden** recursively partitions the entity graph into nested
communities; an LLM generates a **report per community, at every level, bottom-up** (higher levels
fold in lower). These power **global** ("what are the main themes?") query-focused summarization.
[default_dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/) ·
[arXiv 2404.16130 "Local to Global"](https://arxiv.org/abs/2404.16130)

**Verdict: OVERKILL for a personal corpus.**
- Community report generation is one of the heaviest LLM cost centers; it exists for **corpus-wide
  sensemaking** on **~1M-token enterprise datasets**.
- A single user almost never needs "summarize the global themes of my entire corpus" — they ask
  entity/fact lookups (local-search territory).
- Even **nano-graphrag drops the map-reduce** and only summarizes the top-K central communities
  (default 512). [nano-graphrag](https://github.com/gusye1234/nano-graphrag)
- LightRAG and Graphiti **skip community summarization entirely** for evolving data.
- **If global sensemaking is ever needed:** prefer LazyGraphRAG's *query-time* community extraction
  over GraphRAG's *index-time* summarization (§3.4).

## 3.3 Local vs Global search

| | **Local** | **Global** | **DRIFT** |
|---|---|---|---|
| Mechanism | entity-centric: seed entities → fan out to neighbors + their chunks | map-reduce over **all** community summaries: partial answers (map) → combine (reduce) | local query seeded with community context → follow-ups |
| Cost | cheap | expensive (touches every community summary) | medium |
| Fits | "X's properties?" / specific entity Q&A | "main themes across the corpus?" | entity Q needing broader context |

[query/overview](https://microsoft.github.io/graphrag/query/overview/) ·
[datacamp GraphRAG](https://www.datacamp.com/tutorial/graphrag)

**Verdict:** **Local search FITS** personal Q&A; **Global is OVERKILL.** Local (entity → neighbor
traversal → attach raw chunks) is the pattern to borrow — and it needs no community summaries, so
adopting it lets you skip §3.2 entirely.

## 3.4 LazyGraphRAG — defer everything to query time

**Core idea.** Eliminates all index-time LLM work. Indexing uses only **NLP noun-phrase
extraction** to build a concept co-occurrence graph + cheap community detection. *"None — the lazy
approach defers all LLM use until query time."*

At query time: iterative-deepening best-first + breadth-first:
1. **Best-first:** rank text chunks by embedding similarity, then rank communities by their top
   chunks.
2. **Breadth-first:** an **LLM sentence-level relevance assessor** rates top-k untested chunks.
3. **Iterative deepening:** recurse into sub-communities until *z* consecutive communities yield
   zero relevant chunks or the **relevance-test budget** is exhausted.

A single `relevance test budget` knob trades cost for quality.

**Cost (MS Research, verified):**
- **Indexing cost = identical to vector RAG = 0.1% of full GraphRAG.**
- At budget Z500: matches GraphRAG global-search quality at **~4% of its query cost**; at higher
  budgets, **>700× lower query cost** than GraphRAG global search for comparable quality.
[Microsoft Research: LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)

**Verdict: the single most relevant model to borrow from.** "Cheap structural index now, spend LLM
tokens only on what a query touches" is ideal for local-first. Trade-off: higher per-query
latency/cost, bounded by the budget knob; queries are infrequent for a single user.

## 3.5 The incremental-update problem

**Documented pain.** Adding new docs "needs to recreate the graph... and **communities will be
recomputed — resulting in re-summarization**." Caching avoids re-extracting old docs, but the
**community/summarization stage is the bottleneck**. MS's mitigation is a separate
`graphrag.append`/update command that slots new entities into existing communities and only
re-summarizes changed ones, with user-configurable thresholds for when Leiden must fully re-run.
**Worst case "degrades to the same performance as a normal indexing"** — a full re-index. Kept a
*separate command* so base `index` stays predictable.
[graphrag #741](https://github.com/microsoft/graphrag/issues/741) ·
[#511](https://github.com/microsoft/graphrag/discussions/511)

**Why incremental designs win for evolving personal data:**
- **LightRAG:** adds nodes/edges directly, **no community step to rebuild** — cheaper/faster
  incremental merge; dual-level retrieval. [adasci LightRAG](https://adasci.org/a-deep-dive-into-lightrag/) ·
  [arXiv 2410.05779](https://arxiv.org/abs/2410.05779)
- **Graphiti:** purpose-built for agent/personal memory. **Incremental real-time updates, no batch
  recompute**, bi-temporal model, and **no LLM calls at retrieval** (hybrid embeddings + BM25 +
  graph traversal, ~P95 300ms). Explicitly critiques GraphRAG as batch-oriented and "unsuitable as
  holistic memory for agentic applications". [neo4j: Graphiti](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)

**Verdict: AVOID GraphRAG's update model. BORROW Graphiti/LightRAG's incremental merge.** Personal
data is constantly evolving; a pipeline that risks a full re-index + community re-summarization on
update is a non-starter. Design for **append-only incremental merge with no global recompute** from
day one.

## 3.6 Entity resolution / dedup (and where it breaks)

Baseline GraphRAG merges entities by **exact title+type string match** — "Barack Obama" vs
"President Obama", "Sinn Fein" vs "Sinn Féin" become **separate nodes**, fragmenting the graph.
Each chunk is processed semi-independently, so the same real-world entity spawns duplicates string
matching can't reconcile. Known bug merging same-title/**different-type** entities
([#1718](https://github.com/microsoft/graphrag/issues/1718)).

**Documented quality cliff:** below ~85% entity-resolution accuracy the graph becomes "toxic" — *"a
single misidentified entity poisons every path that traverses through it."* At 5 hops with 85%
resolution, accuracy drops to ~44%. [sowmith.dev: entity disambiguation](https://www.sowmith.dev/blog/graphrag-entity-disambiguation)

**Better pattern (Neo4j/LangChain GraphRAG implementation) — 3-stage:**
1. **Embedding KNN** — embed name+description, k-NN graph, group via weakly-connected components
   (≈0.95 similarity).
2. **Edit-distance filter** — candidate pairs within ≤3 char edit distance ("Sinn Fein"↔"Sinn Féin").
3. **LLM adjudication** — structured yes/no merge: typos→merge; different numbers/dates/products→don't.
[neo4j: constructing the graph](https://neo4j.com/blog/developer/global-graphrag-neo4j-langchain/)

**Verdict: BORROW the embedding+distance+LLM pipeline; AVOID naive string-match dedup.** For a
personal corpus a small accurate graph beats a large noisy one. Cheap enough (embeddings nearly
free, LLM only adjudicates close candidates).

## 3.7 Cost numbers (real reports)

| Source | Dataset | Model | Cost |
|---|---|---|---|
| Legal case dataset (early 2024) | 5 GB | GPT-4 era | **$33,000** to index |
| Same, mid-2025 | 5 GB | LazyGraphRAG / cheap models | **~$33** (0.1%) |
| User zanderjiang | 1 MB txt | GPT-4-Turbo | expensive index; **~$0.40 per search call** |
| User mystvearn | 1000-page PDF | GPT-4-Turbo | **$120** |
| User shaoqing404 | ~1M words (1.2M tok) | DeepSeek | **~$8.20** |
| FalkorDB example | 45,000 words (57.6k tok) | GPT-3.5-Turbo | **$2.25**, ~48 min |
| Demo dataset | small | GPT-4-Turbo | **~$5** out of the box |
| General estimate | 1M tokens | — | **$20–50** + hours compute |

Sources: [graph-praxis cost cliff](https://medium.com/graph-praxis/the-graphrag-cost-cliff-how-33-000-became-33-in-eighteen-months-be1b0fbe37e4) ·
[graphrag #440](https://github.com/microsoft/graphrag/discussions/440) ·
[falkordb](https://www.falkordb.com/blog/reduce-graphrag-indexing-costs/)

**Takeaways:** per-query cost (~$0.40 with premium models) and the ~10,000× index premium vs vector
search are the alarming figures for a single user. Model choice swings cost 10–15×. LazyGraphRAG's
0.1% indexing cost is the structural fix, not just model swaps.

## 3.8 Cheaper variants worth knowing

- **nano-graphrag** (~1100 LoC): keeps extraction + community detection + local/global, **drops
  covariates**, replaces map-reduce with top-K central communities, two-model split (smart for
  plan/respond, cheap for summarize). [github](https://github.com/gusye1234/nano-graphrag)
- **KET-RAG**: multi-granular — full LLM graph only on a **skeleton of key chunks**, lightweight
  **keyword↔chunk bipartite graph** for the rest. **>10× cheaper indexing**, up to **+32.4%
  generation quality**. [arXiv 2502.09304](https://arxiv.org/abs/2502.09304)
- **E2GraphRAG**: **SpaCy** for entity graph (no LLM extraction) + LLM summary tree + bidirectional
  entity↔chunk index + adaptive local/global routing. **~10× faster indexing than GraphRAG, ~100×
  faster retrieval than LightRAG.** [arXiv 2505.24226](https://arxiv.org/abs/2505.24226)

## 3.9 GraphRAG family — borrow / avoid (ranked)

**BORROW**
1. **LazyGraphRAG's defer-to-query-time** — cheap structural index, LLM only on what a query
   touches; bounded by a relevance-test budget. 0.1% of GraphRAG indexing cost.
2. **Incremental append-only merge (Graphiti/LightRAG)** — no community recompute, no LLM at
   retrieval, bi-temporal conflict resolution.
3. **Local search (entity-centric neighbor traversal)** — matches personal Q&A; no community
   summaries needed.
4. **3-stage entity resolution** — embedding KNN → edit-distance filter → LLM adjudication.
5. **TextUnit chunking with deliberate size tuning** — smaller chunks = better entity recall, more
   calls.
6. **Selective/skeleton extraction (KET-RAG)** — full LLM extraction only on key chunks.
7. **NLP-based extraction (SpaCy/noun phrases)** where quality allows.

**AVOID**
1. **Index-time hierarchical community summarization** (Leiden + bottom-up LLM reports) — heaviest
   cost, enterprise sensemaking, pointless for personal Q&A.
2. **Global map-reduce search.**
3. **GraphRAG's update model** — worst case = full re-index.
4. **Naive string-match dedup** — fragments the graph; <85% → toxic.
5. **Aggressive gleaning (multiple passes)** — cap at 0–1.
6. **Per-entity/per-relationship LLM description summarization.**
7. **Claim/covariate extraction.**
8. **Premium models (GPT-4-Turbo) for indexing** — 10–15× multiplier.

**Net steer:** build a **lazy, incremental, local-search graph** — cheap structural/NLP index +
clean entity resolution + query-time relevance scoring with a budget knob — and **skip communities,
global map-reduce, claims, heavy gleaning.**

---

# §4 — Cognee + Mem0 + Entity Resolution

## 4.1 Cognee (topoteretes/cognee)

### 4.1.1 The ECL pipeline (Extract → Cognify → Load)
Four verbs: `remember` (add), `recall` (search), `forget` (delete), `improve` (memify).

| Stage | What happens |
|---|---|
| **Extract** | Ingest raw content (APIs, DBs, files); produce `Document` objects with metadata. |
| **Cognify** | Transformation core — sequential tasks: (1) classify document, (2) check permissions, (3) extract chunks (configurable chunker), (4) **extract graph** — LLM identifies entities + relationships, inserts nodes/edges, (5) summarize each chunk, (6) embed datapoints + finalize edges. Incremental: re-runs skip already-processed content. |
| **Load** | Write vector embeddings + graph triplets + relational metadata/provenance to the three stores. |

A separate **Memify** post-processing pipeline runs enrichment/optimization after the core graph is
built ("make memory smarter over time"). Sources:
[docs.cognee.ai/.../cognify](https://docs.cognee.ai/core-concepts/main-operations/cognify),
[how-cognee-builds-ai-memory](https://www.cognee.ai/blog/fundamentals/how-cognee-builds-ai-memory),
[deepwiki/topoteretes/cognee](https://deepwiki.com/topoteretes/cognee).

### 4.1.2 Data model: DataPoints (Pydantic) as the unifying schema
The most reusable architectural idea. Every piece of information is a **`DataPoint`** — a typed
Pydantic base class that **doubles as both node schema and edge schema**.
- Base `DataPoint` carries `metadata` and `index_fields` (mark which fields get embedded/indexed,
  e.g. `index_fields = ["name"]`).
- Specialized subclasses: `Entity`, `EntityType`, `DocumentChunk`, `TextSummary`.
- In cognify, Cognee: assigns **UUID + version + timestamp**, **recursively unpacks nested
  DataPoints** (a `Company` referencing `Person` founders becomes connected nodes), **deduplicates
  identical entities**, embeds the indexed fields.
- Conversion in `get_graph_from_model`: fields containing other DataPoints become **edges**; scalar
  fields become **node properties**. An optional `Edge` metadata object in a tuple attaches edge
  attributes.
- LLM extraction constrained to a Pydantic `KnowledgeGraph` schema via **Instructor** (default) or
  **BAML**. Extraction prompts have strictness modes: balanced / simple / strict / guided.

Sources: [8.2-graph-entities-and-relationships](https://deepwiki.com/topoteretes/cognee/8.2-graph-entities-and-relationships),
[custom-data-models](https://docs.cognee.ai/guides/custom-data-models),
[dev.to cognee](https://dev.to/om_shree_0709/cognee-building-the-next-generation-of-memory-for-ai-agents-oss-3jm1).

### 4.1.3 Entity dedup & ontology grounding (directly relevant)
1. LLM extracts typed entities unconstrained.
2. **`FuzzyMatchingStrategy`** maps extracted names to canonical ontology classes using Python
   `difflib.get_close_matches()` at an **80% similarity threshold**.
3. **Canonicalization:** matched entity's LLM name replaced with the canonical **ontology
   URI-derived name** → eliminates cross-document duplicates.
4. **Structural enrichment:** BFS over the ontology injects inherited relations
   (`ElectricCar ⊑ Car`).
5. Each node gets an **`ontology_valid` flag** so downstream consumers know grounding quality;
   un-grounded extraction kept as fallback.
[grounding-ai-memory](https://www.cognee.ai/blog/deep-dives/grounding-ai-memory).

### 4.1.4 Backends — embedded/local
**Poly-store, embedded-by-default.** Runs fully embedded with no infrastructure:

| Role | Default (embedded) | Other supported |
|---|---|---|
| Graph | **Kuzu** | Neo4j, NetworkX (in-memory), FalkorDB, Memgraph, Amazon Neptune |
| Vector | **LanceDB** | pgvector, Qdrant, Weaviate, Redis, Chroma, Pinecone |
| Relational | **SQLite** | DuckDB, Postgres |

Invariant: **graph and vector stores stay linked — every graph node has a corresponding
embedding** → pivot between semantic similarity and relational traversal. Sources:
[vector-stores](https://docs.cognee.ai/setup-configuration/vector-stores),
[kuzu+cognee](https://blog.kuzudb.com/post/cognee-kuzu-relational-data-to-knowledge-graph/),
[lancedb case study](https://www.lancedb.com/blog/case-study-cognee).

### 4.1.5 Retrieval / search types
Auto-routed search; explicit types: `GRAPH_COMPLETION` (LLM answer over graph-traversal context),
`RAG_COMPLETION` (classic vector-chunk RAG), `INSIGHTS` (entity+relationship structures), `CHUNKS`,
`SUMMARIES`, `CODE`, `NATURAL_LANGUAGE`. An **in-memory projected graph** supports traversal,
vector-distance calc, and **triplet importance scoring** at query time. A session-memory "fast
cache" is queried first, then the permanent graph.
[deepwiki](https://deepwiki.com/topoteretes/cognee),
[vectors-and-graphs-in-practice](https://www.cognee.ai/blog/fundamentals/vectors-and-graphs-in-practice).

**Reusable from Cognee:** (1) DataPoint-as-Pydantic dual node/edge schema with `index_fields`;
(2) embedded Kuzu+LanceDB+SQLite triad keeping every node embedded; (3) structured-output
extraction (Instructor/BAML) to a `KnowledgeGraph` schema with strictness modes; (4) ontology
fuzzy-match canonicalization with an `ontology_valid` flag.

## 4.2 Mem0 graph memory + the over-capture / re-ingestion problem

### 4.2.1 Two-phase memory pipeline (base algorithm)
Mem0 (paper *Building Production-Ready AI Agents with Scalable Long-Term Memory*,
[arXiv:2504.19413](https://arxiv.org/html/2504.19413v1)) splits writes into two LLM phases:

**Phase 1 — Extraction.** An LLM function φ over message pair `(m_{t-1}, m_t)` plus two context
sources: a **rolling conversation summary S** and **recent messages**. Output = candidate facts Ω.

**Phase 2 — Update.** For each candidate, retrieve **top-s semantically similar existing memories**
and let the LLM pick one op:

| Op | Trigger |
|---|---|
| **ADD** | no semantically equivalent memory exists |
| **UPDATE** | existing memory augmented with complementary info |
| **DELETE** | new info contradicts an existing memory |
| **NOOP** | no change needed |

`DEFAULT_UPDATE_MEMORY_PROMPT` (`mem0/configs/prompts.py`): UPDATE keeps the **same ID** and merges
to the richer version ("likes cheese pizza" + "loves chicken pizza" → "Loves cheese and chicken
pizza"); DELETE fires on contradiction. The fact-extraction prompt (`FACT_RETRIEVAL_PROMPT`) is
preference-centric (7 categories: preferences, personal details, plans, service prefs, health,
professional, misc) and instructs **"Create the facts based on the user … messages only. Do not pick
anything from the system messages."** Sources: `mem0/configs/prompts.py`,
[arXiv:2504.19413](https://arxiv.org/html/2504.19413v1),
[memory-operations](https://docs.mem0.ai/core-concepts/memory-operations).

### 4.2.2 Graph variant (Mem0g)
- **Entity Extractor** → entities + types.
- **Relationship Generator** → triplets `(source, relation, destination)`.
- **Storage/update:** compute node embeddings, **search existing nodes above similarity threshold
  `t`** (the entity-resolution step), then an **LLM-based Update Resolver** decides add both / add
  one / update. Conflicting edges **marked invalid/obsolete rather than physically deleted** →
  temporal reasoning.
- Graph search: extract entities from query → embedding match to nodes → **rerank with BM25**.

> **Caveat:** as of the latest OSS release, **graph_store support was removed from the Mem0 OSS
> SDK** (~4000 LOC deleted; previously Neo4j/Memgraph/Kuzu/Apache AGE/Neptune), replaced by **"entity
> linking"** (entities extracted on every add into a parallel `{collection}_entities` vector
> collection, matched at query time to **boost** memories; relationships no longer a queryable
> graph). The graph mechanics remain valid as a *design reference* only. Sources:
> [graph-memory](https://docs.mem0.ai/platform/features/graph-memory),
> [memo.d.foundation/breakdown/mem0](https://memo.d.foundation/breakdown/mem0),
> [deepwiki mem0 graph](https://deepwiki.com/mem0ai/mem0/4-graph-memory).

### 4.2.3 ⭐ Root cause of "everything gets re-extracted" — the bleed bug, diagnosed
A production audit ([mem0 issue #4573](https://github.com/mem0ai/mem0/issues/4573), *"auditing
10,134 mem0 entries: 97.8% were junk"*) is the single most useful source. After 32 days, only ~38
entries were clean.

| Cause | Share | Description |
|---|---|---|
| **Boot-file / identity restating** | 52.7% | system prompts/agent identity re-extracted as memories ("uses she/her" stored 50+ times) |
| **Heartbeat/system noise** | 11.5% | cron output, boot sequences accumulate |
| **System architecture dumps** | 8.2% | tool configs/state stored as memory instead of static metadata |
| **Transient task state** | 7.4% | "Finish proposal by Friday" persists forever |
| **Hallucinated profiles** | 5.2% | small model invents demographics |
| **⚠️ Feedback-loop amplification** | — | **recalled memories re-extracted and stored again — one hallucination "User prefers Vim" multiplied to 808 copies** |

That last row **is the "retrieved knowledge got re-ingested as memory" bug.** Recommended fixes (in
priority), directly applicable write-policy lessons:
1. **Tag recalled/retrieved content so it is excluded from extraction** (break the feedback loop).
2. **Quality gate**: score candidates *before* storage.
3. **Negative examples in the extraction prompt** (explicit "what NOT to store").
4. **Add a REJECT action** to the update-decision pipeline.
5. **Make extraction context-aware** of whether the "user" is human vs agent/system.

Corroborating: Harvard D3 found *indiscriminate storage performs worse than no memory*, and
**filtering before storage gave ~10% boost**. Mem0's own ingestion-control guidance recommends
**custom "only store CONFIRMED facts" instructions, confidence thresholds (0.8+ high-stakes / 0.6+
general), and the `infer` flag** (`infer=False` = raw store, no dedup; keep modes consistent to
avoid dup explosions). Sources: [issue #4573](https://github.com/mem0ai/mem0/issues/4573),
[controlling-memory-ingestion](https://docs.mem0.ai/cookbooks/essentials/controlling-memory-ingestion),
[state-of-ai-agent-memory-2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026).

**Write-policy lessons (apply to our pipeline):**
- **Provenance-tag every piece of context** with a source role (`user` / `assistant` /
  `retrieved_knowledge` / `system`). **Never feed `retrieved_knowledge` or `system` back into the
  extractor.** Kills the bleed.
- **Two-phase write** (extract → resolve ADD/UPDATE/DELETE/NOOP against top-s similar) is sound —
  keep it, but add a **5th REJECT/quality-gate** before persistence.
- Prefer **UPDATE-with-same-ID + invalidate-don't-delete** over churn.
- **Don't store transient/ephemeral state** as durable memory (TTL or a "durability" classifier).

## 4.3 Entity Resolution (the hard write-side problem)

ER detects different mentions/profiles referring to the same real-world entity. Inherently
**O(n²)**, so the standard pipeline is **Blocking → Matching → Clustering/Canonicalization**, with
**coreference** and **disambiguation** as front-end NLP steps. Surveys: Papadakis et al., *A Survey
of Blocking and Filtering Techniques for ER* (ACM CSUR 2020, [arXiv:1905.06167](https://arxiv.org/abs/1905.06167));
Christophides et al., *End-to-End ER for Big Data: A Survey* (2020).

### 4.3.1 Blocking / candidate generation (kill the O(n²))

| Method | Mechanics | Local-first fit |
|---|---|---|
| **Standard / Token blocking** | blocking key (token, first-3-chars of surname); compare only records sharing a key | ✅ trivial baseline |
| **Q-gram blocking** | keys = character q-grams; tolerant to typos/variants | ✅ good for messy personal names |
| **Sorted Neighborhood (SNM)** | sort by key, slide a fixed window; compare within window | ✅ memory-light, streaming-friendly |
| **Suffix arrays / Canopy clustering** | index suffixes / cheap distance → overlapping canopies before exact match | ◐ optional |
| **LSH (MinHash)** | shingle key → MinHash → hash to buckets; compare within buckets; sub-quadratic | ✅ scales, overkill at single-user volume |
| **DeepBlocker (learned)** | **self-supervised tuple embeddings** (AutoEncoder / Cross-Tuple-Training / Hybrid; FastText) → **kNN (top-K, e.g. K=50)** in vector space → candidate set; no labels | ✅✅ for us this is **ANN over existing embeddings** — reuse infra |

Sources: [arXiv:1905.06167](https://arxiv.org/abs/1905.06167),
[DeepBlocker VLDB](https://www.vldb.org/pvldb/vol14/p2459-thirumuruganathan.pdf),
[github qcri/DeepBlocker](https://github.com/qcri/DeepBlocker).
**Takeaway:** at single-user scale, **embedding-ANN blocking on the existing vector index** is the
natural candidate generator; keep cheap q-gram/normalized-name blocking as a deterministic complement.

### 4.3.2 Embedding-based matching (dedup decision)
- **Ditto** ([VLDB 2020](https://arxiv.org/pdf/2004.00584), [github](https://github.com/megagonlabs/ditto)):
  matching as **sequence-pair classification** with a pretrained LM. Serialize each record as
  `COL <attr> VAL <value> …`, feed the pair to BERT/DistilBERT/RoBERTa → match/no-match. Boosters:
  domain-knowledge tagging, TF-IDF summarization of long strings, MixDA augmentation. SOTA +29% F1,
  up to 96.5% F1.
- **Lightweight local-first alternative:** sentence-embedding **cosine over candidate pairs +
  threshold**, or a small logistic-regression/GBM over field comparators (Jaro-Winkler, edit
  distance, token Jaccard, embedding cosine). The **Magellan / dedupe / Fellegi–Sunter** lineage —
  cheap, explainable, offline.
Sources: [Ditto VLDB](https://dl.acm.org/doi/abs/10.14778/3421424.3421431),
[py_entitymatching/Magellan](https://pypi.org/project/py-entitymatching/),
[biggorilla entity-matching](https://www.biggorilla.org/software_cat/entity-matching/index.html).

### 4.3.3 Canonicalization / surface-form normalization / alias tables
- **Normalize surface forms**: lowercase, strip honorifics/diacritics, expand nicknames, collapse
  whitespace; keep a **canonical record per entity** as the merge target.
- **Alias table**: every observed surface form → canonical entity ID ("mom"/"my mother"/"Sara" →
  `person:sara`). Small and high-value for a personal KG.
- **Cognee's pattern** (§4.1.3): `difflib.get_close_matches` at 80% → replace with canonical name;
  flag grounded vs not.
- **CESI** ([arXiv:1902.00172](https://ar5iv.labs.arxiv.org/html/1902.00172)) for open-KB
  canonicalization: learn embeddings (HolE objective) with **soft penalties** pulling together
  phrases that **side information** says are equivalent (IDF token overlap, PPDB paraphrases,
  WordNet, morphological normalization, entity-linking), then **HAC clustering**; each cluster = one
  canonical entity. Lesson: **combine multiple weak signals as soft constraints, not hard filters.**

### 4.3.4 Coreference resolution (anchor "she" / "my sister" / "the colleague")
Essential because personal conversational data is pronoun-heavy. Resolve mentions into clusters,
then attach the cluster to a known entity.

| Tool | Mechanics / notes | Fit |
|---|---|---|
| **fastcoref / LingMess** ([github](https://github.com/shon-otmazgin/fastcoref), [arXiv:2209.04280](https://arxiv.org/pdf/2209.04280)) | spaCy-pluggable. `F-COREF` fast (2.8K docs/25s on V100), `LingMessCoref` accurate SOTA. Returns clusters as strings or char offsets; **runs on CPU**. | ✅✅ best local default |
| **Maverick** ([github](https://github.com/SapienzaNLP/maverick-coref), ACL 2024) | `pip install maverick-coref`; outputs `clusters_token_offsets` + `clusters_text_mentions` (`[['Rome','The city','its'], ['Barack Obama','the president']]`). Accurate, efficient, no giant LLM. Supports predefined mentions + singletons. | ✅✅ strong, easy API |
| **spaCy experimental coref** (`en_coreference_web_trf`) | cluster-based, OntoNotes-style; transformer-heavy (GPU). Weak on split antecedents. | ◐ |
| **neuralcoref** | legacy spaCy 2.x; deprecated. | ✗ |
| **LLM-based coref** | prompt LLM to output mention clusters / rewrite pronouns to referents. Best for hard context-dependent cases ("my sister" → which person). Slower/costlier. | ✅ fallback for low-confidence |

**Pipeline pattern:** run coref to cluster mentions → for first-person possessives ("my sister") use
**conversation/speaker context** to bind to the user's known relations → replace pronouns with
canonical entity IDs **before** extraction so triples reference entities, not pronouns.
Sources: [fastcoref](https://github.com/shon-otmazgin/fastcoref),
[maverick-coref](https://github.com/SapienzaNLP/maverick-coref),
[explosion.ai/blog/coref](https://explosion.ai/blog/coref).

### 4.3.5 Disambiguation of same-name different-entity (two "Ahmed"s)
This is **Entity Linking / Named-Entity Disambiguation (NED)**
([wikipedia](https://en.wikipedia.org/wiki/Entity_linking)):
1. **Candidate generation** from alias/surface-form dictionary ("Ahmed" → {Ahmed-cousin,
   Ahmed-coworker}).
2. **Disambiguation** combining:
   - **Local context similarity** — embed the mention's surrounding text, compare to each
     candidate's profile/context embedding.
   - **Coherence / collective disambiguation** — pick candidates mutually consistent with other
     entities in the same conversation (graph coherence, PageRank-style).
   - **Popularity / recency prior** — for a personal KG, prefer the recently/frequently-mentioned
     candidate.
   - **Attribute checks** — disambiguate on attributes (workplace, relationship type, location).
For personal data the strongest signal is **conversation context + your existing graph
neighborhood** (who else is mentioned, what relationship). Disambiguate **per-mention against your
own canonical set**, not Wikipedia.

### 4.3.6 Incremental / streaming entity resolution
Mentions arrive over time and must match an **existing canonical set**.
- **Pattern:** maintain a persistent **blocking index** (q-gram/normalized-name + ANN over entity
  embeddings). For each new mention: block → score candidate canonical entities → **link to best
  match above threshold**, else **create a new canonical entity**. Update the index incrementally.
  (Lit: [arXiv:1402.4417](https://arxiv.org/pdf/1402.4417),
  [MDPI 13/12/568](https://www.mdpi.com/2078-2489/13/12/568),
  [arXiv:1407.3751](https://arxiv.org/pdf/1407.3751).)
- **Tooling analog:** dedupe's **Gazetteer/Static matching** — match incoming records against an
  already-canonicalized reference set (exactly incremental linking).
- Allow **merge/split**: later evidence may reveal two canonical nodes are the same (merge) or one
  conflated two people (split). Keep edges **provenance-stamped** so merges/splits are reversible.

### 4.3.7 Confidence scoring & human-in-the-loop
- Produce a **match probability/score** per candidate (classifier output or calibrated similarity).
- **Three-band policy:** High (auto-merge) above upper threshold; Low (auto-new) below lower
  threshold; **Gray zone → queue for human confirmation** (one-click confirm/reject), the way
  **dedupe** uses **active learning** and Cognee flags `ontology_valid`. For a single user this is a
  tiny, high-leverage review queue.
- Mem0's audit recommends a **REJECT action + pre-storage quality gate** — fold confidence scoring
  into that gate.
Sources: [dedupe](https://github.com/dedupeio/dedupe), [zingg](https://github.com/zinggAI/zingg)
(probabilistic + deterministic, active learning),
[ER at scale](https://medium.com/@shereshevsky/entity-resolution-at-scale-deduplication-strategies-for-knowledge-graph-construction-7499a60a97c3)
(rule of thumb: <1M records → Dedupe; 1–100M → Zingg/Splink — we are firmly Dedupe-scale, even
simpler).

## 4.4 §4 — techniques worth borrowing (ER-weighted, ranked)

1. **Provenance-tagged write gate — never re-extract retrieved/system content** (mem0 #4573
   feedback-loop fix). Highest ROI; directly fixes the bleed. Add a **REJECT/quality-gate** as a 5th
   update op.
2. **Embedding-ANN blocking (DeepBlocker-style) over the existing vector index** + cheap q-gram /
   normalized-name deterministic blocks.
3. **Incremental linking against your own canonical set** (dedupe Gazetteer pattern): block → score
   → link-or-create, incrementally maintained; reversible **merge/split** via provenance-stamped
   edges.
4. **Three-band confidence with a tiny human-confirm queue for the gray zone** (dedupe active
   learning + Cognee `ontology_valid`).
5. **Coreference front-end (fastcoref/LingMess or Maverick on CPU) + LLM fallback**, resolving
   pronouns to canonical entity IDs **before** triple extraction; bind first-person relations via
   speaker/conversation context.
6. **Canonicalization with alias table + fuzzy-match-to-canonical** (Cognee difflib 80%; CESI
   "multiple weak signals as soft constraints").
7. **Context-based disambiguation against your own graph** (NED): local-context embedding + graph
   coherence + recency prior + attribute checks.
8. **Pairwise matcher**: cheap field-comparator + logistic-regression/embedding-cosine threshold
   (Magellan/dedupe/Fellegi–Sunter); reserve Ditto-style LM classification for genuinely ambiguous
   pairs.
9. **DataPoint-as-Pydantic dual node/edge schema with `index_fields`** + structured-output
   extraction (Instructor/BAML) to a constrained `KnowledgeGraph` schema (Cognee).
10. **Embedded poly-store: graph + vector + relational, every node embedded** (Cognee defaults).
11. **Invalidate-don't-delete temporal edges + UPDATE-same-ID** (Mem0g) over destructive churn.

**Open decisions (from this pass):** matcher choice (cheap classifier vs Ditto LM) per latency
budget; exact merge/auto-new thresholds; formal ontology (Cognee-style) vs lightweight alias table.

---

# §5 — Embedded graph-DB storage (skeptical comparison)

**Constraints recap:** single-user, local-first, **Windows desktop primary**, Python,
`pip`-installable, **no Docker, no server, no JVM, no external runtime**. Needs persistent storage +
Cypher/traversal under our own write pipeline. Native Windows (not WSL) is a hard requirement.

**One-sentence landscape:** the category wanted is "embedded property-graph DB with Cypher + native
Windows wheels"; after Kuzu was archived Oct 2025 that category collapsed to **the Kuzu lineage
(LadybugDB / RyuGraph / Bighorn / Vela fork)**, with **DuckDB+DuckPGQ** the only credible non-Kuzu
embedded option and **CozoDB** a Datalog (non-Cypher) alternative.

## 5.1 Candidate findings

### LadybugDB (Kuzu fork) — VIABLE
- Community fork of Kuzu started 2025, led by **Arun Sharma (adsharma, ex-Facebook/Google)**; aims
  to be a "full one-to-one replacement of Kuzu." ([blog](https://blog.ladybugdb.com/post/ladybug-spreading-its-wings/),
  [register](https://www.theregister.com/2025/10/14/kuzudb_abandoned/))
- **License MIT.** Embedded/in-process, serverless. **Cypher**, **native full-text search + vector
  index** (inherited from Kuzu). ([github](https://github.com/LadybugDB/ladybug),
  [pypi](https://pypi.org/project/ladybug/))
- **PyPI package is `ladybug`** (NOT `ladybugdb`; not the `ladybug-tools` building-energy package).
  Requires Python >=3.10,<3.15.
- **Native Windows wheels CONFIRMED**: e.g. `ladybug-0.16.1-cp314-cp314-win_amd64.whl`; docs state
  install identical on Linux/macOS/Windows, `win_amd64` wheels for Python 3.11–3.14, Windows CLI
  (`lbug.exe`). ([docs](https://docs.ladybugdb.com/installation/))
- Fast-moving: **v0.17.0 (May 28, 2026)** latest; v0.15 added Arrow/DuckDB/Parquet integration.
- **Deciding reason (VIABLE):** only post-Kuzu fork simultaneously embedded, Cypher, MIT, actively
  released, shipping **native Windows wheels**, carrying Kuzu's vector + FTS forward.
- **Longevity caveat:** young (~8 months), informal governance, single-lead bus-factor. RISKY on
  governance, VIABLE on technical fit.

### Upstream Kuzu — RISKY (usable but dead)
- **Archived Oct 10, 2025**; repo read-only. Last release **0.11.3** (bundled algo/fts/json/vector;
  single-file format in 0.11.0). Windows wheels on PyPI (cp37–cp312). Prior artifacts remain usable.
  ([biggo](https://biggo.com/news/202510130126_KuzuDB-embedded-graph-database-archived),
  [register](https://www.theregister.com/2025/10/14/kuzudb_abandoned/),
  [pypi json](https://pypi.org/pypi/kuzu/json))
- **Deciding reason (RISKY):** still installs/works on Windows, but zero maintenance, unpatched
  vulnerabilities, no future fixes. Frozen-baseline only.

### Other Kuzu forks
| Fork | Maintainer | Status | Verdict |
|---|---|---|---|
| **RyuGraph** (`predictable-labs/ryugraph`) | Predictable Labs | MIT; latest **v25.9.2 (Dec 6, 2025)**; Cypher + FTS + vector | **VIABLE (backup)** — Windows-wheel availability not confirmed; pilot-check ([github](https://github.com/predictable-labs/ryugraph)) |
| **Bighorn** (`Kineviz/bighorn`) | Kineviz | MIT; **no releases published**; tied to GraphXR | **RISKY** — no wheels; viz-driven scope |
| **Vela-Engineering/kuzu** | Vela Partners | MIT; niche multi-writer fork; authors point general users to Ladybug | **DISQUALIFIED (scope)** — single-user doesn't need multi-writer |

### FalkorDB / FalkorDB-Lite — DISQUALIFIED
- FalkorDBLite = embedded Redis + FalkorDB (GraphBLAS) module, Unix-domain-socket subprocess,
  **Python 3.12+ only**. ([pypi](https://pypi.org/project/falkordblite/),
  [github](https://github.com/FalkorDB/falkordblite))
- **Native Windows NOT supported.** README: "Redislite can be installed on newer releases of
  Windows 10 under the Bash on Ubuntu shell" — **WSL required**; v0.10.0 only added WSL2
  compatibility. macOS needs `libomp` via Homebrew.
- **Deciding reason (DISQUALIFIED):** WSL dependency violates "native Windows, no external runtime".

### DuckDB + DuckPGQ — RISKY (strongest non-Kuzu)
- DuckDB itself: embedded, MIT, rock-solid native Windows wheels, huge longevity. DuckPGQ adds
  **SQL/PGQ (SQL:2023)** via `INSTALL duckpgq FROM community; LOAD duckpgq;`.
  ([duckdb ext](https://duckdb.org/community_extensions/extensions/duckpgq),
  [duckpgq.org](https://duckpgq.org/))
- **Persistence CONFIRMED**: "As of community version v0.1.0 released with DuckDB v1.1.3, property
  graphs are persistent and are synchronised between connections."
  ([property_graph docs](https://duckpgq.org/documentation/property_graph/))
- **But:** a **CWI research project** — docs warn "some features may still be under development";
  framed "research prototype → community extension," not production-grade; effectively
  one-maintainer (Dtenwolde).
- **No Cypher** (SQL/PGQ instead) and **no built-in graph-native vector index** like Kuzu (DuckDB
  has a separate `vss` extension; FTS extension exists).
- **Deciding reason (RISKY):** best-funded host engine + confirmed persistence + Windows, but
  SQL/PGQ not Cypher, and the PGQ extension is experimental/single-maintainer.

### CozoDB — RISKY (no Cypher)
- Embeddable, **MPL-2.0**, **Datalog**, relational+graph+vector, **HNSW vector + FTS** built in.
  `pip install cozo-embedded`, verified **`win_amd64` wheel**. ([github](https://github.com/cozodb/cozo),
  [pypi](https://pypi.org/project/cozo-embedded/))
- **Maintenance stalled:** last release **v0.7.6, Dec 2023** — no PyPI releases 2024–2025; pre-1.0.
- **Deciding reason (RISKY):** fits embedded/Windows/vector/FTS, but **no Cypher** (Datalog) and
  ~2.5 years without a release → abandonment risk.

### CogDB — DISQUALIFIED
- Pure-Python embedded triple store, zero-setup, traversal via its own "Torque" API.
  ([cogdb.io](https://cogdb.io/), [github](https://github.com/arun1729/cog))
- **No Cypher**, in-memory-oriented, "small to medium" only; no PyPI release in 12+ months →
  effectively discontinued.

### ArcadeDB — DISQUALIFIED
- Capable multi-model (SQL, **Cypher/OpenCypher 25**, Gremlin, GraphQL, Mongo, vector); markets a
  "from KuzuDB" migration path. ([arcadedb.com](https://arcadedb.com/),
  [github](https://github.com/ArcadeData/arcadedb))
- **Confirmed JVM requirement:** "ArcadeDB's embedded mode is only possible if your application is
  running in a JVM." ([embedded.html](https://arcadedb.com/embedded.html))
- **Deciding reason (DISQUALIFIED):** JVM is a hard no, even though a `pip` shim
  (`arcadedb-embedded`) exists — it still drags in Java.

### NetworkX / rustworkx — fallback only (not a DB)
- In-memory graph libraries; **no persistence, no Cypher**. NetworkX pure-Python/ubiquitous;
  rustworkx fast Rust-backed drop-in. Both pip-install on Windows.
- **Role:** non-DB fallback for in-process algorithms/prototyping, or a compute layer *on top of*
  the chosen store. Not a storage answer.

## 5.2 Comparison table

| Option | License | Embedded | Native Win wheels | Python pip | Query lang | Persistence | Maint. 2025-26 | Vector / FTS | Longevity risk | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **LadybugDB** | MIT | Yes | **Yes** (cp311-314) | `ladybug` | **Cypher** | Disk (single-file) | **Active** (v0.17, 5/2026) | **Yes / Yes** | Med (young, 1 lead) | **VIABLE** |
| Kuzu (upstream) | MIT | Yes | Yes | `kuzu` | Cypher | Disk | **Archived** (0.11.3) | Yes / Yes | High (dead) | RISKY |
| RyuGraph | MIT | Yes | Unconfirmed | likely | Cypher | Disk | Active (v25.9.2) | Yes / Yes | Med | VIABLE (backup) |
| Bighorn | MIT | Yes | None published | n/a | Cypher | Disk | No releases | Yes / Yes | High | RISKY |
| Vela/kuzu | MIT | Yes | via `kuzu` | yes | Cypher | Disk | Niche-active | Yes / Yes | Med | DISQ (scope) |
| FalkorDB-Lite | (FalkorDB) | Yes (subproc) | **No (WSL)** | `falkordblite` (3.12+) | Cypher | Disk | Active | Yes / — | — | **DISQ** |
| DuckDB+DuckPGQ | MIT | Yes | **Yes** | `duckdb`+ext | **SQL/PGQ** | **Yes (v1.1.3+)** | Active (exp. ext) | via `vss`/`fts` | Med (ext exp.) | RISKY |
| CozoDB | MPL-2.0 | Yes | **Yes** | `cozo-embedded` | **Datalog** | Disk | **Stalled (2023)** | Yes / Yes | High | RISKY |
| CogDB | MIT | Yes (pure-Py) | Yes (pure-Py) | `cogdb` | Torque (no Cypher) | Disk | **Discontinued** | partial | High | DISQ |
| ArcadeDB | Apache-2.0 | Yes (**JVM**) | n/a | shim | Cypher/Gremlin/SQL | Disk | Active | Yes / Yes | Low | **DISQ (JVM)** |
| NetworkX/rustworkx | BSD/Apache | Yes | Yes | yes | none | **None** | Active | no | Low | Fallback only |

## 5.3 Final ranked recommendation — pilot these two

1. **LadybugDB (`pip install ladybug`) — primary pilot.** The only option satisfying *every* hard
   constraint at once: embedded, MIT, **confirmed native Windows `win_amd64` wheels**, Cypher,
   Kuzu's built-in vector index + FTS, active 2026 releases. Most direct Kuzu continuation, so
   Kuzu/Cypher code and LangChain/Graphiti-style integrations port with minimal change. Mitigate
   youth/bus-factor by pinning a version and keeping the storage layer abstracted.
2. **DuckDB + DuckPGQ — secondary / hedge.** Pick if you want a maximally durable host engine and
   can accept **SQL/PGQ instead of Cypher**. Persistence across connections confirmed (v1.1.3+),
   Windows wheels first-class; layer `vss`/`fts` for vector + FTS. Catch: PGQ extension
   experimental/single-maintainer.

Keep **RyuGraph** as a named fallback (verify Windows wheels during the pilot); keep
**rustworkx/NetworkX** for in-process algorithms regardless.

**Open decision:** can we accept **SQL/PGQ** (unlocks the durable DuckDB path) or is **Cypher
mandatory** (locks us to the Kuzu lineage = LadybugDB)?

---

# §6 — Cross-cutting convergence (the trust signal)

Techniques appearing in *every* (or nearly every) system researched. When independently-built
production systems converge, treat these as settled practice rather than open questions.

| Convergent technique | Who does it | Why trusted |
|---|---|---|
| **Single ingestion abstraction** for text/chat/JSON | Graphiti "episodes", Cognee "DataPoints", LightRAG | one pipeline, many sources |
| **LLM structured extraction → typed entities + relations** | all | the proven write-side core |
| **Don't dedup on string match — embedding + LLM adjudication** | Graphiti, GraphRAG/Neo4j, Cognee, Mem0g | naive string-match → "toxic graph"; <85% resolution poisons multi-hop |
| **Incremental merge, never batch re-index** | Graphiti, LightRAG, Cognee | GraphRAG's batch model is the documented anti-pattern |
| **Invalidate-don't-delete temporal facts** | Graphiti (bi-temporal), Mem0g | facts change ("my ex", job moves); keep history |
| **Hybrid retrieval: vector entry → one-hop graph expansion → back to source chunks** | LightRAG, Graphiti, GraphRAG local-search, Cognee | the read-side pattern |
| **Provenance from every fact back to its source** | all | trust/citation + the bleed fix |
| **Cost control via "spend LLM only where needed"** | LazyGraphRAG (defer-to-query), LightRAG (lazy summary), Graphiti (deterministic-first dedup) | makes small/local-model viable |

---

# §7 — Consolidated borrow / avoid + open decisions

## 7.1 BORROW (cross-system, ranked by leverage for our case)
1. **Provenance-tagged write gate** — tag context source role; **never re-extract
   `retrieved_knowledge`/`system`**; add a REJECT/quality-gate. (Fixes the known bleed.) [§4.2.3]
2. **Deterministic-first entity resolution** — exact-name → MinHash/LSH fuzzy → **LLM only for
   ambiguous**, gated by name-entropy; LLM arbitrates identity with context+type. [§1.3]
3. **Single-call typed extraction** — entities + relations + edge-keywords in one structured call;
   atomic-delimiter discipline; overridable entity-type list; gleaning off initially. [§2.1]
4. **Episode-style unified ingestion + append-only bidirectional provenance** (one pipeline for
   docs/chat/JSON; `episodes[]`/`source_id` link facts↔sources). [§1.1, §2.3]
5. **Vector-entry → one-hop graph expansion → back to chunks**, fused with RRF (semantic + BM25),
   `node_distance`/`episode_mentions` rerankers. [§1.5, §2.3]
6. **Incremental in-place merge** (no community rebuild) + **lazy threshold-gated summarization**;
   summed edge weights as a salience prior. [§2.4]
7. **Bi-temporal facts, invalidate-don't-delete** (event-time `valid_at/invalid_at` kept; txn-time
   stored for audit, not queried initially). [§1.4]
8. **ER recipe:** ANN-blocking on the existing vector index → cheap match (LLM for ambiguous) →
   3-band confidence + tiny human-confirm queue → CPU coref before extraction → disambiguate
   against *our* graph. [§4.3]
9. **Content-hash IDs as cross-store join key** (`ent-<md5(name)>`, `rel-<md5(src+tgt)>`). [§2.5]
10. **LazyGraphRAG defer-to-query-time** philosophy with a relevance-test budget knob, *if/when*
    indexing cost becomes a concern. [§3.4]
11. **Prompt-level pollution control** (exclusion lists, uniquely-identifiable test, two-entity
    rule, possessive qualification) + per-source extraction policy. [§1.7]
12. **Pydantic ontology / DataPoint dual node-edge schema** with `index_fields`, kept optional. [§4.1.2]

## 7.2 AVOID (deliberately, for a single-user personal corpus)
1. **Index-time community detection + hierarchical summarization** (Leiden + per-community LLM
   reports). [§3.2]
2. **Global map-reduce search.** [§3.3]
3. **GraphRAG's batch update model** (worst case = full re-index). [§3.5]
4. **Naive string-match entity dedup** (toxic graph). [§3.6]
5. **Aggressive multi-pass gleaning** (cap at 0–1). [§3.1]
6. **Per-entity/per-relationship LLM description summarization** at small scale. [§3.1]
7. **Claim/covariate extraction.** [§3.1]
8. **Premium models for indexing** (10–15× cost). [§3.7]
9. **Adopting a framework that bundles its own LLM/embedder/retrieval/memory** (Graphiti/Cognee
   wholesale) — clashes with our `model_factory`/credentials/ledger and our Qdrant retrieval, and
   risks recreating the Mem0 memory↔knowledge bleed. Use as **reference**, not dependency.
10. **FalkorDB-Lite (WSL) / ArcadeDB (JVM) / Cozo & CogDB (stale, no Cypher)** as storage. [§5]

## 7.3 Open decisions (to resolve when folding into L3)
1. **Storage query language:** Cypher mandatory → **LadybugDB**; or accept **SQL/PGQ** → unlock the
   more durable **DuckDB+DuckPGQ**. [§5.3]
2. **Extraction engine:** LLM structured-output (reuse `model_factory`) vs local NER (GLiNER/spaCy);
   Arabic quality decides. Keep gleaning? (recall vs 2× cost). [§2.1, §2.7]
3. **Entity matcher:** cheap field-comparator/cosine threshold vs Ditto-style LM classifier; exact
   merge/auto-new thresholds. [§4.3.2, §4.3.7]
4. **Ontology:** formal Pydantic ontology (Cognee-style, `edge_type_map`) vs lightweight alias
   table. [§1.2, §4.1.2]
5. **Temporal scope:** event-time only vs full bi-temporal; which predicate types trigger
   contradiction checks. [§1.4]
6. **Coref tooling:** fastcoref/LingMess vs Maverick (both CPU) + LLM fallback; Arabic support to
   verify. [§4.3.4]
7. **Provenance/source-role taxonomy** for the write gate (`user`/`assistant`/`retrieved_knowledge`/
   `system`/per-connector). [§4.2.3]
8. **Cost posture:** eager incremental extraction (LightRAG-style) vs lazy defer-to-query
   (LazyGraphRAG-style) for the personal corpus. [§3.4]

## 7.4 Primary sources (consolidated)
- Graphiti repo `graphiti_core/*`; Zep paper [arXiv 2501.13956](https://arxiv.org/html/2501.13956v1).
- LightRAG repo `HKUDS/LightRAG` `lightrag/*`; [arXiv 2410.05779](https://arxiv.org/abs/2410.05779);
  [DeepWiki](https://deepwiki.com/HKUDS/LightRAG).
- Microsoft GraphRAG [docs](https://microsoft.github.io/graphrag/) +
  [arXiv 2404.16130](https://arxiv.org/abs/2404.16130); LazyGraphRAG
  [MS Research](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/);
  nano-graphrag, [KET-RAG 2502.09304](https://arxiv.org/abs/2502.09304),
  [E2GraphRAG 2505.24226](https://arxiv.org/abs/2505.24226).
- Cognee [docs](https://docs.cognee.ai/) + [DeepWiki](https://deepwiki.com/topoteretes/cognee);
  Mem0 [arXiv 2504.19413](https://arxiv.org/html/2504.19413v1) + [issue #4573](https://github.com/mem0ai/mem0/issues/4573).
- ER surveys [arXiv 1905.06167](https://arxiv.org/abs/1905.06167); Ditto
  [arXiv 2004.00584](https://arxiv.org/pdf/2004.00584); coref
  [fastcoref](https://github.com/shon-otmazgin/fastcoref),
  [Maverick](https://github.com/SapienzaNLP/maverick-coref); CESI
  [arXiv 1902.00172](https://ar5iv.labs.arxiv.org/html/1902.00172); dedupe/zingg.
- Storage: [Ladybug](https://github.com/LadybugDB/ladybug)/[docs](https://docs.ladybugdb.com/installation/),
  [Kuzu archived](https://www.theregister.com/2025/10/14/kuzudb_abandoned/),
  [DuckPGQ](https://duckpgq.org/), [FalkorDB-Lite](https://github.com/FalkorDB/falkordblite),
  [Cozo](https://github.com/cozodb/cozo), [ArcadeDB embedded](https://arcadedb.com/embedded.html).

---

*End of research dossier. Next step (separate turn): fold §6/§7 into
`knowledge-l3-content-routing-design.md` as decisions + a spike plan.*
