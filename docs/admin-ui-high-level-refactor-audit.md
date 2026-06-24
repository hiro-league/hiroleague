# Admin UI — High-Level Refactor Audit

**Status:** Findings / proposal (not yet executed)
**Scope:** `admin_frontend/src` — big, impactful structural refactors only, grouped by impact.
**Companion doc:** [admin-ui-shared-component-promotion.md](./admin-ui-shared-component-promotion.md) (component-level promotions).

> Abiding by the repo's *no-backward-compatibility* rule: refactors below split/move/merge outright — no wrappers or shims kept for old paths.

---

## Summary

The codebase is healthy post-refactor: routes are thin, and tables/headers/dialogs/tab-prefs/polling already run on shared primitives. The remaining wins are **concentrated, not systemic**. Each headline claim below was verified against the code; three earlier-flagged items were **disproven** and are listed under [Verified non-problems](#verified-non-problems) so they aren't chased.

---

## Tier 1 — Decompose the mega-controllers (biggest structural debt)

Four `.svelte.ts` controllers have grown into multi-responsibility god-objects — the largest, riskiest files. Each bundles concerns that should be sibling sub-models the controller merely composes.

| Controller | ~Lines | Bundled concerns that should split out |
| --- | --- | --- |
| `features/graph-runs/state/graph-runs-controller.svelte.ts` | 695 | ledger polling/pagination · retrieval+ingest trace dialog state · **eval-row cross-feature bridge** · run-timeline cache + LangSmith URLs · filter/sort · node-detail selection |
| `features/logs/state/logs-controller.svelte.ts` | 576 | log fetch/tail · scope-message **ordinal computation** (own domain) · filter/sort/select · debounced search · device-pairing metadata |
| `features/chat-channels/state/chat-channels-controller.svelte.ts` | 551 | facade wiring 6 sub-models inline (engine, form, composer, character-resolved, dialogs, ui-prefs) — should delegate, not compose at top level |
| `features/knowledge/state/knowledge-ingest.svelte.ts` | 540 | file-scan UI state · ingest job polling · **L3 graph-build orchestration** (distinct concern) · tag extraction · recent jobs |

**Why it matters:** these files attract bugs and merge conflicts; each extraction is self-contained and testable. Cleanest first cuts: the `graph-runs` eval-bridge and the `knowledge-ingest` graph-build step.

---

## Tier 2 — Kill cross-feature duplication with shared abstractions

| Opportunity | Evidence | Impact |
| --- | --- | --- |
| **Model-picker logic** — extract `providersForPicker` / `modelsForPicker` / `providerConfigured` / `selectedRowInactive` into one `catalog-picker-logic.ts` | `components/ui/ordered-model-picker/OrderedModelPicker.svelte` ↔ `features/preferences/SingleModelPicker.svelte`, ~40% overlap, **no shared module** | High — provider-filtering drift; this is the skill's §3 poster-child dedup case |
| **`createResource` adoption** — only ~7 consumers; metrics/chat-messages/graph-runs/preferences hand-roll the `loading/error/data + load()` skeleton | `state/create-resource.svelte.ts` exists and is the intended pattern | Medium — consistency + free `.loaded`/error paths |
| **Trace-derive shared helpers** — common `StageRef`, label/hint maps, stage-meta + view-table projection | `features/graph-runs/shared/ingest-trace-derive.ts` ↔ `retrieval-trace-derive.ts` | Medium-Low — phase vs lane shapes genuinely differ; extract only the table/meta scaffold |

---

## Tier 3 — Decompose oversized view components

- **`features/eval/answers/EvalRowDetailDialog.svelte`** (~394 lines) — one dialog renders **6 diagnostic tabs** (Judge/Evidence/Facts/Entities/Episodes/Trajectory) plus cross-tab search. Split each tab into its own component; the dialog becomes a thin shell.
- **`features/eval/answers/EvalAnswersPane.svelte`** (~458 lines) — extract the 6-key URL-synced filter orchestration into a micro-controller.
- **`features/knowledge/graph/KnowledgeGraphPanel.svelte`** / **`KnowledgeGraphDetailPanel.svelte`** — pull async chunk/document loading into a `*-loader.svelte.ts`; lift panel-side state into a prefs module.

---

## Tier 4 — Cheap convention sweeps (bundle into one PR)

Small individually, mechanical, worth doing together:

- **~10 bespoke `rounded-lg border bg-card` cards** → `<SectionCard>` / `<SectionCardMuted>`.
- **`notify` prop-drilling** in 4 tabs (`WorkspacesTab`, `GatewaysTab`, `MetricsTab`, `EvalPanel`) → local `createToastNotifier()`.
- **Duplicate `formatBytes`** in `features/knowledge/shared/knowledge-pure.ts:187` → import from `$lib/format/bytes`.
- **~10 raw `h-10 rounded-md border` input** blocks → `FormField` / `ADMIN_INPUT`.

---

## Verified non-problems

Flagged by an initial audit pass but **disproven** by reading the code — do not pursue:

- **"Fragmented polling / hand-rolled `setInterval`"** — false. Zero `setInterval` in feature controllers; `createPoller` is already adopted by 6 features. Polling is unified. (The remaining nuance is two *intentional* live mechanisms: timer `createPoller` and SSE `EventSource` for eval/knowledge.)
- **"Tab-preferences under-migrated (only 4 of 10)"** — false. Nearly every feature uses `createTabPreferences`; remaining custom prefs files own *non-tab* filter/layout state, which is correct.
- **"13 custom dialogs bypass `Dialog.Root` (43%)"** — false. `ConfirmDialog` is the blessed wrapper and is widely used. Only `KnowledgeGraphPanel` has bespoke overlay markup, and it's a fullscreen panel, not a modal.

---

## Suggested sequencing

1. **Tier 1 first** — start with `graph-runs-controller` (extract the eval-bridge + trace-dialog state), then `knowledge-ingest` (split the graph-build step). Highest structural leverage.
2. **Tier 2** — `catalog-picker-logic.ts` (kills the highest-drift duplication), then broaden `createResource`.
3. **Tier 3** — `EvalRowDetailDialog` tab split.
4. **Tier 4** — one mechanical sweep PR.

Each step should keep the app working, run `npm run check` + `npm run test:unit` (admin_frontend), and verify affected pages on the Vite dev site (`http://localhost:5173`).
