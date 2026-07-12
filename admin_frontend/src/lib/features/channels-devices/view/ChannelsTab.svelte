<script lang="ts">
  import { Lock, Power, PowerOff, Settings2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import type { Notify } from '$lib/ui/toast-types';
  import type { ChannelsController } from '../state/channels-controller.svelte';
  import RefreshableSectionCard from '../shared/RefreshableSectionCard.svelte';
  import ChannelDetail from './ChannelDetail.svelte';

  let { ctrl, notify }: { ctrl: ChannelsController; notify: Notify } = $props();

  // Which channel's generic detail view (§5.5) is open; null = the list.
  let selected = $state<string | null>(null);

  const CHANNEL_GRID = '180px 110px 1.4fr 1fr 210px';
</script>

{#if selected}
  {#key selected}
    <ChannelDetail
      name={selected}
      {notify}
      onBack={() => (selected = null)}
      onChanged={() => void ctrl.load()}
    />
  {/key}
{:else}
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
          <span class="flex justify-end gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onclick={() => (selected = row.name)}
              title="Manage channel"
            >
              <Settings2 size={13} /> Manage
            </Button>
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
              {@const toggleTitle = row.enabled ? 'Disable channel' : 'Enable channel'}
              <Button
                size="icon"
                variant="ghost"
                disabled={ctrl.isBusy(row)}
                onclick={() => void ctrl.toggle(row)}
                title={toggleTitle}
                aria-label={toggleTitle}
              >
                <ToggleIcon size={15} />
              </Button>
            {/if}
          </span>
        </div>
      {/each}
    {/snippet}
  </AdminTableShell>
</RefreshableSectionCard>
{/if}
