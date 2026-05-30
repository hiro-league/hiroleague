# Knowledge RAG — Retrieval **Scoping** Design

> Sibling to [`knowledge-service-v1-design.md`](knowledge-service-v1-design.md) (the
> service/data model) and [`rag-optimize.md`](rag-optimize.md) (retrieval **quality**).
> This doc owns a different axis: **scope** — *which slice of the corpus do we search, and
> do we search at all, for this speaker in this conversation.*
>
> **Initial-development mode:** no backward compatibility, no migration, no wrappers.
> This is a **design / discussion** document — nothing here is implemented yet.

## 1. The problem, stated precisely

Everything in the other two docs answers *"given we search the whole corpus, how do we
return the **best** chunks?"* (hybrid, reranker, embedder, query rewrite). That is
**retrieval quality** — *how well* you search.

This doc answers a different question:

> *"Which **slice** of the corpus should we even search — and should we search at all —
> for **this user** talking to **this character** in **this conversation**?"*

That is **retrieval scope** — *what* you search over, and *whether* to.

The two axes are orthogonal. A perfect reranker over the wrong 300 documents still answers
from the wrong neighborhood. Today, chat-side retrieval searches the **entire** knowledge
base on every knowledge-seeking turn (`_knowledge_scope_filters` returns `{}` — see §6),
so the symptom isn't bad ranking, it's an unscoped candidate set.

## 2. The nature of *this* corpus changes everything

This is **not** a library of topic documents. It is a person's life, plus their machine,
turned into searchable data. Two properties dominate the design:

**(a) It is personal and entity-dense.** Examples of what a single user's knowledge holds:

| Kind | Examples |
|---|---|
| People & relationships | "my sister Lina", "Selim (colleague)", "the Henderson family" |
| Places | "the apartment in Paris", "Mom's house", "the gym on 5th" |
| Objects | "my road bike", "the blue Toyota", "Dad's watch" |
| Event timeline | "the 2019 ski trip", "last Tuesday's dentist appointment", "the move" |
| Preferences / traits | likes, dislikes, dietary rules, habits |

**(b) It is multi-modal and effectively unbounded** — drive data converted into usable
text: chat history, **photo-folder descriptions**, **voice-note transcripts**, documents,
notes. "There is no limit." New modalities arrive over time.

Consequence: the scoping dimensions a user actually thinks in are **entity** (who/where/what),
**time** (when), and **modality** (from my photos / my voice notes / my chats) — *not just*
the `category / subcategory / tags` taxonomy v1 ships with. A query like
*"what did I do with Selim in Paris last summer?"* decomposes into
**person=Selim · place=Paris · time≈last summer**, which the current scalar+tag filter can't
express. **This is the single biggest design implication** and drives §9 (metadata).

## 3. Personas vs. purpose-built characters

From the product framing: a character is **not necessarily tied to a skill**. It may be a
**purpose-built assistant** (a "Chef", a "Fitness coach" with a clear knowledge domain), or
it may be a **persona** (a warm friend, a playful companion, a stern mentor) whose identity
is about *tone and relationship*, not a knowledge domain.

This splits the role of character in scoping:

