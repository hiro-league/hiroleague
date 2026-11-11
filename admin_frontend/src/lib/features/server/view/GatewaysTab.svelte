<script lang="ts">
  import ResourceView from '$kit/ui/resource-view.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import { onMount } from 'svelte';
  import { RefreshCw } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { liveStatus } from '$lib/live/status.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import type { Notify } from '$kit/ui/toast.svelte';
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

  const view = $derived({
    data: gateway.rows.length || !(gateway.loading || gateway.error) ? gateway.rows : null,
    error: gateway.error ?? '',
    loading: gateway.loading,
    reload: () => gateway.load()
  });
</script>

<Panel title="Gateways" description={`${gateway.rows.length} configured / ${gateway.runningCount} running`}>
  {#snippet actions()}
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
  {/snippet}
  <ResourceView
    resource={view}
    loadingLabel="Loading gateways…"
    errorTitle="Could not load gateways"
    empty={(d) => d.length === 0}
    emptyMessage="No gateway instances configured yet."
    quiet
  >
    {#snippet children()}
      <TableShell layout="grid" minWidth={880} gridColumns={GATEWAY_GRID}>
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
      </TableShell>
    {/snippet}
  </ResourceView>
</Panel>

<GatewayCreateDialog {gateway} />
<GatewayStopDialog {gateway} />
<GatewayRemoveDialog {gateway} />
