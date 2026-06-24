<script lang="ts">
  import { splitOnQuery } from './match';

  // Plain-text search highlight — splits on the query (never {@html}) so content stays injection-safe.
  let { text, query }: { text: string | null | undefined; query: string } = $props();
</script>

{#each splitOnQuery(text, query) as s, i (i)}{#if s.hit}<mark class="search-hit">{s.text}</mark>{:else}{s.text}{/if}{/each}

<style>
  .search-hit {
    background: color-mix(in srgb, #facc15 55%, transparent);
    color: inherit;
    border-radius: 2px;
    padding: 0 1px;
  }
</style>
