# Admin Preferences — Schema-Driven Refactor Design

> **Initial-development mode:** no backward compatibility, no migration, no wrappers.
>
> **Status:** the **high-impact** items `#1`–`#3` (§4–§6) are **implemented and green**. The
> **medium** items `#4`–`#6` (§7–§9) are **not yet built** and are written as step-by-step
> implementation guidance. The **lower** items `#7`–`#8` (§10–§11) are now also written as
> step-by-step guidance — note `#8`'s **backend metadata half is already shipped** (`model_kind`
> is emitted in the field map today), so it is a frontend-only consolidation.
>
> Scope: the **Preferences** admin feature only (`admin_frontend/src/lib/features/preferences/**`,
> `admin_frontend/src/lib/api/preferences.ts`, and the backend model
> `hiroserver/hirocli/src/hirocli/domain/preferences.py`). It does not cover other admin pages.

## 1. The problem, stated precisely

A single preference field — say `graph.reranker.min_relevance` — is one fact: a name, a type,
a default, bounds, nullability, an enum domain, and a human description. Today that one fact is
re-declared in **five places**, with **no contract** keeping them in sync:

| Layer | File | What it declares |
|---|---|---|
| Backend model | `domain/preferences.py` | type, default, bounds (`Field(ge, le)`), nullability, `Literal` enums, description (docstring) |
| Frontend type | `api/preferences.ts` | the type, re-typed by hand |
| Frontend default | `api/preferences.ts` | the default, re-typed by hand (and **wins** over backend on load) |
| UI control | `features/preferences/sections/**/*.svelte` | the binding path, `min`/`max`/`step`, enum `<option>`s |
| Save rules | `features/preferences/state/preferences-edits.ts` | the path as a magic string in `SKIP_PATHS` / `WHOLE_OBJECT_PATHS` / `NULLABLE_*_PATHS` |

The **write** path is already schema-driven: the PATCH endpoint walks the Pydantic model
(`preferences_runtime._set_path`), so a new field is a valid write target automatically. The
**read / UI** side is not — it is hand-mirrored. The asymmetry is the root cause of every
duplication and drift problem below.

### Symptoms this produces

- **Silent drift.** Change a bound in Python (`chunk_size` max 8000 → 6000) and the UI happily
  accepts 7000 until the save 422s. Defaults declared twice means the frontend const silently
  overrides the backend default on load.
- **Fragile, invisible coupling.** Add a field and forget a `preferences-edits.ts` path-set entry
  → the field looks editable but never persists, or persists in the wrong shape. Nothing fails
  loudly.
- **Copy can reference dead fields.** `preferences-copy.ts` indexes hints by stringly-typed field
  name; nothing guarantees the field still exists.
- **Boilerplate tax.** 16 section cards repeat the same `{#if ctrl.draft}` → `SectionCardMuted` →
  `bind:value + oninput={ctrl.markDirty}` skeleton, with inconsistent input markup.

## 2. Inventory (today)

- **Frontend preferences feature:** ~4,348 LOC across ~40 files (1 page, 16 section cards,
  9 widgets, 7 shared utilities, 3 state files).
- **Frontend API types/defaults:** `api/preferences.ts`, ~443 LOC, hand-written mirror.
- **Backend model:** `domain/preferences.py`, ~2,127 LOC — the real source of truth.

Existing abstractions worth keeping/building on: `PrefModelPicker.svelte`, `SettingToggle.svelte`,
`SectionCardMuted.svelte`, `preferences-model-picker.ts`, the controller's draft/baseline model.

## 3. The high-level ideas, by impact

### 🔴 High — kill the multi-layer duplication
1. **Export Pydantic field metadata via a `/preferences/schema` endpoint**, and drive the frontend
   bounds / defaults / enums / hints from it. *(detailed in §4)*
2. **Generate the TS types** from that schema instead of hand-writing `api/preferences.ts`.
   *(detailed in §5)*
3. **Derive the `preferences-edits.ts` path-sets from schema** instead of magic strings.
   *(detailed in §6)*

### 🟠 Medium — collapse the card boilerplate
4. **Declarative field specs + typed primitives.** A card becomes a list of `path`s; primitives
   wire `bind` + `markDirty` + bounds + hint from schema. Removes per-field repetition and forces
   input consistency. *(detailed in §7)*
5. **Colocate copy with fields** — fold descriptions into backend `Field(description=...)` (see §4),
   or attach to the field spec so hints can't drift from real fields. *(detailed in §8)*
6. **Typed path accessors** — one definition of `graph.reranker.min_relevance` with autocomplete and
   compile-time breakage, instead of the same string repeated as type, binding, path-set key, and
   serialization key. *(detailed in §9)*

### 🟡 Lower — consistency & polish
7. **Schema-driven inline validation** — show `ge/le` and cross-field errors before save instead of
   round-tripping a 422. *(detailed in §10)*
8. **Unify model-picker dispatch** — move "this field is a model of kind X" into schema metadata
   (`json_schema_extra={"model_kind": "chat"}`) so the picker self-configures from the path. The
   backend metadata is already shipped; this is now a frontend-only cleanup. *(detailed in §11)*

### Sequencing

```
#1 schema endpoint ─┬─► #2 generated types
                    ├─► #3 schema-derived path rules   (deletes the fragile sets)
                    └─► #4 declarative fields ─► #5 colocated copy
                                                 #7 inline validation
                                                 #8 model-kind from schema
#6 typed paths can land independently as a safety net
```

