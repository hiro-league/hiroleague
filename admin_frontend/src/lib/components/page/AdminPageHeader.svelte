<script lang="ts">
  /**
   * Canonical page header for every admin page.
   *
   * Owns the page wrapper (`max-w-[1420px]` left-aligned) and a snippet-rich
   * header bar. Covers all 6 top-right variants from
   * `docs/admin-frontend-refactor-plan.md` §2.2 plus the dense Logs case from
   * §2.4.2.
   *
   * Snippet slots:
   *  - `titleAdornment` — inline element next to the title (e.g. open-folder icon).
   *  - `subtitle`       — replaces the `subtitle` string prop with rich markup.
   *  - `tabs`           — an `<AdminTabStrip>` (or a custom strip).
   *  - `actions`        — trailing buttons / link actions.
   *  - `actionsCollapse({ expanded, toggle, ariaControls })` — optional chevron
   *    toggle that collapses a secondary region elsewhere on the page; receives
   *    the wired state/handler so the page does not have to thread three props.
   *  - `backToTop`      — overrides the auto-generated "back to top" affordance
   *    that appears in the action row when `sticky` is set and the page has
   *    scrolled past `BACK_TO_TOP_THRESHOLD_PX`.
   *
   * Sticky mode (`sticky` prop):
   *  - Adds `ADMIN_PAGE_STICKY_HEADER` so the header pins under the shell.
   *  - Measures itself with `ResizeObserver` and publishes `--admin-page-header-h`
   *    on the wrapper so a sibling `<AdminPageStickyToolbar>` can mount at
   *    `top: calc(theme(spacing.16) + var(--admin-page-header-h))`. No magic
   *    pixel constants live on consumers.
   */
  import { onMount, type Snippet } from 'svelte';
  import { ArrowUp } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import {
    ADMIN_HEADER_INTRO,
    ADMIN_HEADER_KICKER,
    ADMIN_HEADER_TITLE,
    ADMIN_PAGE_MAX_W,
    ADMIN_PAGE_STICKY_HEADER
  } from '$lib/styling/admin-tokens';

  type ActionsCollapseArgs = {
    expanded: boolean;
    toggle: () => void;
    ariaControls: string | undefined;
  };

  type Props = {
    kicker?: string;
    title: string;
    /** Static intro text. Ignored when the `subtitle` snippet is provided. */
    subtitle?: string;
    sticky?: boolean;
    /** Optional extra classes appended to the wrapping `<section>`. */
    class?: string;
    /**
     * Override the default `ADMIN_PAGE_MAX_W` wrapper class. Use sparingly —
     * Logs uses this for its full-height virtualized-feed layout. Most pages
     * should leave this unset and append via `class` instead.
     */
    wrapperClass?: string;

    // actionsCollapse wiring
    /** Whether the collapsible region (e.g. Logs secondary controls) is open. */
    collapseExpanded?: boolean;
    /** Toggles `collapseExpanded`. */
    onToggleCollapse?: () => void;
    /** `id` of the controlled region for `aria-controls`. */
    collapseAriaControls?: string;

    // snippet slots
    titleAdornment?: Snippet;
    subtitleSlot?: Snippet;
    tabs?: Snippet;
    actions?: Snippet;
    actionsCollapse?: Snippet<[ActionsCollapseArgs]>;
    backToTop?: Snippet;
    /** Main page body — children are rendered below the header inside the wrapper. */
    children?: Snippet;
  };

  let {
    kicker,
    title,
    subtitle,
    sticky = false,
    class: className,
    wrapperClass,
    collapseExpanded = true,
    onToggleCollapse,
    collapseAriaControls,
    titleAdornment,
    subtitleSlot,
    tabs,
    actions,
    actionsCollapse,
    backToTop,
    children
  }: Props = $props();

  let headerEl = $state<HTMLDivElement | null>(null);
  let wrapperEl = $state<HTMLElement | null>(null);
  let scrolled = $state(false);

  const BACK_TO_TOP_THRESHOLD_PX = 480;

  function scrollToTop() {
    if (typeof window === 'undefined') return;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  onMount(() => {
    if (!sticky) return;

    // Publish header height so AdminPageStickyToolbar / AdminTableShell can
    // align the second-level sticky bar without pixel guesses.
    let publishedHeight = -1;
    const publishHeight = () => {
      if (!headerEl || !wrapperEl) return;
      const h = Math.round(headerEl.getBoundingClientRect().height);
      if (h !== publishedHeight) {
        publishedHeight = h;
        wrapperEl.style.setProperty('--admin-page-header-h', `${h}px`);
      }
    };

    const resizeObserver =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(publishHeight) : null;
    if (headerEl && resizeObserver) {
      resizeObserver.observe(headerEl);
    }
    publishHeight();

    const onScroll = () => {
      scrolled = window.scrollY > BACK_TO_TOP_THRESHOLD_PX;
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });

    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener('scroll', onScroll);
    };
  });

  const actionsCollapseArgs = $derived<ActionsCollapseArgs>({
    expanded: collapseExpanded,
    toggle: () => onToggleCollapse?.(),
    ariaControls: collapseAriaControls
  });
</script>

<section bind:this={wrapperEl} class={cn(wrapperClass ?? ADMIN_PAGE_MAX_W, className)}>
  <div bind:this={headerEl} class={cn(sticky && ADMIN_PAGE_STICKY_HEADER)}>
    <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div class="min-w-0">
        {#if kicker}
          <p class={ADMIN_HEADER_KICKER}>{kicker}</p>
        {/if}
        <div class="mt-1 flex items-center gap-1.5">
          <h2 class={ADMIN_HEADER_TITLE}>{title}</h2>
          {#if titleAdornment}
            {@render titleAdornment()}
          {/if}
        </div>
        {#if subtitleSlot}
          {@render subtitleSlot()}
        {:else if subtitle}
          <p class={cn(ADMIN_HEADER_INTRO, 'mt-1')}>{subtitle}</p>
        {/if}
      </div>

      {#if tabs || actions || actionsCollapse || (sticky && scrolled && !backToTop)}
        <div class="flex min-w-0 flex-wrap items-center gap-2 md:justify-end">
          {#if tabs}{@render tabs()}{/if}
          {#if actions}{@render actions()}{/if}
          {#if sticky && scrolled}
            {#if backToTop}
              {@render backToTop()}
            {:else}
              <button
                type="button"
                class="inline-flex size-8 items-center justify-center rounded-md border border-input bg-background/70 text-muted-foreground shadow-xs transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Back to top"
                title="Back to top"
                onclick={scrollToTop}
              >
                <ArrowUp size={16} />
              </button>
            {/if}
          {/if}
          {#if actionsCollapse}
            {@render actionsCollapse(actionsCollapseArgs)}
          {/if}
        </div>
      {/if}
    </div>
  </div>

  {#if children}
    {@render children()}
  {/if}
</section>
