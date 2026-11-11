<script lang="ts">
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import type { MetricsController } from '../state/metrics-controller.svelte';

  type Props = {
    ctrl: MetricsController;
  };

  let { ctrl }: Props = $props();

  const CHANNEL_GRID = 'minmax(180px,1fr) 90px 100px 100px 110px 100px';
</script>

<Panel title="Channel Plugins" contentClass="grid gap-3">
  {#if ctrl.children.length === 0}
    <EmptyState message="No channel plugin processes reported." />
  {:else}
    <TableShell layout="grid" minWidth={760} gridColumns={CHANNEL_GRID}>
      {#snippet headRow()}
        <span>Channel</span>
        <span class="text-center">PID</span>
        <span class="text-center">Status</span>
        <span class="text-right">CPU %</span>
        <span class="text-right">RSS</span>
        <span class="text-right">Threads</span>
      {/snippet}
      {#snippet body()}
        {#each ctrl.children as child (child.name)}
          <div class={TABLE_GRID_ROW} style:grid-template-columns={CHANNEL_GRID}>
            <span class="truncate font-semibold">{child.name}</span>
            <span class="text-center text-muted-foreground">{child.pid}</span>
            <span class="text-center">
              <Badge variant={child.alive === 'running' ? 'success' : 'outline'}>{child.alive}</Badge>
            </span>
            <span class="text-right">{child.cpu}</span>
            <span class="text-right">{child.rss}</span>
            <span class="text-right">{child.threads}</span>
          </div>
        {/each}
      {/snippet}
    </TableShell>
  {/if}
  <p class="font-sans text-sm text-muted-foreground">{ctrl.frame?.children_total_caption ?? '-'}</p>
</Panel>