`#1` is the keystone: it aligns the read path with the already-schema-driven write path, and almost
everything else gets cheaper once it exists. This document details `#1`–`#3` (§4–§6, **shipped**),
`#4`–`#6` (§7–§9), and `#7`–`#8` (§10–§11) — the last two groups **written for a step-by-step
implementer**.

> **Status (2026-06-24):** `#1`–`#3` have **landed**. The schema endpoint, codegen, and schema-driven
> save policy are in the tree and green. The medium sections below build *on top of* that shipped
> plumbing — they assume the schema map and its helpers already exist. Key shipped artifacts the
> medium work depends on:
> - Backend: `GET /preferences/schema` → `{ preferences_version, fields }` (flat `path → meta`);
>   built by `hirocli/domain/preferences_schema.py`.
> - Frontend committed mirror: `src/lib/api/generated/preferences-field-schema.json`, surfaced as
>   `PREFERENCES_FIELD_SCHEMA` (`src/lib/api/preferences-field-schema.ts`).
> - Helpers: `preferenceFieldMeta(schema, path)`, `preferenceNumberBounds(meta) → {min,max,step}`,
>   `preferenceHint(meta) → description` (`features/preferences/shared/preferences-schema.ts`).
> - Controller exposes the **live** map as `ctrl.fieldSchema` (falls back to the committed mirror).
> - **Reference card already migrated:** `sections/knowledge/KnowledgeEmbeddingChunkingCard.svelte`
>   reads bounds + hints from schema instead of hardcoding them. Copy that pattern.

---

## 4. Detail — #1: Export field metadata via `/preferences/schema`

### 4.1 Goal

One backend-owned source of truth for everything the UI needs to *render and validate* a field:
type, default, bounds, nullability, enum domain, description, and a few UI-specific hints. The
frontend stops hand-copying bounds into HTML and descriptions into `preferences-copy.ts`.

### 4.2 Where the metadata comes from

Pydantic already produces most of it via `model_json_schema()`. We enrich the gaps with `Field`
arguments that are otherwise lost (descriptions currently live in docstrings; UI hints don't exist
yet):

| UI need | Source today | Source after |
|---|---|---|
| type | hand-typed in TS | JSON Schema `type` / `anyOf` |
| default | `Field(default=...)` **and** TS const | JSON Schema `default` (single source) |
| bounds | `Field(ge, le)` **and** HTML `min/max` | JSON Schema `minimum` / `maximum` |
| step | only in HTML | `json_schema_extra={"step": 0.05}` |
| enum domain | `Literal[...]` **and** `<option>`s | JSON Schema `enum` |
| nullable | `X | None` **and** path-sets **and** TS union | `anyOf: [..., {type: null}]` |
| description | docstring **and** `preferences-copy.ts` | `Field(description=...)` |
| read-only/computed (`*_resolved`) | implicit + `SKIP_PATHS` | `json_schema_extra={"readOnly": true}` |
| whole-object write shape | `WHOLE_OBJECT_PATHS` | `json_schema_extra={"writeWhole": true}` |
| model kind (for picker) | `preferences-model-picker.ts` switch | `json_schema_extra={"model_kind": "chat"}` |

**Required backend change of habit:** move human descriptions out of docstrings into
`Field(description=...)`, and tag the handful of special fields with `json_schema_extra`. This is the
bulk of the work and is mechanical.

### 4.3 The endpoint

`GET /preferences/schema` → returns `Preferences.model_json_schema()` (with `$defs` resolved/flattened
as convenient for the client). Static for a given server build, so it can be fetched once at page load
and cached. Optionally bump an ETag/version off the model so the client can cache across reloads.

Note: this is a **read of the schema**, separate from `GET /preferences` (the current *values*). The UI
joins the two: schema gives shape/bounds/hints, values fill the draft.

### 4.4 What the frontend does with it

- **Bounds & step** → fed into number inputs instead of hardcoded `min`/`max`/`step`.
- **Enum domain** → `<select>` options generated from `enum` (label mapping can live in a small
  frontend lookup keyed by enum value, or in `json_schema_extra` if we want labels backend-side).
- **Defaults** → seed any missing draft leaf from schema `default`, removing the frontend `DEFAULT_*`
  object as a second source of truth.
- **Descriptions** → replace most of `preferences-copy.ts` hints.
- **`readOnly` / `writeWhole` / `model_kind`** → consumed by #3 (path rules) and #8 (picker).

### 4.5 Tradeoffs / decisions to make

