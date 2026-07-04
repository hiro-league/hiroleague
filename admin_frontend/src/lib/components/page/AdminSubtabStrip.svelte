<script lang="ts" generics="TId extends string">
  /**
   * Second-level underline subtab strip (Preferences sections, Graph runs
   * ledger + open inspectors). Page-level pill tabs use `<AdminTabStrip>`.
   *
   * - Fixed `tabs` render as underline buttons and call `onSelect`.
   * - `extraTabs` — dynamic subtabs after the fixed set (Graph runs per-run).
   * - `toolbar` — trailing icon/actions row (refresh, collapse, …).
   * - `scrollable` — keep tabs on one line; on overflow, flanking chevron
   *   buttons scroll the strip left/right (the scrollbar itself stays hidden).
   */
  import type { Snippet } from 'svelte';
  import { ChevronLeft, ChevronRight } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import { ADMIN_SUBTAB_STRIP_SHELL, ADMIN_SUBTAB_TABLIST } from '$lib/styling/admin-tokens';
  import AdminSubtabButton from './AdminSubtabButton.svelte';
  import type { AdminSubtabDescriptor } from './tab-types';

  type Props = {
    ariaLabel: string;
    tabs: readonly AdminSubtabDescriptor<TId>[];
    active: TId;
    onSelect?: (id: TId) => void;
    class?: string;
    /** Keep tabs on one line and reveal scroll-arrow buttons on overflow (vs. wrapping). */
    scrollable?: boolean;
    extraTabs?: Snippet;
    toolbar?: Snippet;
  };

  let {
    ariaLabel,
    tabs,
    active,
    onSelect,
    class: className,
    scrollable = false,
    extraTabs,
    toolbar
  }: Props = $props();

  // Scroll-arrow state: only meaningful when `scrollable`. `overflowing` gates whether the arrows
  // render at all; `canLeft`/`canRight` disable the arrow once that edge is reached.
  let tablistEl = $state<HTMLDivElement | null>(null);
  let overflowing = $state(false);
  let canLeft = $state(false);
  let canRight = $state(false);

  function measure() {
    const el = tablistEl;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    overflowing = max > 1;
    canLeft = el.scrollLeft > 1;
    canRight = el.scrollLeft < max - 1;
  }

  function scrollByDir(dir: 1 | -1) {
    const el = tablistEl;
    if (!el) return;
    // Page by ~60% of the visible width so a couple of tabs stay in view as an anchor.
    el.scrollBy({ left: dir * el.clientWidth * 0.6, behavior: 'smooth' });
  }

  // Reveal-neighbor padding: bring the target tab fully in view PLUS a sliver of the tab beyond it,
  // so clicking a tab tucked under an arrow scrolls the next one into reach (and clear of the arrow).
  const EDGE_PAD = 52;

  function scrollTabIntoView(tab: HTMLElement) {
    const el = tablistEl;
    if (!el) return;
    const contRect = el.getBoundingClientRect();
    const tabRect = tab.getBoundingClientRect();
    const left = tabRect.left - contRect.left + el.scrollLeft;
    const right = left + tabRect.width;
    if (right + EDGE_PAD > el.scrollLeft + el.clientWidth) {
      el.scrollTo({ left: right + EDGE_PAD - el.clientWidth, behavior: 'smooth' });
    } else if (left - EDGE_PAD < el.scrollLeft) {
      el.scrollTo({ left: Math.max(0, left - EDGE_PAD), behavior: 'smooth' });
    }
  }

  // Re-measure on viewport resize (ResizeObserver) and when tabs are added/removed or their labels
  // load in late (MutationObserver) — both change scrollWidth without a scroll event.
  $effect(() => {
    const el = tablistEl;
    if (!el || !scrollable) return;
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    const mo = new MutationObserver(measure);
    mo.observe(el, { childList: true, subtree: true, characterData: true });
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  });

  // When the active tab changes (clicked, opened from the table, or restored from the URL), scroll it
  // into view — the common tab-strip behavior so a tab tucked behind an arrow becomes fully clickable.
  $effect(() => {
    void active; // re-run on selection change
    if (!scrollable) return;
    const el = tablistEl;
    if (!el) return;
    const selected = el.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
    if (selected) scrollTabIntoView(selected);
  });
</script>

<div class={cn(ADMIN_SUBTAB_STRIP_SHELL, className)}>
  {#if scrollable && overflowing}
    <button
      type="button"
      class="-mb-px flex h-9 w-6 shrink-0 items-center justify-center rounded-t-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-25"
      aria-label="Scroll tabs left"
      disabled={!canLeft}
      onclick={() => scrollByDir(-1)}
    >
      <ChevronLeft size={18} aria-hidden="true" />
    </button>
  {/if}
  <div
    bind:this={tablistEl}
    class={cn(
      ADMIN_SUBTAB_TABLIST,
      // Hide the native scrollbar — the chevron buttons are the affordance (trackpad/shift-wheel
      // still work). `scroll-smooth` animates the arrow paging.
      scrollable &&
        'flex-nowrap overflow-x-auto overflow-y-hidden scroll-smooth [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'
    )}
    role="tablist"
    aria-label={ariaLabel}
    onscroll={scrollable ? measure : undefined}
  >
    {#each tabs as tab (tab.id)}
      <AdminSubtabButton
        label={tab.label}
        count={tab.count}
        countText={tab.countText}
        countClass={tab.countClass}
        active={tab.id === active}
        disabled={tab.disabled}
        ariaLabel={tab.ariaLabel}
        htmlId={tab.htmlId}
        ariaControls={tab.ariaControls}
        title={tab.title}
        onclick={() => onSelect?.(tab.id)}
      />
    {/each}
    {#if extraTabs}
      {@render extraTabs()}
    {/if}
  </div>
  {#if scrollable && overflowing}
    <button
      type="button"
      class="-mb-px flex h-9 w-6 shrink-0 items-center justify-center rounded-t-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-25"
      aria-label="Scroll tabs right"
      disabled={!canRight}
      onclick={() => scrollByDir(1)}
    >
      <ChevronRight size={18} aria-hidden="true" />
    </button>
  {/if}
  {#if toolbar}
    <div class="flex shrink-0 items-end gap-1 pb-px">
      {@render toolbar()}
    </div>
  {/if}
</div>
