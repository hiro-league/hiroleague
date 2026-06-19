<script lang="ts">
  import { Lock, Power, PowerOff } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import type { ChannelsController } from '../state/channels-controller.svelte';
  import RefreshableSectionCard from '../shared/RefreshableSectionCard.svelte';

  let { ctrl }: { ctrl: ChannelsController } = $props();

  const CHANNEL_GRID = '180px 120px 1.5fr 1fr 140px';
</script>

<RefreshableSectionCard
  title="Channels"
  countText="{ctrl.rows.length} configured / {ctrl.enabledCount} enabled"
  loading={ctrl.loading}
  error={ctrl.error}
  empty={ctrl.rows.length === 0}
  loadingLabel="Loading channels…"
  errorTitle="Could not load channels"
  emptyMessage="No channels configured for this workspace."
  onRefresh={() => void ctrl.load()}
>
  <AdminTableShell layout="grid" minWidth={920} gridColumns={CHANNEL_GRID}>
    {#snippet headRow()}
      <span>Name</span>
      <span>Status</span>
      <span>Command</span>
      <span>Config keys</span>
      <span>Actions</span>
    {/snippet}
    {#snippet body()}
      {#each ctrl.rows as row (row.name)}
        <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={CHANNEL_GRID}>
          <span class="truncate font-sans text-sm font-semibold" title={row.name}>{row.name}</span>
          <span>
            <Badge variant={row.enabled ? 'success' : 'outline'}>
              {row.enabled ? 'Enabled' : 'Disabled'}
            </Badge>
          </span>
          <span class="truncate font-mono text-xs text-muted-foreground" title={row.command}>
            {row.command || '-'}
          </span>
          <span class="flex flex-wrap gap-1.5">
            {#if row.config_keys.length}
              {#each row.config_keys as key}
                <Badge variant="secondary">{key}</Badge>
              {/each}
            {:else}
              <small class="text-muted-foreground">-</small>
            {/if}
          </span>
          <span class="flex justify-end">
            {#if ctrl.isMandatory(row)}
              <Button
                size="icon"
                variant="ghost"
                class="opacity-45"
                disabled
                aria-label="Mandatory channel cannot be disabled"
                title="Mandatory channel cannot be disabled"
              >
                <Lock size={15} />
              </Button>
            {:else}
              {@const ToggleIcon = row.enabled ? PowerOff : Power}
              {@const toggleLabel = row.enabled ? 'Disable' : 'Enable'}
              {@const toggleTitle = row.enabled ? 'Disable channel' : 'Enable channel'}
              <Button
                size="sm"
                variant="outline"
                disabled={ctrl.isBusy(row)}
                onclick={() => void ctrl.toggle(row)}
                title={toggleTitle}
              >
                <ToggleIcon size={13} /> {toggleLabel}
              </Button>
            {/if}
          </span>
        </div>
      {/each}
    {/snippet}
  </AdminTableShell>
</RefreshableSectionCard>
