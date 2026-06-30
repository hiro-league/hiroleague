<script lang="ts">
  /**
   * Settings search box for the sticky toolbar (rendered just before the "show advanced" toggle).
   * Dumb/presentational: the page owns the search controller and wires these callbacks. While there
   * are unsaved edits the box is `disabled` (search is clean-only) — the page also clears the query.
   *
   * Shows an autocomplete dropdown of matches (each row: field title + "Tab › Section") so a specific
   * control can be picked directly; the n/N indicator + prev/next arrows step through the same list.
   */
  import { ChevronLeft, ChevronRight, Search, X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';
  import type { PrefSearchEntry } from '$lib/features/preferences/shared/preferences-search-index';

  type Props = {
    query: string;
    disabled?: boolean;
    /** 1-based position of the active match (0 when none). */
    position: number;
    total: number;
    /** Ordered match list backing the dropdown + arrows. */
    matches: readonly PrefSearchEntry[];
    /** Dotted path of the currently-active match (marks its row). */
    activePath: string | null;
    /** Current value of a field, formatted for the dropdown's second line ("--" when unset). */
    valueFor: (entry: PrefSearchEntry) => string;
    onQuery: (next: string) => void;
    onPrev: () => void;
    onNext: () => void;
    /** Jump to a specific match by its index in `matches`. */
    onPick: (index: number) => void;
    onClear: () => void;
  };

  let {
    query,
    disabled = false,
    position,
    total,
    matches,
    activePath,
    valueFor,
    onQuery,
    onPrev,
    onNext,
    onPick,
    onClear
  }: Props = $props();

  let focused = $state(false);
  // Set by Esc to hide the dropdown without clearing the query; reset on the next keystroke.
  let dismissed = $state(false);
  // Keyboard cursor within the dropdown (-1 = none; Enter then steps via arrows instead of picking).
  let highlighted = $state(-1);
  // Bound to the dropdown <ul> so we can scroll the active row into view when the list opens.
  let listEl = $state<HTMLUListElement | null>(null);

  const open = $derived(focused && !dismissed && query.trim() !== '' && matches.length > 0);

  // When the dropdown opens (e.g. clicking back into a box that already has a query), the active
  // match may be far down the list — scroll it into view inside the dropdown so it's not hidden.
  // Scrolls only the list container (manual scrollTop), never the page.
  $effect(() => {
    if (!open || !listEl) return;
    // Re-run when the active row changes (e.g. arrowing while the list is open).
    activePath;
    const row = listEl.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!row) return;
    const top = row.offsetTop;
    const bottom = top + row.offsetHeight;
    if (top < listEl.scrollTop) listEl.scrollTop = top;
    else if (bottom > listEl.scrollTop + listEl.clientHeight) {
      listEl.scrollTop = bottom - listEl.clientHeight;
    }
  });

  function pick(index: number) {
    onPick(index);
    dismissed = true; // collapse after choosing; typing/arrowing reopens
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      dismissed = false;
      highlighted = Math.min(highlighted + 1, matches.length - 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      highlighted = Math.max(highlighted - 1, -1);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (open && highlighted >= 0) pick(highlighted);
      else if (event.shiftKey) onPrev();
      else onNext();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      if (open) dismissed = true;
      else onClear();
    }
  }
</script>

<div class="relative flex items-center gap-1 pb-1">
  <div class="relative">
    <Search
      size={15}
      class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
      aria-hidden="true"
    />
    <!-- type=text (not search) so the browser's native clear "×" doesn't duplicate our own. -->
    <input
      type="text"
      value={query}
      {disabled}
      placeholder="Search settings…"
      title={disabled ? 'Save or reset your changes to search' : undefined}
      aria-label="Search settings"
      autocomplete="off"
      class="h-9 w-44 rounded-md border border-input bg-background py-1.5 pl-8 pr-7 font-sans text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 sm:w-56"
      oninput={(event) => {
        dismissed = false;
        highlighted = -1;
        onQuery(event.currentTarget.value);
      }}
      onfocus={() => {
        focused = true;
        dismissed = false; // re-open the list when returning to a box that already has a term
      }}
      onclick={() => (dismissed = false)}
      onblur={() => (focused = false)}
      onkeydown={onKeydown}
    />
    {#if query && !disabled}
      <button
        type="button"
        class="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
        aria-label="Clear search"
        onclick={onClear}
      >
        <X size={14} aria-hidden="true" />
      </button>
    {/if}
  </div>

  {#if query.trim() && !disabled}
    {#if total > 0}
      <span class="min-w-[2.5rem] text-center font-sans text-xs tabular-nums text-muted-foreground">
        {position}/{total}
      </span>
      <Button
        variant="ghost"
        size="icon"
        class="size-7 text-muted-foreground hover:text-foreground"
        type="button"
        aria-label="Previous result"
        title="Previous result (Shift+Enter)"
        onclick={onPrev}
      >
        <ChevronLeft size={16} aria-hidden="true" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="size-7 text-muted-foreground hover:text-foreground"
        type="button"
        aria-label="Next result"
        title="Next result (Enter)"
        onclick={onNext}
      >
        <ChevronRight size={16} aria-hidden="true" />
      </Button>
    {:else}
      <span class="font-sans text-xs text-muted-foreground">No matches</span>
    {/if}
  {/if}

  {#if open}
    <!-- Anchored under the input. mousedown is prevented so clicking a row doesn't blur the input
         (which would close the list before the click registers). -->
    <ul
      bind:this={listEl}
      class="absolute left-0 top-full z-50 mt-1 max-h-80 w-[22rem] max-w-[80vw] overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-lg"
      role="listbox"
      aria-label="Search results"
      onmousedown={(event) => event.preventDefault()}
    >
      {#each matches as match, index (match.path)}
        {#if index === 0 || matches[index - 1].tabLabel !== match.tabLabel}
          <!-- Tab group header — accent-colored bar to separate groups. -->
          <li
            class="mt-1 rounded bg-primary/10 px-2.5 py-1 font-sans text-[0.7rem] font-semibold uppercase tracking-wider text-primary first:mt-0"
            aria-hidden="true"
          >
            {match.tabLabel}
          </li>
        {/if}
        <li>
          <button
            type="button"
            role="option"
            aria-selected={match.path === activePath}
            class={cn(
              'flex w-full flex-col gap-0.5 rounded px-2.5 py-1.5 text-left transition-colors',
              index === highlighted ? 'bg-accent' : 'hover:bg-accent/60',
              match.path === activePath && 'ring-1 ring-inset ring-primary/50'
            )}
            onclick={() => pick(index)}
            onmouseenter={() => (highlighted = index)}
          >
            <span class="flex w-full items-baseline gap-1 truncate font-sans">
              {#if match.section}
                <span class="shrink-0 text-xs text-muted-foreground">{match.section} ›</span>
              {/if}
              <span class="truncate text-sm font-medium text-foreground">{match.title}</span>
            </span>
            <span class="truncate font-sans text-xs text-muted-foreground">{valueFor(match)}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>
