# Svelte (admin frontend) — component and styling best practices

This document captures conventions for large Svelte 5 feature pages in `admin_frontend`, especially when a `.svelte` file grows past a few hundred lines. It is derived from refactoring guidance for feature pages such as Characters.

We are in **initial development mode**: no backward compatibility or migration shims are required unless explicitly stated for a change.

---

## 1. Keep feature pages thin

**Prefer a “composition root” over a monolith.** The route or top-level `*Page.svelte` should mostly:

- Wire navigation, URL-driven preferences, and high-level layout.
- Import child sections and pass props (or call small controller modules).
- Avoid owning hundreds of lines of domain UI, duplicated interactions, and global CSS.

If a single `<script>` block mixes unrelated lifecycles (e.g. browse list, edit form, photo crop, navigation guards), **split by concern** so each piece can be tested and changed independently.

For **document / interval / teardown** boilerplate, a small **`*.ts` helper** that returns an **`onMount` cleanup** (e.g. `setupFeatureRuntime(...)`) keeps the shell readable. **`$effect`** blocks that tie many shell locals together (e.g. **`bind:`**, one-off UI flags) often **stay on the page** unless you deliberately move them into `.svelte.ts`.

---

## 2. Extract pure logic early

**Move side-effect-free helpers to `*.ts` modules** next to the feature (or under `shared/` / `$lib` when reused):

- Serialization / deserialization (e.g. `formFromCharacter`, `saveBody`, validation).
- Small utilities (`prettyJson`, empty defaults, merge helpers).

This shrinks the Svelte file without changing behavior and makes unit testing straightforward.

---

## 3. Kill near-duplicated UI with one generic component

When two blocks are structurally the same (e.g. “provider list → model list → ordered selected list with drag-and-drop”), **do not copy-paste**:

- Introduce **one parameterized component** (e.g. an ordered catalog picker) with props for labels, data, active-provider hints, and callbacks.
- Share drag-and-drop helpers (e.g. ghost element creation, reorder logic) in a small `*.ts` module.

For **two shapes inside one file** (e.g. inline row + tooltip), **Svelte 5 `{#snippet}`** can dedupe markup without extracting a whole component.

Fixing a bug once beats forgetting the mirror copy.

---

## 4. Markdown and `{@html}`

**Do not hand-roll a markdown-to-HTML pipeline** in a page component for production previews:

- Prefer a maintained parser plus a **strict sanitizer** (e.g. DOMPurify) before any `{@html}`.
- Treat every `{@html}` boundary as a security and maintenance boundary; centralize rendering in one preview component.

Before adding **any** new npm dependency, verify the **current latest stable version** (do not rely on stale training data).

---

## 5. Tailwind vs `<style>` — when to use which

This project uses **Tailwind CSS v4** with design tokens in global CSS (`app.css`). Default to **utility classes** for layout, spacing, typography, and colors.

**Use component `<style>` (scoped) sparingly** for:

- **Third-party or injected HTML** styling (e.g. markdown output) where Tailwind does not author the nodes.
- **Complex pseudo / interaction** states that are clearer in a few lines of CSS than long arbitrary-value class strings.

**Avoid large blocks of `:global(...)` rules in a feature page.** If styles are global-by-necessity, they belong in:

- A dedicated component that wraps the markup those rules target, with **scoped** selectors; or
- Global design layers (`app.css`) when truly app-wide.

**Red flag:** many `:global` selectors for “`.field`”, “`.section-card`”, etc. — that is usually a sign to introduce **small presentational components** (`Field.svelte`, `SectionCard.svelte`) with Tailwind on real elements instead of global class names.

When **replacing layout `<style>` with utilities**, default **`sm` / `md` / `lg` / `xl`** breakpoints may **not** match a legacy **`@media`**. Use **arbitrary min-width** (e.g. **`min-[1180px]:`**) when you need **pixel-parity**, or the layout will drift subtly.

---

## 6. Typography for rich HTML previews

For markdown/HTML previews, consider **`@tailwindcss/typography`** and a `prose` variant on the wrapper. That often replaces dozens of hand-written `h1`/`p`/`ul` rules.

If you skip the plugin, keep preview typography rules in **the preview component’s scoped `<style>`**, not in the parent page.

---

## 7. State and Svelte 5 runes

**Split state by responsibility** when a page gets heavy:

- **Controller / form modules** (`.svelte.ts`): loading flags, list rows, API orchestration, `save` / `delete`.
- **Preferences** (URL **or** **session**): keep restore/persist logic in a small module (e.g. `create*Preferences()` in `.svelte.ts`); **children receive plain props**, not ad-hoc `sessionStorage` reads in leaves.

