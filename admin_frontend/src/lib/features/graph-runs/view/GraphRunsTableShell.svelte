<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    class: className = '',
    children
  }: {
    class?: string;
    children: Snippet;
  } = $props();
</script>

<div class="gr-table-shell {className}">
  {@render children()}
</div>

<style>
  /* Shared dense admin table chrome for graph-runs ledger + memories lists (avoid duplicating across panels). */
  .gr-table-shell {
    overflow: auto;
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 8px;
  }

  .gr-table-shell :global(table) {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    white-space: nowrap;
  }

  .gr-table-shell :global(th),
  .gr-table-shell :global(td) {
    border-bottom: 1px solid var(--border, #e4e4e7);
    padding: 8px 10px;
    text-align: left;
  }

  .gr-table-shell :global(th) {
    position: sticky;
    top: 0;
    background: var(--background, #fff);
    z-index: 1;
  }
</style>
