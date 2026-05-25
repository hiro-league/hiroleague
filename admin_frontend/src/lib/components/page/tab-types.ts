/**
 * Shared types for `<AdminTabStrip>` / `<AdminTabButton>` / `<AdminSubtabStrip>`
 * / `<AdminPageHeader>`.
 *
 * Tabs carry an explicit `kind`:
 *  - `'pane'` (default) — local content; the host renders the matching panel.
 *  - `'route'` — a real anchor that navigates elsewhere; rendered as `<a href>`
 *    so middle-click / copy-link / right-click work. See
 *    `docs/admin-frontend-refactor-plan.md` §2.4.6.
 */

export type AdminTabKind = 'pane' | 'route';

export type AdminPaneTabDescriptor<TId extends string = string> = {
  id: TId;
  label: string;
  kind?: 'pane';
  disabled?: boolean;
  /** Override `aria-label` for screen readers when `label` is not descriptive enough. */
  ariaLabel?: string;
  /** DOM `id` for the rendered tab element (use when consumers reference it via `aria-labelledby`). */
  htmlId?: string;
  /** `id` of the controlled tabpanel for `aria-controls`. */
  ariaControls?: string;
};

export type AdminRouteTabDescriptor<TId extends string = string> = {
  id: TId;
  label: string;
  kind: 'route';
  /** Required for `kind: 'route'`. */
  href: string;
  disabled?: boolean;
  ariaLabel?: string;
  htmlId?: string;
  ariaControls?: string;
};

export type AdminTabDescriptor<TId extends string = string> =
  | AdminPaneTabDescriptor<TId>
  | AdminRouteTabDescriptor<TId>;

/** Second-level underline tab (Preferences sections, Graph runs ledger strip). */
export type AdminSubtabDescriptor<TId extends string = string> = {
  id: TId;
  label: string;
  disabled?: boolean;
  ariaLabel?: string;
  htmlId?: string;
  ariaControls?: string;
  /** Native `title` tooltip (e.g. truncated run id on dynamic Graph runs tabs). */
  title?: string;
};
