/**
 * The admin's own layout classes: the page area's padding and the width of a page. (The look of its controls, tables
 * and headings is the kit's.)
 */

// ── shell content inset (sidebar → main column) ────────────────────────────

// The page area's padding: the shared shell's (UI kit step 3).
export const ADMIN_SHELL_CONTENT_PADDING = 'p-4 md:p-6';

export const ADMIN_SHELL_HEADER_PADDING = 'pr-4 pl-4 md:pr-6 md:pl-6';

/** Cancels shell content padding so sticky page chrome can bleed edge-to-edge in `<main>`. */
export const ADMIN_SHELL_STICKY_BLEED = '-mx-4 px-4 md:-mx-6 md:px-6';

// ── page wrapper ───────────────────────────────────────────────────────────

/** Left-aligned page width used by every admin page. */
export const ADMIN_PAGE_MAX_W = 'grid max-w-[1420px] gap-5';

/**
 * Wider page width for dense, table + detail-panel operations pages (Graph runs,
 * Logs) whose master/detail split needs more horizontal room. Keep the bare
 * `max-w` literal here in sync with the Logs page custom flex wrapper.
 */
export const ADMIN_PAGE_MAX_W_WIDE = 'grid max-w-[2000px] gap-5';

// ── table head ─────────────────────────────────────────────────────────────

// The head cells (the kit's SortHead or a plain th) get the admin's roomier padding and the head's own colour.
export const ADMIN_TABLE_HEAD =
  'bg-muted text-xs uppercase text-muted-foreground [&_th]:h-auto [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-bold [&_th]:whitespace-normal [&_th]:text-inherit';