| Character type | Example | What it scopes |
|---|---|---|
| **Purpose-built** | "Chef Marco" | *Narrows* the domain → bind to `category=cooking` (+ the user's food prefs). A real **topical pre-filter**. |
| **Persona** | "Aria, my friend" | Does **not** narrow the domain. Aria should know about your family, your trip, your bike — *the whole personal corpus*. Persona colors **how** it answers, not **what** it may retrieve. |

**Implication:** "bind a character to a category" (the old Layer 2) is the **exception**, not
the rule. For a persona, character binding is empty and the **per-query router (Layer 3)** does
the narrowing. Both must be supported; neither is the universal answer.

## 4. The governing principle (recall is fragile)

`rag-optimize.md`'s thesis: **recall is the bottleneck — if the right chunk never enters the
candidate set, nothing downstream recovers it.** Scoping *shrinks* the candidate set, so it
**directly endangers recall**. If a filter guesses `place=Paris` but the memory was filed
under "France trip," the right chunk is gone before ranking runs.

The rule that governs every decision below:

```
Hard-filter ONLY what you are CERTAIN of   → identity      (from chat context, not a guess)
Soft-bias / fall back on what you INFER    → topic/entity/time (from the query, can be wrong)
```

Two sources of scope, treated oppositely:

| Source | Comes from | Certainty | Filter type | Decided by |
|---|---|---|---|---|
| **Identity scope** — *who is talking* | chat context (`character_id`, channel's `user_id`) | certain | **hard** Qdrant filter | server, deterministic |
| **Content scope** — *what they ask about* (topic/entity/time/modality) | the query + conversation | inferred | **soft** bias + automatic unfiltered fallback | semantic router / LLM |

Letting the LLM control identity scope is a **security hole** (a character could talk its way
into another user's private data) *and* a recall risk. Hard-filtering on an inferred entity is
a **silent recall loss**. Keep them separate.

## 5. The funnel

```
                      All docs (one user's whole life + system + characters)
                                    │
  L0  Should we retrieve?           │   ✅ DONE — knowledge_needed (rewrite_query) skips small talk
                                    ▼
                  ┌───────────────────────────────┐
  L1  IDENTITY scope (HARD)          │ system + this character + this │  ⬅ SEAM EXISTS, returns {}
      who is talking                 │ channel's user (per policy)     │     _knowledge_scope_filters
                  └───────────────────────────────┘     (base.py:721)
                                    │
  L2  CHARACTER profile (optional)   │ purpose-built → topical narrow │  ⬅ NEW; empty for personas
                                    │ persona       → no narrowing    │
                                    ▼
  L3  CONTENT routing (SOFT)         │ topic · entity · time · modality│  ⬅ NEW; the workhorse for personas
      what they ask about           │ + automatic unfiltered fallback │
                                    ▼
  L4  Hybrid + rerank + min_score                                        ⬅ QUALITY (the other two docs)
                                    ▼
  L5  Abstain if nothing relevant                                        ⬅ partly there (min_score; rerank relevance)
                                    ▼
                          Final context (or nothing)
```

## 6. Layer by layer, with examples

### L0 — Should we retrieve at all? *(already built)*
Admin **Ask** = every submit is a deliberate question → always retrieve. **General chat** =
most turns aren't knowledge-seeking. Already solved: `rewrite_query` emits `knowledge_needed`
and `_route_after_rewrite` skips embed/search on small talk.

- *"hey, how's it going?"* → `knowledge_needed=false` → no retrieval. ✅
- *"what's my sister's birthday again?"* → `knowledge_needed=true` → continue. ✅

### L1 — Identity / ownership scope *(HARD — the direct answer; seam is stubbed)*
The turn already carries identity into the subgraph (`character_id`, `user_id` —
[`base.py:689`](../hiroserver/hirocli/src/hirocli/runtime/agent_graph/base.py)). The scope
filter is built **server-side from that context, never from the LLM**. Today
[`_knowledge_scope_filters`](../hiroserver/hirocli/src/hirocli/runtime/agent_graph/base.py:721)
returns `{}` — *every owner visible* — with a comment that tightening is "a later step." That
"later step" **is** deferred open question #1 from the v1 design doc.

Technique: textbook **access-control / multi-tenant filtering** — a hard `owner` filter ANDed
into the Qdrant query. All the plumbing exists (`owner_kind`/`owner_id` payload + indexes,
`build_qdrant_filter`).

**Example.** User *Maya* (user_id=`42`) chats with character *Aria* (`aria`). The hard filter
becomes: `owner_kind=system` **OR** (`owner_kind=character` AND `owner_id=aria`) **OR**
(`owner_kind=user` AND `owner_id=42`). Maya can never retrieve user *Omar*'s docs, no matter
how she phrases it — that branch is never in the filter.

The only open question is the **policy** — which owners a character-in-channel may see:

| Policy | Sees | Use when |
|---|---|---|
| Narrow | `system` + this character | character must not touch personal data |
| **Channel-scoped** *(suggested default)* | `system` + this character + **this channel's user** | natural for 1:1 personal assistants |
| Configurable | per-character / per-channel toggle | mixed deployments; more UI |

### L2 — Character knowledge profile *(optional; persona vs purpose-built)*
A **purpose-built** character declares a knowledge profile (default categories/tags/owner
scope). A **persona** declares none → full personal corpus.

- **"Chef Marco"** (purpose-built) → profile `{categories:[cooking], include_user_prefs:true}`.
  General chat with Marco is auto-scoped to recipes + Maya's dietary likes/dislikes. *"what can
  I make tonight?"* never pulls in her ski-trip photos. Deterministic, **zero recall risk**.
- **"Aria"** (persona) → empty profile. *"remind me where we stayed in Paris"* must reach
  Maya's travel memories. Aria narrows nothing at L2; L3 does the work.

This reuses the **taxonomy** and the **character config** you already have. For purpose-built
characters it's the highest-leverage, lowest-risk lever; for personas it's intentionally inert.

### L3 — Content routing *(SOFT — the workhorse for personas)*
For a persona over an unbounded personal corpus, narrow by **what the query is about**, across
four dimensions — **but always soft, with an automatic unfiltered fallback** (a wrong hard
filter here is the recall footgun §4 warns about):

| Dimension | Example query | Resolves to | Backing field |
|---|---|---|---|
| **Topic** | "what's my workout split?" | category≈fitness | `category_id` / `tags` |
| **Entity** | "what does **Selim** like?" | person=Selim | *needs entity metadata* (§9) |
| **Time** | "what did I do **last summer**?" | content_date ∈ Jun–Aug | *needs content-date metadata* (§9) |
| **Modality** | "what did I say in my **voice notes** about the apartment?" | source_type=voice_note + topic | `source_type` (exists) |

**Techniques** (increasing cost):

| Technique | How | Cost | Fit |
|---|---|---|---|
| **Semantic routing** | embed each category/entity's name+description (or centroid); pick top-N by cosine; *bias*, don't hard-filter | cheap, **no extra LLM**, Arabic-safe | strong first choice |
| **LLM self-query** | **extend the existing `rewrite_query` structured output** to also emit `categories[] / entities[] / time_range / modality`, validated against the real taxonomy | one LLM call you *already make* when rewrite is on | natural reuse; node + token accounting + fallback already exist |
| **Hierarchical (doc→chunk)** | embed per-doc summaries; retrieve relevant *documents* first, then chunks within | new summary index | best precision on large corpora; defer |

**Soft + fallback, concretely.** For *"where did we go with the Hendersons?"* the router emits
`entity=Henderson`. Run the scoped pass; **if it returns < N hits over `min_score`, re-run
unfiltered** (entity becomes a *boost*, not a gate). The right memory surfaces even if it was
tagged "summer 2018" and never literally said "Henderson."

> L3 should land **after** the embedder upgrade in `rag-optimize.md` — a weak Arabic embedder
> loses recall *within* the scope, and routing can't fix what retrieval never surfaced.

### L4 — Quality
The entire `rag-optimize.md` agenda (embedder upgrade, hybrid ✅, structural context ✅,
reranker). Out of scope for this doc except as the stage scoping feeds.

### L5 — Abstain
Returning **nothing** when nothing is relevant matters *more* in chat than in Ask: injecting
marginal chunks into a casual conversation is worse than injecting none. Reuse the reranker's
normalized `relevance` (already designed) as the abstain gate; `compose_context` already renders
an empty knowledge block cleanly.

- *"what's the capital of France?"* with a personal-only corpus → retrieval finds nothing
  relevant → **abstain**, let the base model answer. Don't force in a Paris *vacation* chunk.

## 7. The metadata dependency — *you can only filter on what you indexed*

This is the strategic crux for a personal corpus. **Entity / time / modality scoping (L3) is
capped by the metadata extracted at ingest.** Today a chunk's queryable scope fields are:
`owner_*`, `category_id`, `subcategory_id`, `tags`, `source_type`, `document_id`, `ord`,
`heading_path`, `ingested_at`.

For the queries in §2 you need richer, *structured* metadata that today's pipeline does not
produce:

| Want to scope by | Needed field (new) | Where it comes from |
|---|---|---|
| people / places / objects | `entities: [{type, name}]` (indexed) | **entity extraction at ingest** (NER / LLM tagging) |
| event timeline | `content_date` / `date_range` (distinct from `ingested_at`!) | **date extraction from content**, not file mtime |
| modality | `source_type` already exists | loader sets it (chat / photo_desc / voice_note / doc) |

Two honest implications:

1. **`ingested_at` ≠ event date.** "Last summer" means *when the event happened*, not when the
   file was imported. A real timeline needs a **content date** parsed from the data.
2. **Entity scoping needs an entity layer.** `tags` can carry a few entities by hand, but an
   unbounded auto-ingested corpus (photo descriptions, transcripts) needs **automatic entity
   extraction at ingest** to be filterable. This is an ingest-side investment that *unlocks* the
   query-side routing — design them together.

This dovetails with Mem0 (which already extracts facts/entities for memory). Worth deciding
whether knowledge reuses or mirrors that extraction rather than building a third path —
see the AGENTS `common-utility` rule (`hiro-commons`).

## 8. Architectural model — node vs. tool

Today knowledge is an **always-on subgraph node** gated by `knowledge_needed`. A future model
is **knowledge-as-a-tool** the LLM calls.

| Model | Scope handling | Notes |
|---|---|---|
| **Node** (current) | identity scope injected **server-side**; LLM never sees the filter | ✅ clean security boundary, already wired |
| **Tool** (future) | LLM may pass **soft content args** (topic/entity/time) | identity scope **still** server-injected, never a tool arg; costs an agent loop + model reliability |

Scoping does not require switching models — L1/L2/L3 all work in the node you already have.

## 9. Worked end-to-end examples

**A. Persona, personal recall.** Maya → Aria: *"what did I get my sister for her birthday last
year?"*
`L0` knowledge_needed=true → `L1` scope = system + aria + user:42 (Omar's data excluded) →
`L2` Aria persona, no narrowing → `L3` router emits `entity=sister, time≈last year`; scoped
pass over Maya's data; fallback to unfiltered if thin → `L4` hybrid+rerank → `L5` answer with
citation, or abstain if truly absent.

**B. Purpose-built, domain.** Maya → Chef Marco: *"something quick with what I have?"*
`L1` scope = system + marco + user:42 → `L2` Marco profile narrows to `category=cooking` +
Maya's food prefs → `L3` light topic bias → answer. Her vacation photos are never candidates.

**C. Modality + time.** Maya → Aria: *"summarize my voice notes from last week about the
apartment."* `L3` emits `modality=voice_note (hard — explicit), time≈last week (soft),
topic=apartment (soft)`. `source_type=voice_note` is a safe hard filter *because the user said
so*; time/topic stay soft with fallback.

> Note example C: a content dimension can be hard-filtered **when the user states it
> explicitly** ("my voice notes"). The hard/soft split is about *certainty*, and an explicit
> user constraint is certain.

## 10. Recommended phasing

1. **L1 identity scope** — fill the stub; decide the ownership policy. Hard, deterministic, the
   real correctness/security fix; plumbing already exists. **Do first.**
2. **L2 character profile** — optional per character; big win for purpose-built assistants, inert
   for personas. Reuses taxonomy + character config. Low risk.
3. **Embedder upgrade** (from `rag-optimize.md`) — recall foundation; scoping can't recover what
   retrieval never surfaced (esp. Arabic).
4. **§7 metadata enrichment** (entities + content_date + modality at ingest) — the unlock for
   real personal scoping. Pairs with / reuses Mem0 extraction.
5. **L3 content routing** — semantic routing first (cheap, no LLM), or extend `rewrite_query`;
   **soft with fallback**; respects explicit hard constraints (modality).
6. **L5 abstain gate** — with the reranker's normalized relevance.

Deterministic/safe first (1–2), recall foundation next (3–4), inferred/recall-risky last (5).

## 11. Open decisions

1. **Ownership policy** (§6 L1): narrow / channel-scoped / configurable? *(= deferred open
   question #1)*
2. **Per-character knowledge profiles** (§6 L2): in the product? what does a profile contain
   (categories, tags, owner scope, prefs)?
3. **Metadata investment** (§7): do we add an **entity layer** and a **content-date** field, and
   do we **reuse Mem0's extraction** or run a knowledge-side extractor?
4. **L3 routing flavor**: semantic router (no LLM) vs. extend `rewrite_query` self-query vs.
   hierarchical doc→chunk.
5. **Node vs. tool** (§8) long-term.

## 12. TL;DR

- **Scope ≠ quality.** The other two docs make search *good*; this doc decides *what* you search
  and *whether* to. Today chat searches the whole corpus (`_knowledge_scope_filters → {}`).
- **The corpus is personal, multi-modal, unbounded** — family, places, objects, event timelines,
  prefs, plus drive data (chats, photo descriptions, voice transcripts). So scope dimensions are
  **entity · time · modality**, not just category/tag.
- **Characters are personas, not necessarily skills.** Purpose-built → narrow by domain (L2).
  Persona → narrows nothing; the **per-query router (L3)** does the work.
- **Two scope sources, opposite handling:** **identity** (who's talking — certain → **hard**
  server-side filter, security boundary) vs. **content** (what they ask — inferred → **soft** +
  automatic unfiltered fallback). Exception: an *explicit* user constraint ("my voice notes")
  may be hard.
- **The seam is already there, stubbed** ([`base.py:721`](../hiroserver/hirocli/src/hirocli/runtime/agent_graph/base.py)), and L0 gating is done.
- **Metadata is the unlock** (§7): you can only filter on what you indexed. Real entity/time
  scoping needs **entity extraction + a content-date field at ingest** (distinct from
  `ingested_at`); consider reusing Mem0's extraction.
- **Order:** L1 identity → L2 profiles → embedder upgrade → metadata enrichment → L3 routing →
  L5 abstain. Safe/deterministic first; inferred/recall-risky last.
- **No code yet** — decisions in §11 first, then "lets implement."
