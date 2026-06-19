<script lang="ts">
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import Badge from '$lib/components/ui/badge.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import { ADMIN_SECTION_HEADING_LG } from '$lib/styling/admin-tokens';
  import type { MetricsController } from '../state/metrics-controller.svelte';

  type Props = {
    ctrl: MetricsController;
  };

  let { ctrl }: Props = $props();

  const CHANNEL_GRID = 'minmax(180px,1fr) 90px 100px 100px 110px 100px';
</script>

<section class="grid gap-3">
  <h3 class={ADMIN_SECTION_HEADING_LG}>Channel Plugins</h3>
  {#if ctrl.children.length === 0}
    <InlineEmptyState message="No channel plugin processes reported." />
  {:else}
    <AdminTableShell layout="grid" minWidth={760} gridColumns={CHANNEL_GRID}>
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
          <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={CHANNEL_GRID}>
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
    </AdminTableShell>
  {/if}
  <p class="font-sans text-sm text-muted-foreground">{ctrl.frame?.children_total_caption ?? '-'}</p>
</section>
