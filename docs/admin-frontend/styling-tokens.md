# Styling — Semantic Tokens

> The layout/chrome foundation is solid (`app.css` semantic CSS vars + `@theme inline`,
> `admin-tokens.ts` class-string constants adopted in 37 files, centralized gradient
> utilities). The one systematic gap is **semantic status colors** — they bypass the token
> layer entirely.

---

## 1. Semantic status tokens (the main fix)

**Problem.** "ok = green / warn = amber / error = red / info = sky" is an app-wide
convention with **no token**. Re-expressed ~**140×** as raw Tailwind palette classes (each
with a hand-maintained `dark:` pair) **and** as raw hex in graph-runs scoped styles. Same
meaning, several different shades, no source of truth.

Evidence:
- `badge.svelte` is inconsistent with itself — `destructive` uses the `bg-destructive` token; `success`/`warning` use raw `emerald-500`/`amber-500` (`:18–20`).
- The amber warning-banner string `rounded-md border border-amber-500/30 bg-amber-500/10 … text-amber-700 dark:text-amber-300` is byte-identical in `KnowledgePage.svelte:75`, `EvalPage.svelte:95`, + 3 workspace dialogs.
- Raw hex (theme-**blind** → identical in light/dark = a real contrast bug): `ValidityPill.svelte:28` (`#16a34a`/`#dc2626`), `IngestPhaseStages.svelte:467`, `GraphRunsRunDetailHeading.svelte:176` (node swatches).

**Fix.**
```css
/* app.css — per theme, wired into @theme inline so bg-success / text-warning exist */
--success: …; --success-foreground: …;
--warning: …; --info: …;
/* + node-type accent swatches */
```
Then route `badge.svelte`, `ToastHost`, `InlineWarningAlert`, and the graph-runs pills/swatches
through them. One change retires ~140 hardcoded sites **and** closes the dark-mode-contrast
footgun (raw hex stops being theme-blind).

## 2. Class-string constants

- **`ADMIN_FIELD_KICKER`** — the uppercase label `font-sans text-xs font-semibold uppercase text-muted-foreground` recurs 8× (`CharacterViewPanel`, `CharacterResolvedBlock`). Add to `admin-tokens.ts` (distinct from the page-level `ADMIN_HEADER_KICKER`).
- **`<AdminAlert variant>`** (or `ADMIN_ALERT_*` constants) — collapses the duplicated amber banner above. Pairs with the SSE-banner dedup in [cross-cutting-resilience.md](cross-cutting-resilience.md).

## 3. Minor

- **Scoped-style cleanups** — `MemoriesPanel` `.memories-*-cell` rules and `ValidityPill` re-implement plain Tailwind utilities / colors; convert to utilities + the new tokens. (Leave the justified `:global` table/layout blocks in `TraceTable`/`AdminTableShell`.)
- **Stale fallbacks** — drop `, #64748b` in `var(--muted-foreground, #64748b)` calls (~20×); the var is always defined on `:root` and the slate fallback matches neither theme.
- **`1180px` breakpoint** — `AdminMasterDetail.svelte:26` + `MemoriesPanel.svelte:234` use the same arbitrary value for the master/detail split; promote to a named breakpoint if a 3rd use appears.

---

Dark mode itself is correct (`@custom-variant dark` + `:root[data-theme="light"]`); the only
breakage is the hardcoded colors in §1. Fixing §1 closes the theming gap too.
