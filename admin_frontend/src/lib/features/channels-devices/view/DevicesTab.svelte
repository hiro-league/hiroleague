<script lang="ts">
  import { Link2, Link2Off } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import DevicePairingDialog from '../dialogs/DevicePairingDialog.svelte';
  import DeviceRevokeDialog from '../dialogs/DeviceRevokeDialog.svelte';
  import { formatDeviceTimestamp } from '../shared/channels-devices-format';
  import type { DevicesController } from '../state/devices-controller.svelte';
  import RefreshableSectionCard from '../shared/RefreshableSectionCard.svelte';

  let { ctrl }: { ctrl: DevicesController } = $props();

  const DEVICE_GRID = '180px 1.5fr 190px 190px 110px';
</script>

<section class="grid gap-4">
  <SectionCard class="grid gap-4">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <h3 class="text-lg font-semibold">Pair new device</h3>
        <p class="font-sans text-sm text-muted-foreground">
          Generate a short-lived code and enter it on your mobile device to authorize it.
        </p>
      </div>
      <Button disabled={ctrl.busy} onclick={() => void ctrl.generatePairingCode()}>
        <Link2 size={15} /> Generate pairing code
      </Button>
    </div>
  </SectionCard>

  <RefreshableSectionCard
    title="Approved devices"
    countText="{ctrl.rows.length} paired"
    loading={ctrl.loading}
    error={ctrl.error}
    empty={ctrl.rows.length === 0}
    loadingLabel="Loading devices…"
    errorTitle="Could not load devices"
    emptyMessage="No paired devices. Use the button above to generate a pairing code."
    onRefresh={() => void ctrl.load()}
  >
    <AdminTableShell layout="grid" minWidth={920} gridColumns={DEVICE_GRID} stickyHead>
      {#snippet headRow()}
        <span>Name</span>
        <span>Device ID</span>
        <span>Paired</span>
        <span>Expires</span>
        <span>Actions</span>
      {/snippet}
      {#snippet body()}
        {#each ctrl.rows as row (row.device_id)}
          <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={DEVICE_GRID}>
            <span class="truncate font-sans text-sm font-semibold" title={row.device_name ?? ''}>
              {row.device_name || '-'}
            </span>
            <span class="truncate font-mono text-xs text-muted-foreground" title={row.device_id}>
              {row.device_id}
            </span>
            <span class="truncate text-xs text-muted-foreground">
              {formatDeviceTimestamp(row.paired_at)}
            </span>
            <span class="truncate text-xs text-muted-foreground">
              {formatDeviceTimestamp(row.expires_at)}
            </span>
            <span class="flex justify-end">
              <Button
                size="sm"
                variant="destructive"
                disabled={ctrl.busy}
                onclick={() => ctrl.openRevoke(row)}
                title="Revoke device"
              >
                <Link2Off size={13} /> Revoke
              </Button>
            </span>
          </div>
        {/each}
      {/snippet}
    </AdminTableShell>
  </RefreshableSectionCard>
</section>

<DevicePairingDialog {ctrl} />
<DeviceRevokeDialog {ctrl} />
