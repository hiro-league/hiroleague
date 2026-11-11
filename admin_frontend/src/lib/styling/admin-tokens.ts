/**
 * Shared Tailwind class tokens for admin pages.
 *
 * Single canonical home for cross-cutting tokens (page wrapper, header,
 * section cards, form controls, table chrome). Replaces per-feature copies
 * such as `KNOWLEDGE_HEADER_*`, `GRAPH_RUNS_HEADER_*`, and the header
 * portion of `character-section-classes.ts`. See
 * `docs/admin-frontend-refactor-plan.md` §2.4.4 and §3.
 */
import { cn } from '$lib/utils';

// ── shell content inset (sidebar → main column) ────────────────────────────

/** Vertical padding on `<main>` in AdminShell. */
export const ADMIN_SHELL_CONTENT_PY = 'py-4 md:py-6';

/** Right inset — unchanged from original shell padding. */
export const ADMIN_SHELL_CONTENT_PR = 'pr-4 md:pr-6';

/** Left inset — 2× the original `pl-4` / `md:pl-6` gap from the side nav. */
// UI kit step 3: the page area's padding is the shared shell's (p-4, md:p-6); the left side was twice that.
export const ADMIN_SHELL_CONTENT_PL = 'pl-4 md:pl-6';

export const ADMIN_SHELL_CONTENT_PADDING = cn(
  ADMIN_SHELL_CONTENT_PY,
  ADMIN_SHELL_CONTENT_PR,
  ADMIN_SHELL_CONTENT_PL
);

export const ADMIN_SHELL_HEADER_PADDING = cn(ADMIN_SHELL_CONTENT_PR, ADMIN_SHELL_CONTENT_PL);

/** Cancels shell content padding so sticky page chrome can bleed edge-to-edge in `<main>`. */
export const ADMIN_SHELL_STICKY_BLEED = cn(
  '-mx-4 px-4 md:-mx-6 md:px-6'
);

// ── page wrapper ───────────────────────────────────────────────────────────

/** Left-aligned page width used by every admin page. */
export const ADMIN_PAGE_MAX_W = 'grid max-w-[1420px] gap-5';

/**
 * Wider page width for dense, table + detail-panel operations pages (Graph runs,
 * Logs) whose master/detail split needs more horizontal room. Keep the bare
 * `max-w` literal here in sync with the Logs page custom flex wrapper.
 */
export const ADMIN_PAGE_MAX_W_WIDE = 'grid max-w-[2000px] gap-5';

// ── page header (kicker + brand-gradient title + muted intro) ──────────────

export const ADMIN_HEADER_INTRO = 'font-sans text-sm text-muted-foreground';

// ── tab strip ──────────────────────────────────────────────────────────────

/** Class to apply to each tab button; pass `active` to toggle the visual state. */
export function cnAdminTab(active: boolean) {
  return cn('shadow-none', !active && 'bg-transparent text-muted-foreground hover:bg-secondary');
}

// ── second-level subtab strip (underline, below page title or primary tabs) ─

// ── section cards (two deliberate variants — §2.4.4) ───────────────────────


export const ADMIN_SECTION_TITLE = 'font-sans text-base font-semibold text-primary';


// ── form controls ──────────────────────────────────────────────────────────

// Focus ring is drawn `ring-inset` (inside the element's own box) so it is never
// clipped on the bottom/left when an input sits flush against an `overflow-hidden`
// ancestor; `border-ring` keeps it reading as a single clean blue outline.
const ADMIN_FOCUS_RING =
  'focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';

export const ADMIN_INPUT = cn(
  'h-9 rounded-md border border-input bg-background px-3 text-sm outline-none',
  ADMIN_FOCUS_RING
);

export const ADMIN_INPUT_LG = cn(
  'h-10 rounded-md border border-input bg-background px-3 text-sm outline-none',
  ADMIN_FOCUS_RING
);

/** Destructive icon button for clearing a single filter (LogsFiltersPanel). */
export const FILTER_CLEAR_ICON_BTN =
  'size-8 shrink-0 text-destructive hover:bg-destructive/15 hover:text-destructive';

/** Multi-line message / notes fields. */
export const ADMIN_TEXTAREA = cn(
  'min-h-11 w-full resize-y rounded-md border border-input bg-background px-3 py-2.5 text-sm leading-snug outline-none',
  ADMIN_FOCUS_RING
);

/** Search field shell with embedded transparent input (Logs header). */
export const ADMIN_SEARCH_FIELD = cn(
  'flex h-9 min-w-72 items-center gap-2 rounded-md border border-input bg-background px-3 font-sans text-sm shadow-xs',
  'focus-within:border-ring focus-within:ring-2 focus-within:ring-inset focus-within:ring-ring'
);

// ── table chrome (primitives implemented in Phase 4.5; tokens shipped now
// so feature-local copies can be retired without two rounds of churn) ──────

export const ADMIN_TABLE_HEAD = 'bg-muted text-xs uppercase text-muted-foreground';

export const ADMIN_TABLE_GRID_ROW = 'grid min-h-16 gap-3 border-t px-3 py-3';
