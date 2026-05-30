# Design: surface local downloadable models in the Catalog browser

## Problem

Cloud rerankers (Voyage / Cohere) are `catalog.yaml` rows, so they appear in the **Catalog
browser**, **Active Providers** kinds, and the reranker picker. Local in-process rerankers
(FlashRank / FastEmbed / sentence-transformers) live in a **code registry**
(`services/knowledge/reranker_registry.py`) and only appear in the **reranker picker** with
download buttons. So a user browsing the Catalog tab sees the cloud rerankers but **not** the
local ones — an asymmetry. (The local default *embedder* has the same gap: it's a non-catalog
resolver fallback, invisible in the browse.)

## Principle (what we are NOT changing)

`catalog.yaml` stays **cloud / server-provider reference data** — static, versioned, vendor-
credentialed. We do **not** add local in-process models to the YAML, because that would force a
credential-less pseudo-provider (`flashrank`/`fastembed`) into the Active-Providers /
addable-providers / scan-environment surfaces, and would split local-model truth across YAML
(rerankers) and code (the embedder) unless both migrate.

Instead: keep a **code registry as the source of truth for local models**, and **merge** it into
the browse view as **read-only `hosting: local` rows** whose availability axis is *downloaded*
(not *provider-configured*). Management (download / select) stays in
Preferences → Knowledge → Reranker. The Catalog browser is a read-only reference surface.

This reuses machinery the catalog already has:
- `hosting: local` already exists (ollama / lm_studio).
- The browse already overlays **per-workspace availability** (`online`/`offline` from
  `is_configured`) — see `filterModelsByAvailability`. For a local row, "online" simply means
  **downloaded**. The overlay pattern is identical; only the predicate changes.

## Approach (Shape B — separate local source, merged in the browse)

```
Catalog browser  ─┬─ GET /catalog/models        (cloud + server-local, unchanged)
                  └─ GET /catalog/local-models   (in-process registry + per-workspace download status)
                        → merged + rendered as one table; local rows are read-only
```

Rejected alternative (Shape A — merge inside `/catalog/models`): couples the
workspace-agnostic catalog service to per-workspace download state. Keep them separate.

## Data model

A small generalization of the reranker registry into a **local-model** abstraction (the seed of
a future unified local registry):

```python
# domain/local_models.py  (NEW)
@dataclass(frozen=True)
class LocalModelRow:
    id: str                 # e.g. "local:ms-marco-multibert-l-12"
    provider_id: str        # the backend, shown as the "provider": flashrank | fastembed | sentence_transformers
    display_name: str
    model_kind: str         # "rerank" (later: "embedding")
    hosting: str            # always "local"
    size_label: str
    languages: str
    downloaded: bool        # per-workspace overlay (pure cache check)
    source: str             # "local"  (vs catalog rows' "catalog")
```

`list_local_model_rows(workspace_path, model_kind=None)` aggregates the registries and overlays
`downloaded` via `reranker_cache_dir(workspace_path)` + `is_downloaded(...)` — a **pure cache
check, no live service needed**. The transient `downloading` state stays the reranker picker's
concern (it already polls the service), so the browse endpoint is service-free → low coupling.

Phase 1 wraps `reranker_registry.LOCAL_RERANKERS` (kind `rerank`). Phase 2 adds the local
default embedder (kind `embedding`).

## Touched files

### Backend
| File | Change |
|---|---|
| `domain/local_models.py` *(new)* | `LocalModelRow` + `list_local_model_rows(workspace_path, model_kind)` aggregator/adapter over the reranker registry (and later the embedder default). |
| `services/knowledge/reranker_registry.py` | Minor: expose the specs to the aggregator (already public via `list_local_rerankers`). No structural change. |
| `admin_svelte/routes/catalog.py` | New `GET /catalog/local-models?model_kind=` — **workspace-scoped** (`SelectedWorkspaceIdDep`) to resolve the cache dir for `downloaded`. Returns `{ models: LocalModelRow[] }`. |
| *(consider)* generalize `GET /knowledge/rerankers` → fold into `/catalog/local-models` | One endpoint for all local kinds; the reranker picker consumes it filtered to `rerank`. Avoids two parallel local-model endpoints. |

### Frontend
| File | Change |
|---|---|
| `api/catalog.ts` | `LocalModelRow` type (+ `source`/`downloaded` on the browse row union); `listLocalCatalogModels(model_kind?)`. |
| `features/catalog/state/catalog-controller.svelte.ts` | In `loadModels()`, also fetch local rows and **merge** into `models`; tag rows with `source`. |
| `features/catalog/shared/catalog-filter-ui.ts` | Add `isRowAvailable(row, configuredProviderIds)` → `row.source==='local' ? row.downloaded : isCatalogProviderOnline(...)`; route `filterModelsByAvailability` through it so the existing online/offline filter "just works" for local rows. |
| `features/catalog/browse/ModelsTab.svelte` | Render local rows: provider col = backend, pricing `-`, availability dot = downloaded, a small **Local** badge + size; **read-only** with a deep link "Manage in Preferences → Knowledge → Reranker." |
| `features/catalog/shared/catalog-sort.ts` | Local rows sort with backend as the provider label (already param-driven). |
| *(optional)* `features/preferences/sections/KnowledgeSection.svelte` + controller | Switch the reranker picker from `listKnowledgeRerankers` to the unified `listLocalCatalogModels('rerank')` — one local-models source. Download action unchanged. |

