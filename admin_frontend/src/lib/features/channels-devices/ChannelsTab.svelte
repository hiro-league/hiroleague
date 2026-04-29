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
    <p class="text-muted-foreground">Loading channels...</p>
  {:else if error}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
      <strong class="font-sans">Could not load channels</strong>
      <span class="block text-sm">{error}</span>
    </div>
  {:else if rows.length === 0}
    <p class="text-muted-foreground">No channels configured for this workspace.</p>
  {:else}
    <div class="overflow-x-auto rounded-md border">
      <div class="min-w-[920px]">
        <div
          class="grid grid-cols-[180px_120px_1.5fr_1fr_140px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground"
        >
          <span>Name</span>
          <span>Status</span>
          <span>Command</span>
          <span>Config keys</span>
          <span>Actions</span>
        </div>
        {#each rows as row}
          <div class="grid min-h-16 grid-cols-[180px_120px_1.5fr_1fr_140px] gap-3 border-t px-3 py-3">
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
      </div>
    </div>
  {/if}
</section>
