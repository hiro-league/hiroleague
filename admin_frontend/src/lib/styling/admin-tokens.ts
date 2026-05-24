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

// ── page wrapper ───────────────────────────────────────────────────────────

/** Left-aligned page width used by every admin page. */
export const ADMIN_PAGE_MAX_W = 'grid max-w-[1420px] gap-5';

// ── page header (kicker + brand-gradient title + muted intro) ──────────────

export const ADMIN_HEADER_KICKER = 'font-sans text-xs font-extrabold uppercase text-primary';

export const ADMIN_HEADER_TITLE = 'brand-text-gradient mt-1 text-3xl font-semibold';

export const ADMIN_HEADER_INTRO = 'font-sans text-sm text-muted-foreground';

/**
 * Wrapper applied to `<AdminPageHeader sticky>` so the kicker/title/tabs/actions
 * stay pinned beneath the shell header (4rem). The component publishes its own
 * height via `--admin-page-header-h` so secondary toolbars can align without
 * magic pixel constants.
 */
export const ADMIN_PAGE_STICKY_HEADER =
  'sticky top-16 z-10 -mx-4 border-b border-border/70 bg-background/95 px-4 pb-4 backdrop-blur supports-[backdrop-filter]:bg-background/85 md:-mx-6 md:px-6';

// ── tab strip ──────────────────────────────────────────────────────────────

export const ADMIN_TABLIST_SHELL = 'inline-flex rounded-lg border bg-card p-1';

/** Class to apply to each tab button; pass `active` to toggle the visual state. */
export function cnAdminTab(active: boolean) {
  return cn('shadow-none', !active && 'bg-transparent text-muted-foreground hover:bg-secondary');
}

// ── section cards (two deliberate variants — §2.4.4) ───────────────────────

/** Solid card for top-level page sections. */
export const ADMIN_SECTION_CARD = 'rounded-md border bg-card p-4 shadow-sm';

/** Translucent card for nested groupings inside another card. */
export const ADMIN_SECTION_CARD_MUTED = 'rounded-md border bg-background/45 p-4 shadow-sm';

export const ADMIN_SECTION_TITLE = 'font-sans text-base font-semibold text-primary';

export const ADMIN_SECTION_HEADING_LG = 'font-sans text-lg font-semibold text-foreground';

// ── form controls ──────────────────────────────────────────────────────────

export const ADMIN_FIELD_LABEL = 'grid gap-1 font-sans text-sm';

export const ADMIN_FIELD_LABEL_TEXT = 'font-medium';

export const ADMIN_INPUT =
  'h-9 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring';

export const ADMIN_INPUT_LG =
  'h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring';

export const ADMIN_SELECT = ADMIN_INPUT;

export const ADMIN_SELECT_LG = ADMIN_INPUT_LG;

/** Compact filter selects (Logs filter toolbar). */
export const ADMIN_SELECT_SM =
  'h-8 min-w-0 rounded-md border border-input bg-background px-2 font-sans text-sm text-foreground shadow-xs outline-none focus:ring-2 focus:ring-ring';

/** Multi-line message / notes fields. */
export const ADMIN_TEXTAREA =
  'min-h-11 w-full resize-y rounded-md border border-input bg-background px-3 py-2.5 text-sm leading-snug outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** Search field shell with embedded transparent input (Logs header). */
export const ADMIN_SEARCH_FIELD =
  'flex h-9 min-w-72 items-center gap-2 rounded-md border border-input bg-background px-3 font-sans text-sm shadow-xs focus-within:ring-2 focus-within:ring-ring';

// ── table chrome (primitives implemented in Phase 4.5; tokens shipped now
// so feature-local copies can be retired without two rounds of churn) ──────

export const ADMIN_TABLE = 'w-full text-left font-sans text-sm';

export const ADMIN_TABLE_HEAD = 'sticky top-0 bg-muted text-xs uppercase text-muted-foreground';

export const ADMIN_TABLE_ROW = 'border-t transition-[background-color,box-shadow]';

/** Sticky `<thead>` offset beneath shell header + optional sticky toolbar. */
export const ADMIN_TABLE_STICKY_TOP =
  'calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px))';

export const ADMIN_TABLE_GRID_HEAD =
  'grid gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground';

export const ADMIN_TABLE_GRID_ROW = 'grid min-h-16 gap-3 border-t px-3 py-3';

/** Row styling for clickable list rows with a hover/selected accent. */
export function cnAdminTableRow(selected: boolean) {
  return cn(
    'cursor-pointer border-t transition-[background-color,box-shadow]',
    'hover:bg-primary/10 hover:shadow-[inset_0_0_0_2px] hover:shadow-brand',
    selected && 'bg-primary/10 shadow-[inset_0_0_0_2px] shadow-primary'
  );
}
