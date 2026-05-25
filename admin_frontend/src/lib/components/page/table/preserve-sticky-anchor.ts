/**
 * Preserve the viewport position of a sticky-anchor element across a layout
 * change that would otherwise shrink the document and clamp `window.scrollY`.
 *
 * Typical use — wrap an async filter/refresh that re-renders a long list:
 *
 *   await preserveStickyAnchor(applyModelFilters);
 *
 * The default anchor is `[data-sticky-head]` (published by `AdminTableShell`),
 * which is the most stable element on a page whose list rows churn on filter
 * changes. Pass a custom CSS selector when needed.
 *
 * Mechanics:
 *  1. Read the anchor's `getBoundingClientRect().top` before the mutation.
 *  2. Run the mutation (sync or async).
 *  3. Await `tick()` so Svelte commits the new DOM.
 *  4. Read the anchor's new `top` and `window.scrollBy(0, newTop - prevTop)`.
 *     The anchor stays at the same y-coordinate; sticky chrome above it does
 *     not displace, and the user keeps their visual context.
 *
 * No-op outside the browser (SSR) and when the anchor element is absent.
 */
import { tick } from 'svelte';

const DEFAULT_ANCHOR_SELECTOR = '[data-sticky-head]';

export async function preserveStickyAnchor<T>(
  action: () => T | Promise<T>,
  anchorSelector: string = DEFAULT_ANCHOR_SELECTOR
): Promise<T> {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    return action();
  }

  const anchorBefore = document.querySelector(anchorSelector);
  const prevTop = anchorBefore ? anchorBefore.getBoundingClientRect().top : null;

  const result = await action();
  await tick();

  if (prevTop !== null) {
    const anchorAfter = document.querySelector(anchorSelector);
    if (anchorAfter) {
      const newTop = anchorAfter.getBoundingClientRect().top;
      const delta = newTop - prevTop;
      if (Math.abs(delta) > 0.5) {
        window.scrollBy({ top: delta, left: 0, behavior: 'instant' as ScrollBehavior });
      }
    }
  }

  return result;
}

/**
 * Fire-and-forget variant for cases where the state change has already been
 * applied synchronously (e.g. a Svelte `bind:` setter cannot be async). Call
 * this *after* setting the new value; it captures the anchor on the *next*
 * frame relative to the post-mutation layout.
 *
 * Because Svelte 5 setters are synchronous and the reactive re-render is
 * scheduled, we measure *before* the next paint (`requestAnimationFrame`)
 * and again after `tick()` to compute the delta. If the layout has already
 * stabilised we use the current scroll y-difference of the anchor itself.
 */
export function preserveStickyAnchorAround(anchorSelector: string = DEFAULT_ANCHOR_SELECTOR): void {
  if (typeof document === 'undefined' || typeof window === 'undefined') return;
  const anchorBefore = document.querySelector(anchorSelector);
  if (!anchorBefore) return;
  const prevTop = anchorBefore.getBoundingClientRect().top;
  void tick().then(() => {
    const anchorAfter = document.querySelector(anchorSelector);
    if (!anchorAfter) return;
    const newTop = anchorAfter.getBoundingClientRect().top;
    const delta = newTop - prevTop;
    if (Math.abs(delta) > 0.5) {
      window.scrollBy({ top: delta, left: 0, behavior: 'instant' as ScrollBehavior });
    }
  });
}
