/**
 * Graph-runs feature-local class helpers.
 *
 * Header / tablist tokens moved to `$lib/styling/admin-tokens`. What remains
 * here is feature-specific: the primary-pane tab helper and the ledger search
 * hit highlight rule.
 */
import { cn } from '$lib/utils';

export function cnGraphRunsMainPaneTab(active: boolean) {
  return cn('shadow-none', !active && 'bg-transparent text-muted-foreground hover:bg-secondary');
}

/** Search hit highlight in ledger preview cells (`dark:` uses app.css `@custom-variant dark`). */
export const GRAPH_RUNS_PREVIEW_HIGHLIGHT_MARK =
  'rounded-sm bg-yellow-200 p-0 [font:inherit] text-inherit dark:bg-yellow-600 dark:text-amber-950';