- **Runtime endpoint vs build-time emit.** A runtime endpoint guarantees the schema matches the
  *running* server (good in a single-binary deploy). Build-time emit (write schema to a JSON file in
  CI) makes types generatable offline (#5) but can drift from a hot-patched server. **Recommendation:**
  do both — emit at build time for type-gen, serve at runtime for the live UI; assert they match in a
  test.
- **`$ref`/`$defs` handling.** Pydantic nests reused submodels under `$defs`. The client either resolves
  refs or we flatten server-side. Flattening is simpler for the UI but loses sharing; resolving keeps it
  DRY. **Recommendation:** resolve refs into a flat `path → fieldMeta` map server-side; the UI never sees
  raw JSON Schema.
- **Cross-field validators** (e.g. `chunk_overlap < chunk_size`) are **not** expressible in stock JSON
  Schema. They stay backend-authoritative; #7 handles a small declarative subset for inline UX. Don't try
  to encode arbitrary `@model_validator` logic in the schema.

### 4.6 Done-when

- Endpoint returns a flat `path → {type, default, min, max, step, enum, nullable, readOnly, writeWhole,
  model_kind, description}` map for every field.
- At least one card (pick a bounds-heavy one, e.g. Knowledge embedding/chunking) renders bounds, step,
  and hint entirely from schema with **zero** hardcoded `min`/`max`/copy.

---

## 5. Detail — #2: Generate the TS types from schema

### 5.1 Goal

Delete `api/preferences.ts` as a hand-maintained mirror. The `Preferences` type (and the nested
section types) become **generated artifacts** of the backend model.

### 5.2 Mechanism

- Emit the JSON Schema at build time (see §4.5) to a known path, then run a generator
  (`json-schema-to-typescript` or equivalent) as part of `admin_frontend` codegen.
- Output a `preferences.generated.ts` checked into the repo (so editor/types work without running the
  backend) but regenerated by a script (`npm run gen:prefs-types` or folded into `npm run check`'s
  pre-step).
- The default object is **no longer a TS literal** — defaults come from schema at runtime (§4.4). If a
  static default is still wanted for tests, generate it too rather than hand-writing it.

### 5.3 Tradeoffs / decisions

- **Generated-and-committed vs generated-on-build.** Committing the generated file keeps the dev loop
  fast and makes diffs reviewable (you *see* when the contract changes). **Recommendation:** commit it,
  with a CI check that regeneration produces no diff (fails the build if someone edits the backend model
  without regenerating).
- **Naming/shape fidelity.** `Literal` unions should generate as TS string-literal unions, not `string`.
  Verify the generator preserves them; if not, prefer a generator that does or post-process.
- **Hand-written escape hatch.** A few frontend-only view types (e.g. `model_resolved_source`, options
  lists) are *not* part of the persisted model. Keep those in a separate hand-written file that
  *imports* the generated types — never edit the generated file.

### 5.4 Interaction with #1 and #3

Generated types make #3 type-safe: the path-set derivation (§6) can be checked against the generated
shape so a renamed field breaks compilation rather than silently mismatching a string.

### 5.5 Done-when

- `preferences.generated.ts` is produced from the schema and imported by the controller/cards.
- `api/preferences.ts` no longer hand-declares the persisted `Preferences` shape or its defaults.
- CI fails if the committed generated file is stale.

---

## 6. Detail — #3: Derive `preferences-edits.ts` path-sets from schema

### 6.1 Goal

Eliminate the four hand-maintained magic-string sets — `SKIP_PATHS`, `WHOLE_OBJECT_PATHS`,
`NULLABLE_MODEL_PATHS`, `NULLABLE_STRING_PATHS` — which are the most fragile, least-discoverable part
of the feature. They exist only because the diff/serialize logic has no schema to consult.

### 6.2 Mapping each set to schema metadata

| Today (magic strings) | Derive from |
|---|---|
| `SKIP_PATHS` (read-only/computed, `*_resolved`, `version`) | `json_schema_extra={"readOnly": true}` (and the schema simply not listing computed leaves as writable) |
| `WHOLE_OBJECT_PATHS` (`tuning_profiles`, eval prompt libraries) | `json_schema_extra={"writeWhole": true}` on the object |
| `NULLABLE_MODEL_PATHS` | `anyOf: [..., null]` **and** `model_kind` present |
| `NULLABLE_STRING_PATHS` | `anyOf: [string, null]` (nullable string leaf) → empty-string-coerces-to-null rule |

The serializer's leaf rules (empty string → null for nullable model/string fields) become a function of
`fieldMeta.nullable` + `fieldMeta.type`, not membership in a hand-curated set.

### 6.3 Mechanism

- `editsForSave` / `preferencesAreDirty` take the schema map (built once, §4.4) as input.
- Walking baseline vs draft, each leaf consults `schema[path]` for: skip-if-readOnly, coerce-if-nullable,
  treat-as-whole-object.
- The existing structural diff stays; only the **policy lookups** change from set-membership to schema
  lookup.

### 6.4 Tradeoffs / decisions

- **`writeWhole` granularity.** Some "whole object" cases (tuning profiles, prompt libraries) have bespoke
  write shapes the PATCH endpoint expects. Confirm each maps cleanly to a single `writeWhole` flag, or keep
  a *tiny* explicit override map for the genuine special cases — but driven by schema membership, not blind
  strings. Goal is to shrink the hand-curated surface to near-zero, not necessarily to literally zero.
- **Unknown path = loud failure.** Once paths come from schema, a draft leaf with no `schema[path]` entry is
  a real bug (frontend/backend shape mismatch). Make it throw in dev / surface in tests rather than silently
  skip — the opposite of today's silent drift.
- **Keep the unit tests.** `preferences-edits.test.ts` already pins the diff behavior. Reframe its fixtures
  around schema-derived rules; per AGENTS.md run `npm run test:unit -- preferences-edits` after.

### 6.5 Done-when

- The four `*_PATHS` sets are gone (or reduced to a minimal, documented override map for genuine special
  write shapes).
- Adding a normal nullable field requires **no** change to `preferences-edits.ts`.
- A draft path absent from the schema fails a test instead of silently round-tripping wrong.

---

## 7. Detail — #4: Declarative field specs + typed primitives

> **For the implementer.** This is the biggest mechanical win and the highest-touch change (it edits
> ~15 cards). Do it in **small, shippable steps** (one card per commit) per the Svelte skill §9. The
> goal is to delete the per-field boilerplate — `min`/`max`/`step` in HTML, hand-written hint strings,
> and the repeated `bind:value … oninput={ctrl.markDirty}` plumbing — by moving it into a few shared
> primitive components that read the schema. **`KnowledgeEmbeddingChunkingCard.svelte` is the worked
> example; everything here generalizes it.**

### 7.1 The two altitudes — pick 7a first

There are two levels of ambition. **Implement 7a across all cards first.** 7b is an optional later pass;
do **not** start with it.

| | 7a — schema-fed primitives (recommended) | 7b — fully data-driven cards (later) |
|---|---|---|
| Card still writes | `<PrefNumberField bind:value={ctrl.draft.knowledge.chunking.chunk_size} path="…"/>` | `<PrefField path="…"/>` only |
| `bind:` target | concrete lvalue, passed by the card | none — component reads/writes via a path adapter |
| Risk | low; matches the shipped reference card | higher; needs a get/set path adapter (see 7.5) |
| Removes | HTML bounds, hint strings, repeated markup | also the per-field `bind:` line |

The reason 7a keeps the `bind:` in the card is a hard Svelte constraint (skill §11.4): **`bind:` needs a
concrete writable path.** You cannot `bind:value` through a dotted string prop. So the primitive takes a
`$bindable()` value and the *card* supplies the real `ctrl.draft.…` lvalue. That single line of
duplication is normal and accepted.

### 7.2 Primitives to build

Put these in `features/preferences/widgets/` next to `SettingToggle.svelte` / `PrefModelPicker.svelte`.
Each takes `ctrl` (for `ctrl.fieldSchema` + `ctrl.markDirty`) and a `path`, looks up its `meta` once via
`preferenceFieldMeta`, and renders the existing `FormField` + input. `PrefModelPicker` already follows
this shape — these are its siblings for non-model fields.

1. **`PrefNumberField.svelte`** — replaces every `<FormField><input type="number" min max step …>`.
   - Props: `ctrl`, `path: PreferencePath` (see §9), `label`, `bind:value`, optional `class`.
   - Derives `const meta = preferenceFieldMeta(ctrl.fieldSchema, path)`, then
     `const bounds = preferenceNumberBounds(meta)` and `const hint = preferenceHint(meta)`.
   - Renders `<FormField {label} {hint}><input type="number" min={bounds.min} max={bounds.max}
     step={bounds.step} bind:value oninput={ctrl.markDirty} class={ADMIN_SELECT_LG}/></FormField>`.
2. **`PrefToggleField.svelte`** — thin wrapper over `SettingToggle` that sources `details` from
   `preferenceHint(meta)`. Props: `ctrl`, `path`, `label`, `bind:checked`. (Today every card passes the
   hint as a hand-written `{#snippet details()}` — this kills that.)
3. **`PrefSelectField.svelte`** — replaces enum `<select>`s. Props: `ctrl`, `path`, `label`,
   `bind:value`, and an `options` prop mapping `enum` value → human label (the schema gives the *domain*
   via `meta.enum`; the *labels* stay frontend-side — see 7.4). Renders the `<option>`s from `meta.enum`
   and asserts each rendered value is in `meta.enum` so a backend enum change surfaces.
4. *(optional)* **`PrefTextField.svelte`** for the handful of plain string inputs.

> **Why not bake the binding in too?** Because of §7.1 — `bind:value`/`bind:checked` must cross the
> component boundary as a `$bindable()` prop with a concrete lvalue from the card. Keep that one line in
> the card.

### 7.3 Per-card migration recipe (repeat ~15×)

For each card under `features/preferences/sections/**`:

1. Find each numeric/boolean/enum field and its dotted `path` (it's already in the `bind:` expression).
2. Swap the hand-written `FormField`/`SettingToggle`/`select` block for the matching primitive, keeping
   the **same** `bind:` target.
3. Delete the now-dead `min`/`max`/`step` literals and the imported `*_COPY` hint reference (the hint now
   comes from schema — see §8 for moving the *text* backend-side first).
4. Run `npm run check` and `npm run test:unit -- preferences` after each card. Visually confirm on the
   Vite dev site (`http://localhost:5173`, per AGENTS.md) — bounds, step, and hint should be unchanged.

**Order:** start with the simplest cards (`GraphViewCard`, `KnowledgeRetrievalCard`), finish with the
dense ones (`GraphSearchIndexingCard` ~7 inputs, `GraphRetrievalAgentCard` ~10 inputs, where the payoff
is largest). Leave `TuningProfilesSection` for last — its inputs bind to `draft.tuning_profiles[id].*`
(dynamic keys), which are **not** in the field map (the map keys `tuning_profiles` as one whole-object —
see §6); those inputs keep hardcoded bounds or get a dedicated per-profile primitive. **Do not** pass a
`tuning_profiles.*.temperature` path to `preferenceFieldMeta` expecting a hit.

### 7.4 Enum labels — where they live

The schema carries the enum **domain** (`meta.enum = ["off","graphiti"]`) but not display labels
(`"Off (flat Qdrant)"`). Keep a small frontend `Record<enumValue, label>` per select, colocated with the
card or in a `preferences-enum-labels.ts`. Do **not** push presentation copy into the backend model. The
primitive should still derive the *set* of options from `meta.enum` so an added backend variant can't be
silently missing — only its label needs a frontend entry.

### 7.5 7b adapter (only if/when you do the fully data-driven pass)

To make a card literally `<PrefField path="…"/>` with no `bind:`, the component needs to read and write
the draft by dotted path. Use a get/set adapter against the **`$state`-proxied** `ctrl.draft` (writing
`obj[a][b] = v` on the proxy is reactive):

```ts
// reads are reactive inside $derived; writes mutate the proxy → markDirty
const value = $derived(readPath(ctrl.draft, path));
function commit(v: unknown) { writePath(ctrl.draft, path, v); ctrl.markDirty(); }
```

`readPath`/`writePath` are tiny dotted-path helpers (`path.split('.').reduce(...)`). The input uses
`value={value}` + `oninput`/`onchange` calling `commit` — **not** `bind:`. This is the only way to avoid
the per-field `bind:` line, and it trades the compiler's bind-time lvalue check for runtime path walking,
so lean on §9 typed paths to keep it safe. Ship 7a everywhere before considering this.

### 7.6 Done-when

- A new shared `PrefNumberField` / `PrefToggleField` / `PrefSelectField` exists and is unit-or-visually
  verified against the reference card.
- Every section card sources `min`/`max`/`step` and field hints from schema — **zero** hardcoded numeric
  bounds remain in `sections/**` (except the `tuning_profiles.*` dynamic-key inputs, §7.3).
- `npm run check` green; the Vite dev site renders each migrated card identically to before.

---

## 8. Detail — #5: Colocate copy with fields

> **For the implementer.** Today field help text lives in `features/preferences/shared/preferences-copy.ts`
> as 8 `*_COPY` objects (`GRAPH_EXTRACTION_COPY`, `GRAPH_SEARCH_INDEXING_COPY`, `GRAPH_EVAL_MODELS_COPY`,
> `GRAPH_RERANKER_COPY`, `GRAPH_VIEW_COPY`, `KNOWLEDGE_COPY`, `TUNING_PROFILES_COPY`), imported by 7 cards.
> They are keyed by ad-hoc names (`minRelevance`, `kHop`) with **no guarantee they match a real field** —
> a renamed/removed field leaves orphan copy. This item makes the field's **description the single source**
> and lets `#4`'s primitives pull it via `preferenceHint`, so copy can't drift from fields.

### 8.1 The move: copy → backend `Field(description=...)`

For each entry in `preferences-copy.ts`:

1. Find the matching Pydantic field in `domain/preferences.py`.
2. Move the copy **text** into that field's `Field(description="…")` (some already have a short
   description from `#1` — **replace** it with the richer UI copy; the UI text is the better, fuller
   version — e.g. the multi-sentence `simMinScore` / `searchScope` strings).
3. Regenerate codegen (`npm run gen:prefs-types`) — the text now flows into the field map and out via
   `preferenceHint`.
4. Delete the `*_COPY` entry and its import from the card (after `#4`'s primitive is wired, the card no
   longer references it at all).

### 8.2 Gotchas / decisions

- **Backend descriptions are now UI-facing.** That's intended, but it means description edits are
  product copy, not just dev notes. Keep them user-readable; keep dev-only rationale in `#` comments
  above the field, not in `description`.
- **Multi-paragraph copy.** Several strings are long (e.g. `entityOntology`, `observability`). They
  survive fine as a single description string; don't try to structure them — `preferenceHint` just trims
  and returns the text.
- **Apostrophes / quotes.** The current copy uses contractions (`don't`, `model's`). In Python use plain
  double-quoted strings or escape as needed; the JSON codegen handles escaping. Verify no mojibake after
  regen by spot-checking `preferences-field-schema.json`.
- **Copy that has no field.** `TUNING_PROFILES_COPY.contextWindow` describes `tuning_profiles.*.num_ctx`,
  a dynamic-key leaf **not** in the field map (§7.3). That one stays card-local (or move it onto
  `ModelTuning.num_ctx`'s description and read it from the `ModelTuning` sub-schema if you expose it).
  Don't force it into the flat map.
- **Enum option labels are not hints** (§7.4) — they don't move here; only the field-level help text does.

### 8.3 Done-when

- `preferences-copy.ts` is deleted (or down to the one or two genuinely card-local strings that have no
  persisted field, clearly commented as such).
- Every migrated card's hint comes from `preferenceHint(meta)`; no card imports `*_COPY`.
- `npm run check:prefs-types` confirms the regenerated field map carries the moved descriptions.

---

## 9. Detail — #6: Typed path accessors

> **For the implementer.** After `#1`–`#3`, the diff walker no longer holds magic path strings (it walks
> structurally and looks paths up in the schema). The remaining stringly-typed surface is **card-side**:
> `preferenceFieldMeta(ctrl.fieldSchema, 'knowledge.chunking.chunk_size')` and the `path="…"` props the
> `#4` primitives take. Those are plain `string` today — a typo or a renamed field returns `null` meta at
> runtime instead of failing the build. This item makes every preference path a **checked type**.

### 9.1 Generate a `PreferencePath` union from the field map

The committed `preferences-field-schema.json` keys **are** exactly the valid dotted paths. Emit a
string-literal union from them in the existing codegen step (`scripts/gen-preferences-types.mjs`):

```ts
// generated/preferences-paths.generated.ts  (AUTO-GENERATED — do not edit)
export type PreferencePath = 'version' | 'llm.default_chat' | 'knowledge.chunking.chunk_size' | … ;
```

Generate it from the same JSON the script already writes (`Object.keys(fieldMap)`), so it stays in lock-
step and the `check:prefs-types` staleness gate already covers it.

### 9.2 Thread the type through

- `preferenceFieldMeta(schema, path: PreferencePath)` and `preferencePathMeta(...)` — change the `path`
  param from `string` to `PreferencePath`.
- The `#4` primitives' `path` prop: `path: PreferencePath`.
- `PrefModelIdPath` (already a hand-written union in `shared/preferences-model-picker.ts`) becomes a
  **subset** of `PreferencePath`. Either keep it hand-written (it gates the `applyModelIdToDraft` switch
  exhaustiveness, which is a *different* guarantee) or assert `PrefModelIdPath extends PreferencePath` with
  a type-level check so the two can't diverge.

Now `preferenceFieldMeta(ctrl.fieldSchema, 'knowledge.chunking.chunk_zise')` is a **compile error**, and
renaming a backend field (after regen) breaks every stale card reference at `npm run check`.

### 9.3 What this does *not* solve — be explicit

- **`bind:` lvalues are still hand-written.** Typing the path string does **not** let you derive a
  writable `bind:` target from it (skill §11.4). `#4`'s 7a keeps the concrete `bind:` in the card; `#6`
  only type-checks the *parallel* `path` string. Do not attempt a proxy/getter-setter that returns a
  bindable lvalue from a path — it's a dead end with Svelte `bind:`.
- **Runtime payloads stay strings.** The live `/preferences/schema` map and PATCH payload keys are still
  strings on the wire; `PreferencePath` is a compile-time-only narrowing of the frontend.

### 9.4 Done-when

- `PreferencePath` is generated and committed; the staleness check covers it.
- `preferenceFieldMeta` / primitives / `preferencePathMeta` accept `PreferencePath`, not `string`.
- A deliberately misspelled path in a card fails `npm run check` (add one, confirm the error, remove it).

---

## 10. Detail — #7: Schema-driven inline validation

> **For the implementer.** Today a value the backend will reject (a number past `ge`/`le`, or a
> cross-field combination like `limit_min > limit_max`) is **only** caught when Save fires the PATCH
> and the server returns a **422** — the user loses their place and gets a generic toast. This item
> moves both checks **client-side**, surfaced **at the field** and **before** Save is enabled.
>
> **Crucial:** part of the wiring already exists — do **not** rebuild it. `ctrl.setSectionError(id,
> message)` writes into a `sectionErrors` map; `ctrl.hasSectionErrors` is derived from it; and
> **`canSave` already gates on `!hasSectionErrors`** (controller §`canSave`). The cross-field half is
> already demonstrated end-to-end in `GraphRetrievalAgentCard.svelte` + `retrieval-agent-limits.ts`.
> Your job is to (a) add the **single-field bounds** half driven by schema, and (b) generalize the
> existing cross-field pattern — not to invent a new error channel.

### 10.1 The two validation classes — and why only one comes from schema

| Class | Example | Source of truth | Expressible in JSON Schema? |
|---|---|---|---|
| **Single-field bounds** | `chunk_size` must be `100…6000` | `Field(ge, le)` → `meta.min`/`meta.max` | **Yes** — already in the field map |
| **Cross-field** | `limit_min ≤ limit_default ≤ limit_max` | pydantic `@model_validator` | **No** (per §4.5) — stays hand-mirrored |

Single-field bounds are **derivable** — the schema map already carries `min`/`max`/`step` for every
numeric leaf, and `PrefNumberField` already passes them to the `<input>`. But HTML `min`/`max` on a
number input only constrain the **spinner arrows**; a user can still **type or paste** `9999` and the
input accepts it. That out-of-range value sits in the draft until Save → 422. Closing that gap is the
whole single-field task.

Cross-field rules are **not** in JSON Schema (§4.5 is explicit: do not try to encode arbitrary
`@model_validator` logic). They stay a small hand-written mirror of the pydantic validator, exactly
like `validateRetrievalAgentLimits` mirrors `RetrievalAgentLimits._coherent_limits` today. This item
does **not** auto-derive them — it only standardizes how they report.

### 10.2 Single-field bounds — the schema-driven half (build this)

1. **Add a checker helper** next to the existing bounds/hint helpers in
   `features/preferences/shared/preferences-schema.ts`:

   ```ts
   /** Schema-derived ge/le violation message for a numeric leaf, or null when in range. */
   export function preferenceNumberError(
     meta: PreferenceFieldMeta | null | undefined,
     value: number | undefined | null
   ): string | null {
     if (meta == null || value == null || Number.isNaN(value)) return null; // empty handled by nullable/required
     if (meta.min != null && value < meta.min) return `Must be ≥ ${meta.min}`;
     if (meta.max != null && value > meta.max) return `Must be ≤ ${meta.max}`;
     return null;
   }
   ```

   Keep the message text terse and consistent — these render in the same `text-xs text-destructive`
   slot the cross-field error already uses (`GraphRetrievalAgentCard.svelte` line ~130).

2. **Teach `PrefNumberField` to report.** The primitive (`widgets/PrefNumberField.svelte`) already
   derives `meta` and binds `value`. Add a derived error and (a) render it inline, (b) push it into the
   controller so Save is gated. Reporting must key by the field's `path` so two bad fields don't clobber
   each other:

   ```svelte
   const fieldError = $derived(preferenceNumberError(meta, value));
   // Register/clear this field's blocking error by path; clean up on unmount (collapsed card).
   $effect(() => {
     ctrl.setFieldError(path, fieldError);
     return () => ctrl.setFieldError(path, null);
   });
   ```
   …and under the `<input>`:
   ```svelte
   {#if fieldError}<p class="text-xs text-destructive">{fieldError}</p>{/if}
   ```

3. **Add the per-field error registry to the controller.** `sectionErrors` is keyed by an arbitrary
   *section* id; field errors want to be keyed by *path* and there are many of them. Add a sibling
   `fieldErrors` map rather than overloading `sectionErrors`, and fold it into the existing gate so you
   change `canSave` in **one** place:

   ```ts
   let fieldErrors = $state<Record<string, string | null>>({});
   function setFieldError(path: string, message: string | null) {
     if (fieldErrors[path] === message) return;           // same guard shape as setSectionError
     fieldErrors = { ...fieldErrors, [path]: message };
   }
   const hasBlockingErrors = $derived(
     Object.values(sectionErrors).some((m) => m) || Object.values(fieldErrors).some((m) => m)
   );
   // canSave: swap hasSectionErrors → hasBlockingErrors
   ```
   Expose `setFieldError` on the returned controller object alongside `setSectionError`.

### 10.3 Cross-field — generalize the existing pattern (don't auto-derive)

The Retrieval Agent card is the template. For any other card with a pydantic `@model_validator` worth
mirroring:

1. Write a pure `validateX(slice): string | null` in a card-local `*-limits.ts`, **mirroring the
   pydantic check** (cite the validator name in a comment, as `retrieval-agent-limits.ts` cites
   `_coherent_limits` — so the two are findable together when one changes).
2. In the card, `const err = $derived(validateX(slice))` and
   `$effect(() => ctrl.setSectionError('<sectionId>', err))`.
3. Render `{#if err}<p class="text-xs text-destructive">{err}</p>{/if}`.

Do **not** try to read cross-field rules out of the schema — they aren't there (§4.5). Only mirror the
handful that already have a pydantic `@model_validator`; everything else still relies on the 422 as the
backstop, which is fine.

### 10.4 Gotchas / decisions

- **Empty vs out-of-range.** A blank number input yields `undefined`; that's "unset", not "out of
  range" — `preferenceNumberError` returns `null` for it. Required-ness is the backend's job; don't
  invent a "required" error here.
- **Unmount on collapse.** `SectionCardMuted` is `collapsible`; confirm whether collapsing unmounts the
  inputs. The `$effect` cleanup (`return () => ctrl.setFieldError(path, null)`) makes either behavior
  safe — a collapsed, previously-invalid field must not keep Save disabled forever.
- **The 422 stays the backstop.** Client validation is UX, not security. The PATCH endpoint still
  validates; keep its error handling. Don't remove the toast path in `savePreferences`.
- **Don't gate on HTML `:invalid`.** Relying on the browser's constraint-validation pseudo-class is
  flakier than the explicit derived check and won't cover cross-field — use the controller registry as
  the single source for "can we save".
- **Reuse the destructive style.** Every error line is `class="text-xs text-destructive"` to match the
  shipped cross-field message — don't introduce a new error component.

### 10.5 Done-when

- `preferenceNumberError` exists and is unit-tested (in-range → `null`; below `min` / above `max` →
  message; `undefined`/`NaN` → `null`).
- Typing an out-of-range value in any migrated `PrefNumberField` shows an inline message **and**
  disables Save (no 422 reachable for a pure bounds violation).
- The controller exposes `setFieldError`; `canSave` gates on a single `hasBlockingErrors` covering both
  section and field errors.
- A collapsed card with a previously-invalid field does **not** leave Save stuck disabled.

---

## 11. Detail — #8: Unify model-picker dispatch from schema

> **For the implementer.** A model field (e.g. `graph.extraction_model`) needs to know *which* model
> kind it accepts (`chat`, `embedding`, `rerank`, …) so the picker shows the right catalog. Today that
> kind is **hand-passed at every call site** (`<PrefModelPicker kind="chat" path="graph.extraction_model"/>`),
> even though the same fact lives at `path` in the schema. This item makes the picker read its kind from
> schema so the redundant `kind=` prop disappears and can't drift from the backend.
>
> **Already shipped — do not redo it.** The backend metadata half is in the tree: `model_kind` is in
> `_META_KEYS` (`preferences_schema.py`), emitted into the flat field map, typed on
> `PreferenceFieldMeta` (`api/preferences-schema.ts`), declared via `json_schema_extra={"model_kind":
> "…"}` on the model fields in `preferences.py`, and already consumed by `preferences-edits-policy.ts`
> (`coercePreferenceLeafValue` keys nullable-coercion off `meta.model_kind`). So `#8` is now a **pure
> frontend consolidation** — the schema already tells you the kind at every model path.

### 11.1 What stays, what changes

| Surface | File | Action |
|---|---|---|
| `model_kind` in field map | `preferences_schema.py`, `preferences.py` | **Done** — leave it |
| `kind` derivation | `widgets/PrefModelPicker.svelte` | **Change** — derive from `meta.model_kind`, make the prop optional |
| `kind="…"` at call sites | ~8 cards, ~13 `<PrefModelPicker>` usages | **Delete** the `kind=` line |
| `prefModelCatalog(ctrl, kind)` switch | `shared/preferences-model-picker.ts` | **Keep** — it maps kind → controller catalog stores; legit runtime dispatch, now fed by schema |
| `applyModelIdToDraft` switch + `PrefModelIdPath` | `shared/preferences-model-picker.ts` | **Keep for now** (see 11.3) — it owns the `default_embedding_model_locked` guard + exhaustiveness |

### 11.2 Make the picker self-configure (the core change)

In `PrefModelPicker.svelte`, make `kind` optional and fall back to schema, narrowing the meta's
`string` `model_kind` to `PrefModelKind`:

```svelte
type Props = { ctrl; path: PrefModelIdPath; label; /* … */ kind?: PrefModelKind };
const kind = $derived<PrefModelKind>(
  kindProp ?? (preferenceFieldMeta(ctrl.fieldSchema, path)?.model_kind as PrefModelKind)
);
$effect(() => {
  // Loud in dev: a model path with no model_kind in the schema is a backend tagging bug,
  // not a silent fallback to 'chat'.
  if (!kind) console.error(`PrefModelPicker: no model_kind for path "${path}"`);
});
```

`ctrl.fieldSchema` already falls back to the committed mirror when the live fetch failed (controller
`effectiveFieldSchema`), so `model_kind` is **always** available — no need for a hardcoded default kind.
Then delete every `kind="…"` line from the call sites (`ModelsSection`, `KnowledgeRerankerCard`,
`GraphEvalModelsCard`, `KnowledgeEmbeddingChunkingCard`, `GraphExtractionCard`, `KnowledgeAnsweringCard`,
`GraphRerankerCard`). Do it **one card per commit** (Svelte skill §9) and verify the picker still shows
the right catalog on the Vite dev site (`http://localhost:5173`, per AGENTS.md).

### 11.3 The `applyModelIdToDraft` switch — keep, don't force a path-write adapter

It's tempting to also delete the big switch in `preferences-model-picker.ts` and write the id by dotted
path (`writePath(draft, path, id)`, §7.5). **Resist that for the first pass**, because the switch earns
its keep:

- It hosts the **one genuine special case** — `knowledge.default_embedding_model` is a no-op write when
  `default_embedding_model_locked` (returns `false` so `setModelId` skips `markDirty`). A blind
  path-write would silently mutate a locked field.
- Its `default: never` is an **exhaustiveness guard**: adding a `PrefModelIdPath` without a case is a
  compile error (the comment at the bottom says exactly this), so a new model field can't silently
  no-op on select.

If you later want to shrink it, the safe shape is: generic `writePath` for the common case **plus** an
explicit `if (path === 'knowledge.default_embedding_model' && draft.knowledge.default_embedding_model_locked)
return false;` guard — but that's optional polish, not part of #8's win.

### 11.4 Tie into #6 (typed paths) and add a guard test

- Per §9.2, `PrefModelIdPath` should become a **subset** of the generated `PreferencePath`. Keep
  `PrefModelIdPath` hand-written (it still gates the `applyModelIdToDraft` exhaustiveness — a different
  guarantee), but add a type-level assertion so the two can't diverge:
  ```ts
  const _isSubset: PrefModelIdPath extends PreferencePath ? true : never = true;
  ```
- Add a unit test (extend `preferences-model-picker.test.ts`): **every** `PrefModelIdPath` has a
  `model_kind` in `PREFERENCES_FIELD_SCHEMA`, and that kind is a valid `PrefModelKind`. This is the
  contract that lets the picker drop its `kind` prop safely — if someone adds a model path but forgets
  the backend `json_schema_extra`, the test fails instead of the picker silently rendering an empty
  catalog.

### 11.5 Gotchas / decisions

- **`model_kind` is `string` in the meta type.** Narrow it to `PrefModelKind` at the boundary (the
  `as PrefModelKind` cast + the test in 11.4 is the safety net). Don't widen `PrefModelKind`.
- **Keep `prefModelCatalog`'s `default: never`.** It's a second exhaustiveness guard over the kinds; a
  new kind without a catalog store should fail to compile.
- **No backend change needed.** Per the no-backward-compatibility rule, there's nothing to migrate — the
  metadata is already emitted. This item only removes frontend duplication.

### 11.6 Done-when

- `PrefModelPicker` derives `kind` from `meta.model_kind`; the `kind` prop is optional (or removed).
- **Zero** `kind="…"` props remain on `<PrefModelPicker>` in `sections/**`.
- A test asserts every `PrefModelIdPath` carries a valid `model_kind` in the committed field schema, and
  `PrefModelIdPath ⊆ PreferencePath`.
- `npm run check` green; each model picker on the Vite dev site still lists the correct catalog.

---

## 12. Net effect

After #1–#3, "add a preference" collapses toward **backend-only** for the data contract:

1. Add the field to the Pydantic model with `Field(default=..., ge=..., le=..., description=...)` and any
   `json_schema_extra` tags.
2. Regenerate TS types (#2).
3. Add the field's `path` to a card — `<PrefNumberField path="…" bind:value={…}/>` once #4's primitives
   land (§7); a hand-wired-from-schema input until then.

Gone: the second default declaration, the hardcoded HTML bounds, the copy entry, and the three path-set
edits. The read path becomes as schema-driven as the write path already is.

> **Recommended cut order for the medium work:** **#6 first** (§9 — generate `PreferencePath`; tiny,
> independent, and it makes #4/#5 type-safe), then **#5** (§8 — move copy to backend descriptions, one
> `*_COPY` object at a time), then **#4** (§7 — migrate cards one per commit, simplest first). #4 and #5
> interleave naturally: migrating a card to a primitive (#4) is the moment its `*_COPY` import disappears
> (#5).
>
> **Lower work (#7–#8) comes after #4**, because both build on the migrated primitives: #7 (§10) adds the
> inline-error render + `setFieldError` push *inside* `PrefNumberField`, and #8 (§11) removes the `kind=`
> prop *as each card's* `<PrefModelPicker>` is touched. Neither blocks the others — #8 is small and can
> land any time since its backend metadata already exists.

## 13. Related

- `AGENTS.md` → "Adding a `preferences.json` field" — the current manual round-trip this design aims to shorten.
- `../hiro-docs/mintdocs/architecture/misc/preferences.mdx` — `preferences.json`, validated writes, the
  schema-driven PATCH (`_set_path`) this design extends to the read side.
