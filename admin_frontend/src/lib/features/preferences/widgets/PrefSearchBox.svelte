<script lang="ts">
  /**
   * Settings search box for the sticky toolbar (rendered just before the "show advanced" toggle).
   * Dumb/presentational: the page owns the search controller and wires these callbacks. While there
   * are unsaved edits the box is `disabled` (search is clean-only) — the page also clears the query.
   * The n/N indicator + prev/next arrows appear only when the query has matches.
   */
  import { ChevronLeft, ChevronRight, Search, X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';

  type Props = {
    query: string;
    disabled?: boolean;
    /** 1-based position of the active match (0 when none). */
    position: number;
    total: number;
    onQuery: (next: string) => void;
    onPrev: () => void;
    onNext: () => void;
    onClear: () => void;
  };

  let { query, disabled = false, position, total, onQuery, onPrev, onNext, onClear }: Props =
    $props();

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (event.shiftKey) onPrev();
      else onNext();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      onClear();
    }
  }
</script>

<div class="flex items-center gap-1 pb-1">
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
      class="h-9 w-44 rounded-md border border-input bg-background py-1.5 pl-8 pr-7 font-sans text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 sm:w-56"
      oninput={(event) => onQuery(event.currentTarget.value)}
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
</div>
