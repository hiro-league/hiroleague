<script lang="ts">
  import GraphDetailConnectionRow from './GraphDetailConnectionRow.svelte';

  type ConnRow = {
    navKind: 'node' | 'edge';
    navId: string;
    title: string;
    subtitle: string;
    invalid: boolean;
    entityType: string | null;
  };

  let {
    search,
    connections,
    filteredConnections,
    onNavigate,
    onPreview
  }: {
    search: string;
    connections: ConnRow[];
    filteredConnections: ConnRow[];
    onNavigate: (sel: { kind: 'node' | 'edge'; id: string }) => void;
    onPreview: (sel: { kind: 'node' | 'edge'; id: string } | null) => void;
  } = $props();
</script>

{#if connections.length === 0}
  <p class="text-xs text-muted-foreground">No connections.</p>
{:else if filteredConnections.length === 0}
  <p class="text-xs text-muted-foreground">No connections match “{search.trim()}”.</p>
{:else}
  <div class="space-y-1">
    {#each filteredConnections as c (c.navId)}
      <GraphDetailConnectionRow row={c} {search} {onNavigate} {onPreview} />
    {/each}
  </div>
{/if}
