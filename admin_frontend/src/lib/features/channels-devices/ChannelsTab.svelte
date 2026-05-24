<script lang="ts">
  import { Lock, Power, PowerOff, RefreshCw } from '@lucide/svelte';
  import {
    disableChannel,
    enableChannel,
    listChannels,
    type ChannelRow
  } from '$lib/api/channels-devices';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import type { Notify } from './types';

  let { notify }: { notify: Notify } = $props();

  let rows = $state<ChannelRow[]>([]);
  let mandatoryChannelName = $state('');
  let loading = $state(true);
  let busyChannel = $state<string | null>(null);
  let error = $state<string | null>(null);

  const enabledCount = $derived(rows.filter((row) => row.enabled).length);

  async function load() {
    loading = true;
    error = null;
    try {
      const payload = await listChannels();
      rows = payload.data.channels;
      mandatoryChannelName = payload.data.mandatory_channel_name;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load channels.';
    } finally {
      loading = false;
    }
  }

  async function toggle(row: ChannelRow) {
    busyChannel = row.name;
    try {
      const result = row.enabled ? await disableChannel(row.name) : await enableChannel(row.name);
      notify('success', result.data ?? `Channel '${row.name}' ${row.enabled ? 'disabled' : 'enabled'}.`);
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Channel update failed.');
    } finally {
      busyChannel = null;
    }
  }

  load();

  const CHANNEL_GRID = '180px 120px 1.5fr 1fr 140px';
</script>

<section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class="text-lg font-semibold">Channels</h3>
      <span class="font-sans text-sm text-muted-foreground">
        {rows.length} configured / {enabledCount} enabled
      </span>
    </div>
    <Button variant="outline" onclick={load}><RefreshCw size={15} /> Refresh</Button>
  </div>

  {#if loading}
    <InlineLoading label="Loading channels…" />
  {:else if error}
    <InlineDestructiveAlert title="Could not load channels" message={error} />
  {:else if rows.length === 0}
    <InlineEmptyState message="No channels configured for this workspace." />
  {:else}
    <AdminTableShell layout="grid" minWidth={920} gridColumns={CHANNEL_GRID}>
      {#snippet headRow()}
        <span>Name</span>
        <span>Status</span>
        <span>Command</span>
        <span>Config keys</span>
        <span>Actions</span>
      {/snippet}
      {#snippet body()}
        {#each rows as row (row.name)}
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
              {#if row.name === mandatoryChannelName}
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
              {:else if row.enabled}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyChannel === row.name}
                  onclick={() => toggle(row)}
                  title="Disable channel"
                >
                  <PowerOff size={13} /> Disable
                </Button>
              {:else}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyChannel === row.name}
                  onclick={() => toggle(row)}
                  title="Enable channel"
                >
                  <Power size={13} /> Enable
                </Button>
              {/if}
            </span>
          </div>
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</section>
