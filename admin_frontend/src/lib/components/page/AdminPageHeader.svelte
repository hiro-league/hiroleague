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
   *  - `subnav`         — full-width second-level strip rendered inside the sticky
   *    region below the title/tabs row (e.g. a per-record subtab strip). Pins with
   *    the header; its height folds into `--admin-page-header-h` automatically.
   *  - `actions`        — trailing buttons / link actions.
   *  - `actionsCollapse({ expanded, toggle, ariaControls })` — optional chevron
   *    toggle that collapses a secondary region elsewhere on the page; receives
   *    the wired state/handler so the page does not have to thread three props.
   *  - `backToTop`      — overrides the auto-generated "back to top" affordance
   *    that appears in the action row when `sticky` is set and the page has
   *    scrolled past `BACK_TO_TOP_THRESHOLD_PX`.
   *
   * Sticky mode (`sticky` prop):
   *  - Adds sticky header classes so the bar pins under the shell.
   *  - Compacts on scroll with hysteresis (avoids flicker at the stick threshold).
   *  - Frosted background only while pinned; expanded layout at page top.
   *  - Measures itself with `ResizeObserver` and publishes `--admin-page-header-h`
   *    on the wrapper so a sibling `<AdminPageStickyToolbar>` can mount at
   *    `top: calc(theme(spacing.16) + var(--admin-page-header-h))`. No magic
   *    pixel constants live on consumers.
   */
  import { onMount, type Snippet } from 'svelte';
  import { cubicInOut, cubicOut } from 'svelte/easing';
  import { crossfade, slide } from 'svelte/transition';
  import { ArrowUp } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import {
    ADMIN_HEADER_BREADCRUMB_SEP,
    ADMIN_HEADER_INTRO,
    ADMIN_HEADER_KICKER,
    ADMIN_HEADER_KICKER_COMPACT,
    ADMIN_HEADER_TITLE,
    ADMIN_HEADER_TITLE_COMPACT,
    ADMIN_PAGE_MAX_W,
    ADMIN_PAGE_STICKY_HEADER_PINNED,
    ADMIN_PAGE_STICKY_HEADER_POSITION
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
    /**
     * Force the compact/pinned layout regardless of scroll position. Used when a
     * tab wants the header out of the way by default (e.g. Knowledge → Graph,
     * which fills the content area with the canvas). Implies `sticky` styling.
     */
    forceCompact?: boolean;
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
    subnav?: Snippet;
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
    forceCompact = false,
    class: className,
    wrapperClass,
    collapseExpanded = true,
    onToggleCollapse,
    collapseAriaControls,
    titleAdornment,
    subtitleSlot,
    tabs,
    subnav,
    actions,
    actionsCollapse,
    backToTop,
    children
  }: Props = $props();

  let headerEl = $state<HTMLDivElement | null>(null);
  let wrapperEl = $state<HTMLElement | null>(null);
  let pinned = $state(false);
  let scrolled = $state(false);

  /**
   * Hysteresis band for pinned/compact mode. Without it, toggling layout at the
   * sticky threshold shifts document height and scrollY, causing flicker.
   */
  const PINNED_ENTER_SCROLL_Y = 80;
  const PINNED_EXIT_SCROLL_Y = 4;
  const BACK_TO_TOP_THRESHOLD_PX = 480;

  const TITLE_MORPH_MS = 280;
  const SUBTITLE_SLIDE_MS = 220;

  /**
   * Shared-element morph between the expanded (stacked) and compact (inline)
   * title layouts. Each tagged element fades + transforms from its old
   * position/size to the new one so the kicker/title appear to glide rather
   * than crossfade.
   */
  const [sendTitle, receiveTitle] = crossfade({
    duration: TITLE_MORPH_MS,
    easing: cubicInOut,
    fallback(node) {
      const transform = getComputedStyle(node).transform;
      return {
        duration: TITLE_MORPH_MS,
        easing: cubicOut,
        css: (t) =>
          `transform: ${transform === 'none' ? '' : transform} translateY(${(1 - t) * 4}px); opacity: ${t};`
      };
    }
  });

  function scrollToTop() {
    if (typeof window === 'undefined') return;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function updateScrollState() {
    const y = window.scrollY;
    if (y >= PINNED_ENTER_SCROLL_Y) {
      pinned = true;
    } else if (y <= PINNED_EXIT_SCROLL_Y) {
      pinned = false;
    }
    scrolled = y > BACK_TO_TOP_THRESHOLD_PX;
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

    const onScroll = () => updateScrollState();
    updateScrollState();
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

  // `forceCompact` pins the header without any scrolling (used by Graph tab).
  const compact = $derived(pinned || forceCompact);
  const showCompactTitle = $derived(sticky && compact);
</script>

<section bind:this={wrapperEl} class={cn(wrapperClass ?? ADMIN_PAGE_MAX_W, className)}>
  <div
    bind:this={headerEl}
    class={cn(
      sticky && ADMIN_PAGE_STICKY_HEADER_POSITION,
      sticky && compact && ADMIN_PAGE_STICKY_HEADER_PINNED
    )}
  >
    <div
      class={cn(
        'flex flex-col gap-4 transition-[gap] duration-200 ease-out md:flex-row md:justify-between',
        showCompactTitle ? 'md:items-center' : 'md:items-end'
      )}
    >
      <div class="grid min-w-0 [&>*]:col-start-1 [&>*]:row-start-1">
        {#if showCompactTitle}
          <div class="flex min-w-0 items-center gap-2">
            {#if kicker}
              <span
                class={ADMIN_HEADER_KICKER_COMPACT}
                in:receiveTitle={{ key: 'kicker' }}
                out:sendTitle={{ key: 'kicker' }}
              >{kicker}</span>
              <span
                class={ADMIN_HEADER_BREADCRUMB_SEP}
                aria-hidden="true"
                in:receiveTitle={{ key: 'sep' }}
                out:sendTitle={{ key: 'sep' }}
              >/</span>
            {/if}
            <h2
              class={ADMIN_HEADER_TITLE_COMPACT}
              in:receiveTitle={{ key: 'title' }}
              out:sendTitle={{ key: 'title' }}
            >{title}</h2>
            {#if titleAdornment}
              <span in:receiveTitle={{ key: 'adornment' }} out:sendTitle={{ key: 'adornment' }}>
                {@render titleAdornment()}
              </span>
            {/if}
          </div>
        {:else}
          <div class="min-w-0">
            {#if kicker}
              <p
                class={ADMIN_HEADER_KICKER}
                in:receiveTitle={{ key: 'kicker' }}
                out:sendTitle={{ key: 'kicker' }}
              >{kicker}</p>
            {/if}
            <div class="mt-1 flex items-center gap-1.5">
              <h2
                class={ADMIN_HEADER_TITLE}
                in:receiveTitle={{ key: 'title' }}
                out:sendTitle={{ key: 'title' }}
              >{title}</h2>
              {#if titleAdornment}
                <span in:receiveTitle={{ key: 'adornment' }} out:sendTitle={{ key: 'adornment' }}>
                  {@render titleAdornment()}
                </span>
              {/if}
            </div>
            {#if subtitleSlot}
              <div transition:slide={{ duration: SUBTITLE_SLIDE_MS, easing: cubicInOut }}>
                {@render subtitleSlot()}
              </div>
            {:else if subtitle}
              <p
                class={cn(ADMIN_HEADER_INTRO, 'mt-1')}
                transition:slide={{ duration: SUBTITLE_SLIDE_MS, easing: cubicInOut }}
              >{subtitle}</p>
            {/if}
          </div>
        {/if}
      </div>

      {#if tabs || actions || actionsCollapse || (sticky && scrolled)}
        <div
          class={cn(
            'flex min-w-0 flex-wrap items-center gap-2 md:justify-end',
            showCompactTitle && 'gap-1.5'
          )}
        >
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
          {#if tabs}{@render tabs()}{/if}
          {#if actions}{@render actions()}{/if}
          {#if actionsCollapse}
            {@render actionsCollapse(actionsCollapseArgs)}
          {/if}
        </div>
      {/if}
    </div>

    {#if subnav}
      <!-- Second-level strip inside the sticky region: pins with the header and its
           height folds into --admin-page-header-h via the ResizeObserver above.
           Tight top margin keeps the pinned chrome compact. -->
      <div class="mt-1">{@render subnav()}</div>
    {/if}
  </div>

  {#if children}
    {@render children()}
  {/if}
</section>
