# Admin Preferences — Schema-Driven Refactor Design

> **Initial-development mode:** no backward compatibility, no migration, no wrappers.
> This is a **design / discussion** document — nothing here is implemented yet.
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
   input consistency.
5. **Colocate copy with fields** — fold descriptions into backend `Field(description=...)` (see §4),
   or attach to the field spec so hints can't drift from real fields.
6. **Typed path accessors** — one definition of `graph.reranker.min_relevance` with autocomplete and
   compile-time breakage, instead of the same string repeated as type, binding, path-set key, and
   serialization key.

### 🟡 Lower — consistency & polish
7. **Schema-driven inline validation** — show `ge/le` and cross-field errors before save instead of
   round-tripping a 422.
8. **Unify model-picker dispatch** — move "this field is a model of kind X" into schema metadata
   (`json_schema_extra={"model_kind": "chat"}`) so the picker self-configures from the path.

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
everything else gets cheaper once it exists. The rest of this document details `#1`–`#3`.

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

## 7. Net effect

After #1–#3, "add a preference" collapses toward **backend-only** for the data contract:

1. Add the field to the Pydantic model with `Field(default=..., ge=..., le=..., description=...)` and any
   `json_schema_extra` tags.
2. Regenerate TS types (#2).
3. Add the field's `path` to a card (declarative once #4 lands; a bound input wired from schema until then).

Gone: the second default declaration, the hardcoded HTML bounds, the copy entry, and the three path-set
edits. The read path becomes as schema-driven as the write path already is.

> **Open decision for the reviewer:** scope of the first cut — (a) **#1 + #2 only** (expose schema, generate
> types) is a high-value, low-risk slice that immediately ends type/default/bounds drift; (b) add **#3** to
> also kill the fragile path-sets; (c) go further into **#4** (declarative cards) as a separate, larger pass.
> Recommendation: land (a) and (b) together (they share the schema map), defer (c).

## 8. Related

- `AGENTS.md` → "Adding a `preferences.json` field" — the current manual round-trip this design aims to shorten.
- `../hiro-docs/mintdocs/architecture/misc/preferences.mdx` — `preferences.json`, validated writes, the
  schema-driven PATCH (`_set_path`) this design extends to the read side.
