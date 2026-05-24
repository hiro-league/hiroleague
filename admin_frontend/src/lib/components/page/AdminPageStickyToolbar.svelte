<script lang="ts">
  /**
   * Second-level sticky toolbar that mounts immediately under a sticky
   * `<AdminPageHeader>`.
   *
   * Reads `--admin-page-header-h` (published by `AdminPageHeader sticky`) and
   * sticks at `top: calc(theme(spacing.16) + var(--admin-page-header-h))`.
   * Also publishes `--admin-page-sticky-toolbar-h` on the page wrapper so
   * `AdminTableShell stickyHead` can align beneath this bar.
   */
  import { onMount, type Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  type Props = {
    /** Optional extra classes appended to the sticky wrapper. */
    class?: string;
    children?: Snippet;
  };

  let { class: className, children }: Props = $props();

  let toolbarEl = $state<HTMLDivElement | null>(null);

  onMount(() => {
    if (!toolbarEl) return;
    const section = toolbarEl.closest('section');
    if (!section) return;

    let publishedHeight = -1;
    const publishHeight = () => {
      if (!toolbarEl) return;
      const h = Math.round(toolbarEl.getBoundingClientRect().height);
      if (h !== publishedHeight) {
        publishedHeight = h;
        section.style.setProperty('--admin-page-sticky-toolbar-h', `${h}px`);
      }
    };

    const resizeObserver =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(publishHeight) : null;
    resizeObserver?.observe(toolbarEl);
    publishHeight();

    return () => {
      resizeObserver?.disconnect();
      section.style.removeProperty('--admin-page-sticky-toolbar-h');
    };
  });
</script>

<div
  bind:this={toolbarEl}
  class={cn(
    'sticky z-10 -mx-4 border-b border-border/70 bg-background/95 px-4 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/85 md:-mx-6 md:px-6',
    className
  )}
  style="top: calc(4rem + var(--admin-page-header-h, 0px));"
>
  {@render children?.()}
</div>
