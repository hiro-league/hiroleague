/**
 * Publish an element's pixel height into a CSS custom property so sticky bars
 * stacked below it can offset by `var(--name)`.
 *
 * Replaces the hand-rolled `ResizeObserver` + `setProperty` + (optional) scroll
 * dance duplicated across sticky toolbars (the eval sub-tab bar and the answers
 * controls bar). Returns a cleanup fn (disconnect + remove the property) for use
 * as an `onMount` / `$effect` teardown.
 *
 * @param el      The element whose height is measured.
 * @param varName CSS variable to set (e.g. `--admin-eval-subtabs-h`).
 * @param opts.target      Element the property is set on. Defaults to the
 *   nearest enclosing `<section>` (so nested sticky offsets resolve against it).
 * @param opts.trackScroll Also republish on window scroll (passive) — for bars
 *   whose height can change as the page reflows under them.
 */
export interface StickyHeightOptions {
  target?: HTMLElement | null;
  trackScroll?: boolean;
}

export function setupStickyHeightVar(
  el: HTMLElement,
  varName: string,
  opts: StickyHeightOptions = {}
): () => void {
  const target = opts.target ?? el.closest('section');
  if (!(target instanceof HTMLElement)) return () => {};
  // Skip redundant writes: only touch the inline style when the rounded height changes.
  let published = -1;
  const publish = () => {
    const h = Math.round(el.getBoundingClientRect().height);
    if (h === published) return;
    published = h;
    target.style.setProperty(varName, `${h}px`);
  };
  const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(publish) : null;
  ro?.observe(el);
  if (opts.trackScroll) window.addEventListener('scroll', publish, { passive: true });
  publish();
  return () => {
    ro?.disconnect();
    if (opts.trackScroll) window.removeEventListener('scroll', publish);
    target.style.removeProperty(varName);
  };
}
