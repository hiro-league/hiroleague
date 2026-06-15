import { getContext, setContext } from 'svelte';

const KEY = Symbol('admin-page-header');

/**
 * Reactive view of the sticky `AdminPageHeader` state, provided to everything
 * rendered inside it. Page chrome that compacts together with the header
 * (e.g. a sticky toolbar hiding its secondary row) must derive from this
 * `pinned` signal instead of listening to `window.scrollY` itself: the header
 * applies hysteresis *and* document-height compensation when it pins, so
 * collapses driven by it cannot enter the shrink → scrollY-clamp → un-collapse
 * oscillation that a raw scroll-threshold toggle causes on borderline-height
 * pages.
 */
export type AdminPageHeaderContext = {
  /** True while the header is pinned/compacted (including `forceCompact`). */
  readonly pinned: boolean;
};

export function setAdminPageHeaderContext(ctx: AdminPageHeaderContext): void {
  setContext(KEY, ctx);
}

/** `null` when no `AdminPageHeader` ancestor provides the context. */
export function getAdminPageHeaderContext(): AdminPageHeaderContext | null {
  return getContext<AdminPageHeaderContext>(KEY) ?? null;
}