## Phasing

1. ✅ **Phase 1 — implemented.** Local rerankers appear in the Catalog browse (read-only) via
   `domain/local_models.py` + `GET /catalog/local-models` + browse merge, with a shared
   `isRowAvailable` predicate so the availability dot/filter/sort treat local rows by *downloaded*.
   No `catalog.yaml` change, no embedder, no management UI in the browse.
   **Deviation from the open decisions:** kept `/knowledge/rerankers` for the reranker *picker*
   (it needs the live `downloading`/`error` status from the service for its poll) and added a
   separate `/catalog/local-models` for the *browse* (pure `downloaded` cache check). The two
   endpoints differ by intent — service-backed transient status vs. workspace cache snapshot —
   so they were not merged.
2. ✅ **Phase 2 — implemented.** The local default FastEmbed embedder now appears in the browse
   as a read-only `hosting: local`, kind `embedding` row (`_embedder_rows` in `local_models.py`).
   Its availability is a **best-effort** FastEmbed cache read (`is_default_embedder_cached` in
   `embedder.py`) — no marker, because the default embedder auto-downloads on first ingest — and
   a per-row `manage_hint` keeps the "not available" tooltip honest (auto-download for the
   embedder vs. explicit download for rerankers). The frontend needed no new fetch path: the
   browse already merges `listLocalCatalogModels(kind)` for any kind.
3. ✅ **Phase 3 — implemented (full integration).** Triggered by review feedback: Phase 1/2 had
   left local models half-integrated (in Models only, with empty columns, no provider, a bespoke
   dropdown, and split download-tracking). Resolved by making local models **first-class**:
   - **Single "local" provider** (`LocalProviderRow`, id `local`, "Local (in-process)") surfaced
     in **Catalog → Providers** and **Active Providers** (`auth_method: local`, non-removable,
     no key). Models no longer reference an invisible provider.
   - **Full model metadata** on local rows — `context_window`, `features` (backend + multilingual
     + onnx/torch), `modalities`, backend shown via `model_class`, and a **Free** pricing
     indicator (`modelPricing` returns "Free" for local/free rows) instead of blank.
   - **Reranker preference → `SingleModelPicker`** (provider→model, like embedding/answering),
     with an **inline Download** affordance when a selected local model isn't downloaded. The
     bespoke `<select>` + separate download list are gone.
   - **Unified download tracking** — one marker mechanism (`download_markers.py`) for *all* local
     models: rerankers (explicit download) and the embedder (marker written on first successful
     load). The fragile FastEmbed cache-scan heuristic is deleted.

   With this, `list_local_model_rows` / `list_local_providers` is the **unified local registry**
   feeding all three surfaces (Models, Providers, picker).

## Open decisions

1. **Read-only vs actionable in browse.** Recommend **read-only** local rows in the catalog
   browser (download/select stays in Preferences) — the browse is a reference surface, and
   duplicating the download UX in two places invites drift. A deep link covers discoverability.
2. **Local `provider_id`.** Show the **backend** (`flashrank` / `fastembed` /
   `sentence_transformers`) as the provider — more informative than a flat `local`.
3. **Endpoint shape.** Recommend **generalizing `/knowledge/rerankers` → `/catalog/local-models`**
   (one local-models source) rather than a second parallel endpoint.
4. **Availability semantics.** Local row "online" = downloaded; "offline" = not downloaded.
   Reuses the existing availability dot/filter unchanged conceptually.

## Non-goals

- No change to `catalog.yaml` or the provider/credential surfaces.
- No download/management actions added to the Catalog browser (stays in Preferences).
- No catalog_version bump (pre-release).

## TL;DR

- **Keep local models in a code registry** (source of truth), **don't** put them in
  `catalog.yaml`. Surface them in the **Catalog browse as read-only `hosting: local` rows** whose
  availability = *downloaded*, via a new `/catalog/local-models` endpoint merged into the browse.
- **~4 backend touch-points** (1 new `domain/local_models.py`, 1 endpoint, minor registry/route)
  and **~4 frontend** (api type+fetch, controller merge, availability predicate, ModelsTab render).
- **Phased:** rerankers first → embedder next → unified local registry only if many kinds accrue.
- **Reuses** the catalog's existing `hosting: local` + per-workspace availability overlay; no
  pseudo-providers, no YAML mutation.
