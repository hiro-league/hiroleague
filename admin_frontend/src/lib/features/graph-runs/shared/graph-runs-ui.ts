/**
 * Graph-runs feature-local class helpers.
 *
 * Header / tablist tokens moved to `$lib/styling/admin-tokens`; the primary
 * pill tab strip now uses `<AdminTabStrip>` directly. What remains here is
 * the ledger search hit highlight rule.
 */

/** Search hit highlight in ledger preview cells (`dark:` uses app.css `@custom-variant dark`). */
export const GRAPH_RUNS_PREVIEW_HIGHLIGHT_MARK =
  'rounded-sm bg-yellow-200 p-0 [font:inherit] text-inherit dark:bg-yellow-600 dark:text-amber-950';
