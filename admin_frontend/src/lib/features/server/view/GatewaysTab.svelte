<script lang="ts">
  import { onMount } from 'svelte';
  import { RefreshCw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { liveStatus } from '$lib/live/status.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import type { Notify } from '$lib/ui/toast-types';
  import { createGatewayStore } from '../state/gateway-store.svelte';
  import GatewayRow from './GatewayRow.svelte';
  import GatewayCreateDialog from '../dialogs/GatewayCreateDialog.svelte';
  import GatewayStopDialog from '../dialogs/GatewayStopDialog.svelte';
  import GatewayRemoveDialog from '../dialogs/GatewayRemoveDialog.svelte';

  let { notify }: { notify: Notify } = $props();

  const GATEWAY_GRID = '220px 130px 140px 110px 260px';

  const gateway = createGatewayStore((kind, message) => notify(kind, message));

  onMount(() => {
    gateway.load();
    return liveStatus.subscribe((status) => {
      gateway.applyLiveRows(status.gateways, status.gateways_error);
    });
  });
</script>

<section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class="text-lg font-semibold">Gateways</h3>
      <span class="font-sans text-sm text-muted-foreground">
        {gateway.rows.length} configured / {gateway.runningCount} running
      </span>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button
        class="size-9 px-0"
        variant="outline"
        onclick={() => gateway.load()}
        aria-label="Refresh gateways"
        title="Refresh gateways"
      >
        <RefreshCw size={15} />
      </Button>
      <Button onclick={gateway.openCreate}>Create gateway</Button>
    </div>
  </div>

  {#if gateway.loading}
    <InlineLoading label="Loading gateways…" />
  {:else if gateway.error}
    <InlineDestructiveAlert title="Could not load gateways" message={gateway.error} />
  {:else if gateway.rows.length === 0}
    <InlineEmptyState message="No gateway instances configured yet." />
  {:else}
    <AdminTableShell layout="grid" minWidth={880} gridColumns={GATEWAY_GRID}>
      {#snippet headRow()}
        <span>Name</span>
        <span>Status</span>
        <span>Host : Port</span>
        <span>Autostart</span>
        <span>Actions</span>
      {/snippet}
      {#snippet body()}
        {#each gateway.rows as row (row.name)}
          <GatewayRow {row} {gateway} grid={GATEWAY_GRID} />
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</section>

<GatewayCreateDialog {gateway} />
<GatewayStopDialog {gateway} />
<GatewayRemoveDialog {gateway} />
