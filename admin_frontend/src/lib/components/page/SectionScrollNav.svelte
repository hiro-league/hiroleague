<script lang="ts" generics="TId extends string">
  /**
   * Inner section scroll-spy navigation (Preferences-style).
   *
   * **Not** a page-level tab strip. This is the in-page pill row that
   * highlights which `<section id="…">` is currently under the marker line
   * and supports `#hash` deep-links. See
   * `docs/admin-frontend-refactor-plan.md` §2.3.
   *
   * Phase 1 ships the contract; Preferences is the first consumer (Phase 4).
   * Promoted to `lib/components/page/` from day one so the API is settled
   * before adoption; until a second consumer appears it stays the only user.
   */
  import { onMount } from 'svelte';
  import { cn } from '$lib/utils';
  import { cnAdminTab } from '$lib/styling/admin-tokens';

  type Section<I extends string> = { id: I; label: string };

  type Props = {
    ariaLabel: string;
    sections: readonly Section<TId>[];
    /**
     * Pixel offset from the top of the viewport where the "active section"
     * marker line sits. Defaults to 128px (shell header 64 + a little).
     */
    scrollMarkerPx?: number;
    /** Optional extra classes appended to the wrapper. */
    class?: string;
    /** Smooth-scroll behaviour when a pill is clicked or a hash arrives. */
    scrollBehavior?: ScrollBehavior;
  };

  let {
    ariaLabel,
    sections,
    scrollMarkerPx = 128,
    class: className,
    scrollBehavior = 'smooth'
  }: Props = $props();

  let activeId = $state<TId | null>(null);

  function scrollToSection(id: TId, replaceHash = true) {
    if (typeof window === 'undefined') return;
    const el = document.getElementById(id);
    if (!el) return;
    const top = el.getBoundingClientRect().top + window.scrollY - scrollMarkerPx + 1;
    window.scrollTo({ top, behavior: scrollBehavior });
    if (replaceHash) {
      const url = new URL(window.location.href);
      url.hash = id;
      window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    }
  }

  function computeActiveSection() {
    if (typeof window === 'undefined') return;
    let next: TId | null = activeId;
    for (const section of sections) {
      const el = document.getElementById(section.id);
      if (!el) continue;
      const top = el.getBoundingClientRect().top;
      if (top - scrollMarkerPx <= 0) {
        next = section.id;
      } else {
        break;
      }
    }
    if (next !== activeId) {
      activeId = next;
    }
  }

  onMount(() => {
    activeId = sections[0]?.id ?? null;
    const hash = window.location.hash.slice(1);
    if (hash) {
      const match = sections.find((s) => s.id === hash);
      if (match) {
        activeId = match.id as TId;
        requestAnimationFrame(() => scrollToSection(match.id as TId, false));
      }
    }

    computeActiveSection();
    const onScroll = () => computeActiveSection();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);

    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  });
</script>

<nav
  class={cn('inline-flex flex-wrap gap-1 rounded-lg border bg-card p-1', className)}
  aria-label={ariaLabel}
>
  {#each sections as section (section.id)}
    {@const isActive = section.id === activeId}
    <a
      class={cn(
        'inline-flex items-center justify-center rounded-md px-3 py-1.5 font-sans text-sm font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
        isActive ? 'bg-secondary text-secondary-foreground shadow-xs hover:bg-secondary/80' : '',
        cnAdminTab(isActive)
      )}
      href={`#${section.id}`}
      aria-current={isActive ? 'true' : undefined}
      onclick={(event) => {
        event.preventDefault();
        scrollToSection(section.id);
      }}
    >
      {section.label}
    </a>
  {/each}
</nav>
