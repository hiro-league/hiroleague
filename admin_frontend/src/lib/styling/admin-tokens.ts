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
export const ADMIN_SHELL_CONTENT_PL = 'pl-8 md:pl-12';

export const ADMIN_SHELL_CONTENT_PADDING = cn(
  ADMIN_SHELL_CONTENT_PY,
  ADMIN_SHELL_CONTENT_PR,
  ADMIN_SHELL_CONTENT_PL
);

export const ADMIN_SHELL_HEADER_PADDING = cn(ADMIN_SHELL_CONTENT_PR, ADMIN_SHELL_CONTENT_PL);

/** Cancels shell content padding so sticky page chrome can bleed edge-to-edge in `<main>`. */
export const ADMIN_SHELL_STICKY_BLEED = cn(
  '-ml-8 -mr-4 pl-8 pr-4 md:-ml-12 md:-mr-6 md:pl-12 md:pr-6'
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

export const ADMIN_HEADER_KICKER = 'font-sans text-xs font-extrabold uppercase text-primary';

export const ADMIN_HEADER_TITLE = 'brand-text-gradient mt-1 text-3xl font-semibold leading-tight';

export const ADMIN_HEADER_INTRO = 'font-sans text-sm text-muted-foreground';

/** Inline kicker/title row when a sticky header compacts on scroll. */
export const ADMIN_HEADER_KICKER_COMPACT =
  'shrink-0 font-sans text-[10px] font-extrabold uppercase tracking-wide text-primary';

export const ADMIN_HEADER_TITLE_COMPACT = 'brand-text-gradient truncate text-lg font-semibold leading-tight';

export const ADMIN_HEADER_BREADCRUMB_SEP = 'shrink-0 font-sans text-sm font-normal text-muted-foreground/45';

/**
 * Sticky positioning shell — always applied when `<AdminPageHeader sticky>`.
 * Frosted chrome (`ADMIN_PAGE_STICKY_HEADER_PINNED`) is added only once pinned.
 */
export const ADMIN_PAGE_STICKY_HEADER_POSITION = cn(
  'sticky top-16 z-10 mt-0 border-b border-transparent bg-transparent transition-[margin,padding,box-shadow,background-color,border-color,backdrop-filter] duration-200 ease-out',
  ADMIN_SHELL_STICKY_BLEED
);

/** Frosted chrome when pinned; bleeds into `<main>` padding under the shell bar. */
export const ADMIN_PAGE_STICKY_HEADER_PINNED =
  '-mt-4 border-border/70 bg-background/95 py-2 backdrop-blur shadow-sm supports-[backdrop-filter]:bg-background/85 md:-mt-6';

/** @deprecated Use ADMIN_PAGE_STICKY_HEADER_POSITION + PINNED. */
export const ADMIN_PAGE_STICKY_HEADER_BASE = ADMIN_PAGE_STICKY_HEADER_POSITION;

/** @deprecated Pinned headers use ADMIN_PAGE_STICKY_HEADER_PINNED. */
export const ADMIN_PAGE_STICKY_HEADER_EXPANDED = '';

/** @deprecated Pinned headers use ADMIN_PAGE_STICKY_HEADER_PINNED. */
export const ADMIN_PAGE_STICKY_HEADER_COMPACT = ADMIN_PAGE_STICKY_HEADER_PINNED;

/** @deprecated Use ADMIN_PAGE_STICKY_HEADER_POSITION + PINNED. */
export const ADMIN_PAGE_STICKY_HEADER = cn(
  ADMIN_PAGE_STICKY_HEADER_POSITION,
  ADMIN_PAGE_STICKY_HEADER_PINNED
);

// ── tab strip ──────────────────────────────────────────────────────────────

export const ADMIN_TABLIST_SHELL = 'inline-flex gap-1 rounded-lg border bg-card p-1';

/** Class to apply to each tab button; pass `active` to toggle the visual state. */
export function cnAdminTab(active: boolean) {
  return cn('shadow-none', !active && 'bg-transparent text-muted-foreground hover:bg-secondary');
}

// ── second-level subtab strip (underline, below page title or primary tabs) ─

/** Outer row: tablist + optional trailing toolbar. */
export const ADMIN_SUBTAB_STRIP_SHELL =
  '-mb-px flex min-h-[2.5rem] min-w-0 items-end gap-3 border-b border-border';

/** Tablist row inside `ADMIN_SUBTAB_STRIP_SHELL`. */
export const ADMIN_SUBTAB_TABLIST =
  'flex min-h-9 min-w-0 flex-1 flex-wrap items-end gap-x-1 gap-y-0';

/** Underline subtab button — pass `active` for the selected tab. */
export function cnAdminSubtab(active: boolean, className?: string) {
  return cn(
    '-mb-px min-w-0 max-w-[min(22rem,calc(100vw-10rem))] shrink-0 truncate border-b-2 border-transparent bg-transparent px-3 py-2 text-left font-sans text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
    active && 'border-primary font-semibold text-foreground',
    className
  );
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

export const ADMIN_TABLE_HEAD = 'bg-muted text-xs uppercase text-muted-foreground';

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