When moving state out of the page:

- Ensure **`bind:`** targets remain valid (writable state must live where Svelte expects).
- Prefer explicit props and callbacks over deep prop drilling only when it stays readable; otherwise a small context or localized store is fine.

---

## 8. Folder layout for large features

A scalable pattern:

```text
features/<area>/
  <Area>Page.svelte          # thin shell
  browse/                    # list-only UI
  view/                      # read-only detail
  edit/                      # form sections, dialogs
  state/                     # *.svelte.ts controllers, guards
  shared/                    # helpers, *-classes.ts, *-a11y.ts (stable ids), lifecycle, widgets
```

Names are flexible; the idea is **vertical slices by screen concern**, not one mega-file. **`shared/`** is not only Svelte widgets—**pure helpers, design tokens / class maps, stable DOM ids, and mount helpers** belong there too.

---

## 9. Refactor in small, shippable steps

When decomposing a large page:

1. Extract **pure `*.ts` helpers** (no UI change).
2. Extract **self-contained UI** (markdown preview, pickers, modals) and swap usage.
3. **Replace duplicated blocks** with one generic component.
4. **Move orchestration** into `.svelte.ts` modules if the `<script>` is still huge.
5. **Delete global CSS** in favor of components + Tailwind (+ typography plugin where agreed).

Each step should leave the app working.

---

## 10. Checklist before merging a large Svelte change

- [ ] No duplicated drag-and-drop or picker logic without a shared abstraction.
- [ ] No hand-rolled markdown security story without sanitizer + single render path.
- [ ] No new large `:global` style blocks in page components for patterns that could be components.
- [ ] Children get props/callbacks; **preferences** (URL or session) not scattered across every leaf.
- [ ] **Disclosure UI:** if a control uses **`aria-controls`**, the target stays in the DOM when “closed” (e.g. **`hidden`**), not **`{#if}`**-removed, unless you omit **`aria-controls`** when the target is unmounted.
- [ ] `bind:` and runes still line up after moving state.
- [ ] Dependencies added only after checking **latest stable** versions.

---

## 11. Gotchas

Short pitfalls seen on complex admin pages (e.g. heavy forms + `.svelte.ts` controllers). Prefer fixing the pattern once here rather than rediscovering it per feature.

1. **Derived values from `create*()` factories.** Expose **`$derived`** fields through **`get`ters** on the returned object (`get visibleRows() { return visibleRows }`), not **shorthand** properties (`return { visibleRows }`—that can raise **`state_referenced_locally`** and capture a **stale** value). Getters also help when consumers are **identity-sensitive** (`Set` membership, reference equality) or need plain snapshots.

2. **`$effect` that notifies parents.** When an effect pushes DOM refs or derived snapshots upward (e.g. `bind:this` on `<canvas>` → `onCanvasChange(el)`), compare against a **last-synced reference** (or equivalent) before calling the parent so unrelated reactive churn or changing callback identities do not trigger redundant parent work.

3. **Dynamic IDs for accessibility.** For collapsibles and expandable regions, pair **`aria-controls`** with the controlled element’s **`id`** using a real expression (e.g. shared **`feature-a11y.ts`** constants used by both control and target). Centralize ids so strings cannot drift. If **`aria-controls`** points at an element, that element must **exist in the DOM** when the relationship matters—prefer **`hidden`** over **`{#if}`** for the region so the **`id`** is not removed while the button still references it.

4. **`bind:` requires a concrete binding target.** You often need parallel `{#if}` / `{:else}` branches that differ only by which property is bound (`bind:selectedIds={form.llm_models}` vs `...voice_models`). That duplication is normal—the compiler needs a direct writable path. Abstracting it away usually means introducing an explicit writable adapter or wrapper component.

5. **Shared visual tokens without new globals.** When several sibling components must match the same Tailwind-heavy styling (section titles, hints, cards), a **tiny `*.ts` module exporting class string constants** avoids drift and reduces pressure to add feature-specific global utilities in `app.css`.

6. **Plain `*.ts` importing factories.** Mount helpers and similar should **`import type { … }` from `*.svelte.ts`** when they only need types, avoiding **accidental circular runtime imports** with `state/` factories.

---

## Related docs

- Admin UI overview: `docs/admin-ui.md`
- Dev environment setup (if tooling changes): `mintdocs/build/first-time-setup.mdx`
