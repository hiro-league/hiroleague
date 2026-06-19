/** Sticky `<thead>` offset beneath eval page chrome + sub-tabs + answers toolbar. */
export const EVAL_ANSWERS_TABLE_STICKY_TOP =
  'calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px) + var(--admin-eval-subtabs-h, 0px) + var(--admin-eval-acontrols-h, 0px))';

/** Compact toolbar search field (answers pane, corpus review). */
export const EVAL_TOOLBAR_SEARCH =
  'flex h-8 w-48 min-w-0 items-center gap-1.5 rounded-md border border-input bg-background pl-2 pr-1 font-sans text-xs shadow-xs focus-within:border-ring focus-within:ring-2 focus-within:ring-inset focus-within:ring-ring';

export const EVAL_TOOLBAR_SEARCH_INPUT =
  'min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground';
