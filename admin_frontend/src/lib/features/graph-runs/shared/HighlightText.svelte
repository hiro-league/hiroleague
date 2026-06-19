<script lang="ts">
  import { splitHighlight } from './retrieval-trace-derive';

  // Renders plain text with the active search query <mark>-ed wherever it appears. Splits on the
  // query (never {@html}, so it stays injection-safe) — the single home for the `.search-hit`
  // style, shared by the retrieval dialog's inline highlights and <ClampCell>.
  let { text, query }: { text: string | null | undefined; query: string } = $props();
</script>

{#each splitHighlight(text, query) as seg, i (i)}{#if seg.hit}<mark class="search-hit">{seg.text}</mark>{:else}{seg.text}{/if}{/each}

<style>
  /* Search matches — yellow-ish, theme-aware, readable on hovered rows. */
  .search-hit {
    background: color-mix(in srgb, #facc15 55%, transparent);
    color: inherit;
    border-radius: 2px;
    padding: 0 1px;
  }
</style>
