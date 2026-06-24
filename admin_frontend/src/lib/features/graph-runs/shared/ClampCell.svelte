<script lang="ts">
  import { ChevronDown, ChevronUp } from '@lucide/svelte';
  import Highlight from '$lib/search/Highlight.svelte';

  // A potentially-long table cell (entity summary / episode content) clamped to 3 lines with a
  // more/less toggle, search matches still highlighted. Owns its own open state — the retrieval
  // dialog no longer tracks a keyed set of expanded cells.
  let { text, query }: { text: string; query: string } = $props();

  let open = $state(false);

  // Only offer the toggle when the text is long enough to actually clamp (~3 lines); short
  // summaries render in full with no dangling control.
  const isLong = $derived((text?.length ?? 0) > 140);
</script>

<div class="clamp" class:clamp--open={open}><Highlight {text} {query} /></div>
{#if isLong}
  <button type="button" class="clamp-toggle" onclick={() => (open = !open)}>
    {#if open}<ChevronUp size={11} aria-hidden="true" />less{:else}<ChevronDown size={11} aria-hidden="true" />more{/if}
  </button>
{/if}

<style>
  /* Long entity summaries / episode content: clamp to 3 lines until the user expands them. */
  .clamp {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    overflow: hidden;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .clamp--open {
    display: block;
    -webkit-line-clamp: unset;
    line-clamp: unset;
    overflow: visible;
  }

  .clamp-toggle {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    margin-top: 2px;
    padding: 0;
    appearance: none;
    border: none;
    background: transparent;
    font-size: 10px;
    font-weight: 600;
    color: var(--primary);
    cursor: pointer;
  }

  .clamp-toggle:hover {
    text-decoration: underline;
  }
</style>
