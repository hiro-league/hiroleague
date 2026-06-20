# Drift Prevention

> The presentational conventions hold today by **discipline**. As contributors multiply,
> some of them should hold by **tooling** instead, and a couple of structural decisions need
> ratifying so they stop drifting.

---

## 1. Type-codegen (flagged — needs evaluation)

**Problem.** Backend shapes are hand-mirrored in the api layer:
- `api/preferences.ts` mirrors ~200 lines of `hirocli/domain/preferences.py` (CLAUDE.md documents a 4-step manual sync ritual).
- `api/graph-runs.ts:73` keeps a hand-ordered column array "same order as the server" — silent mis-map if the backend reorders.
- `api/knowledge.ts:489` "shapes mirror serialize.py".

**Idea.** FastAPI already emits OpenAPI; generate at least `WorkspacePreferences` + the
serialize/graph-runs DTOs (`openapi-typescript`/`orval`). Removes the manual ritual and a
class of silent shape-mismatch bugs.

**Decision needed:** adopt the tooling, or keep the manual mirror + a lint check that the
shapes match? (Open in [00-overview.md](00-overview.md) §7.)

## 2. Controller naming convention (needs ratification)

`-controller` / `-store` / `-model` / `-engine` are used interchangeably for the same role.
**Proposed:** `-controller` = page orchestrator; `-store` = genuinely cross-page singleton
(`active-providers`, `workspace`); retire `-model`/`-engine` as a naming. Document in the
guide once ratified.

## 3. Lint / CI guardrails

Most divergences are greppable — encode them as ESLint/Stylelint rules or a CI grep:

- Raw inline-alert blocks (`border-destructive/30 bg-destructive/10 …`) outside `ui/Inline*`.
- Raw input soup (`h-10 rounded-md border border-input …`) instead of `FormField`/`ADMIN_INPUT`.
- Hardcoded status colors (`text-emerald-*`, `bg-amber-*`, raw status hex) → require tokens.
- Page wrappers using `mx-auto`/`max-w-` instead of `AdminPageHeader`.
- Page-local `setTimeout` + toast `$state` instead of `createToastNotifier`.
- Deep-imports of another feature's `shared/` (cross-feature coupling).
- Bespoke `setInterval` outside `createPoller`.

This is the difference between conventions held by discipline vs by tooling.

## 4. Minor API helpers

- 4 hand-rolled empty-skipping `URLSearchParams` builders (`catalog.ts:111`, `knowledge.ts:441`, `logs.ts:135`, `eval.ts:98`) → one `queryString()` in `client.ts`.
- Scattered magic-number timeouts → named tiers (`TIMEOUTS.quickProbe/standard/heavyLLM`).

---

## The guide set (next)

Once these docs are reviewed, break the `svelte-best-practice` skill into a small guide set
in this folder, with the skill as the short **index** pointing to them:

- `01-structure.md` — folders, vertical slices, thin routes/pages, naming (`-controller`/`-store`).
- `02-ui-components.md` — the shared component catalog + styling/tokens; "use these, don't hand-roll."
- `03-state-and-data.md` — controllers, the new behavioral primitives ([behavioral-primitives.md](behavioral-primitives.md), [search-and-filter.md](search-and-filter.md)), API/error/SSE rules ([cross-cutting-resilience.md](cross-cutting-resilience.md)).
- `04-new-feature-checklist.md` — one-screen pre-merge checklist.

The guide set is the *enforced rules* (what every agent follows); these design docs are the
*backlog* (what to build). The lint rules in §3 enforce the greppable subset of the guide.
