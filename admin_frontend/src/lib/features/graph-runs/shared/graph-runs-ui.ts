/** Shared Tailwind/class strings for graph-runs UI (header tab strip). */
import { cn } from '$lib/utils';

export const GRAPH_RUNS_HEADER_KICKER = 'm-0 font-sans text-xs font-extrabold uppercase text-primary';

export const GRAPH_RUNS_HEADER_TITLE =
  'brand-text-gradient mb-0 mt-1 text-3xl font-semibold';

export const GRAPH_RUNS_HEADER_INTRO = 'mb-0 mt-1 font-sans text-sm text-muted-foreground';

/** Matches `rounded-lg border bg-card p-1` tablist from the redesign. */
export const GRAPH_RUNS_TABLIST_SHELL =
  'inline-flex max-w-full flex-wrap rounded-lg border bg-card p-1';

export function cnGraphRunsMainPaneTab(active: boolean) {
  return cn('shadow-none', !active && 'bg-transparent text-muted-foreground hover:bg-secondary');
}

/** Search hit highlight in ledger preview cells (`dark:` uses app.css `@custom-variant dark`). */
export const GRAPH_RUNS_PREVIEW_HIGHLIGHT_MARK =
  'rounded-sm bg-yellow-200 p-0 [font:inherit] text-inherit dark:bg-yellow-600 dark:text-amber-950';
