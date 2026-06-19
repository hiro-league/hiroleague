<script lang="ts">
  import type { MemoryEntities } from './shared/memory-pure';

  let { entities }: { entities: MemoryEntities } = $props();
</script>

<td class="memories-entities-cell">
  {#if entities && entities.kind === 'relation'}
    <span class="memories-entity">{entities.source}</span>
    {#if entities.relation}
      <span class="memories-rel">—[{entities.relation}]→</span>
    {:else}
      <span class="memories-rel">→</span>
    {/if}
    <span class="memories-entity">{entities.target}</span>
  {:else if entities && entities.kind === 'summary'}
    <span class="memories-entity">{entities.entity || '—'}</span>
    {#if entities.type}
      <span class="memories-rel">({entities.type})</span>
    {/if}
  {:else}
    —
  {/if}
</td>

<style>
  .memories-entities-cell {
    max-width: 260px;
    white-space: normal;
    word-break: break-word;
    line-height: 1.4;
  }

  .memories-entity {
    font-weight: 600;
  }

  .memories-rel {
    margin: 0 4px;
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 11px;
    color: var(--muted-foreground, #64748b);
  }
</style>
