<script lang="ts">
  import { Link2, Link2Off, PlugZap } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import RefreshableSectionCard from '$lib/features/channels-devices/shared/RefreshableSectionCard.svelte';
  import { humanDateTime } from '$lib/format/human-datetime';
  import type { ExtensionsController } from '../state/extensions-controller.svelte';

  let { ctrl }: { ctrl: ExtensionsController } = $props();

  const GRID = '170px 110px 1.4fr 190px 240px';
</script>

<SectionCard class="grid gap-4">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class="text-lg font-semibold">Add an extension</h3>
      <p class="font-sans text-sm text-muted-foreground">
        Make a short-lived code, then type it with the address into the extension's settings
        (HomeHiro: Settings, HiroLeague).
      </p>
    </div>
    <Button disabled={ctrl.busy} onclick={() => void ctrl.generatePairingCode()}>
      <Link2 size={15} /> Make a pairing code
    </Button>
  </div>
</SectionCard>

<RefreshableSectionCard
  title="Paired extensions"
  countText="{ctrl.connectedCount} of {ctrl.rows.length} connected"
  loading={ctrl.loading}
  error={ctrl.error}
  empty={ctrl.rows.length === 0}
  loadingLabel="Loading extensions…"
  errorTitle="Could not load extensions"
  emptyMessage="No extensions yet. Make a pairing code above to add one."
  onRefresh={() => void ctrl.load()}
>
  <AdminTableShell layout="grid" minWidth={900} gridColumns={GRID} stickyHead>
    {#snippet headRow()}
      <span>Name</span>
      <span>Version</span>
      <span>Status</span>
      <span>Paired</span>
      <span>Actions</span>
    {/snippet}
    {#snippet body()}
      {#each ctrl.rows as row (row.extension_id)}
        <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
          <span class="truncate font-sans text-sm font-semibold" title={row.extension_id}>
            {row.name || row.extension_id.slice(0, 12)}
          </span>
          <span class="truncate font-mono text-xs text-muted-foreground">{row.version || '—'}</span>
          <span class="grid gap-1">
            <span class="flex items-center gap-2">
              {#if row.connected}
                <Badge variant="success">Connected</Badge>
                <span class="truncate text-xs text-muted-foreground" title={row.remote ?? ''}>
                  since {humanDateTime(row.connected_at)}
                </span>
              {:else}
                <Badge variant="secondary">Not connected</Badge>
                <span class="truncate text-xs text-muted-foreground">
                  last seen {humanDateTime(row.last_seen)}
                </span>
              {/if}
            </span>
            {#if ctrl.testResults[row.extension_id]}
              <span class="truncate text-xs text-muted-foreground">{ctrl.testResults[row.extension_id]}</span>
            {/if}
          </span>
          <span class="truncate text-xs text-muted-foreground">{humanDateTime(row.paired_at)}</span>
          <span class="flex justify-end gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={ctrl.busy || !row.connected}
              onclick={() => void ctrl.testCall(row)}
              title="Ask the extension for its name and version"
            >
              <PlugZap size={13} /> Test call
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={ctrl.busy}
              onclick={() => ctrl.openRemove(row)}
              title="Remove extension"
            >
              <Link2Off size={13} /> Remove
            </Button>
          </span>
        </div>
      {/each}
    {/snippet}
  </AdminTableShell>
</RefreshableSectionCard>
