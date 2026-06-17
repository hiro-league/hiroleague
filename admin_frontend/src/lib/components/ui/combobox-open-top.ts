/**
 * Force a bits-ui Combobox/Select dropdown to open scrolled to the TOP.
 *
 * On open, bits-ui auto-highlights the FIRST SELECTED value and scrolls it into view
 * (SelectMultipleRootState.setInitialHighlightedNode → node.scrollIntoView). For our multi-select
 * filters most options are checked and the checked-array order ≠ the visual sort order, so it lands
 * mid-list — the dropdown opens with the scrollbar "in the middle". There's no prop to disable it,
 * so we counter its single programmatic scroll: the first scroll after open snaps the viewport back
 * to 0 (one-shot — the viewport only scrolls because of that highlight, since it starts at 0). An
 * rAF fallback covers the case where bits-ui doesn't scroll at all (nothing selected / already top).
 *
 * Call from an `$effect` keyed on `open` + the viewport node; the return value is the effect cleanup.
 */
export function comboboxOpenAtTop(viewport: HTMLElement): () => void {
  let done = false;
  const reset = (): void => {
    if (done) return;
    done = true;
    viewport.scrollTop = 0;
    viewport.removeEventListener('scroll', reset);
  };
  viewport.addEventListener('scroll', reset);
  const raf = requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      if (!done) viewport.scrollTop = 0;
    })
  );
  return () => {
    viewport.removeEventListener('scroll', reset);
    cancelAnimationFrame(raf);
  };
}
