<script lang="ts">
  import { onMount } from 'svelte';
  import { FileWarning, FolderOpen, Play, RefreshCw, Square, Star, Trash2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { liveStatus } from '$lib/live/status.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import { createGatewayStore } from './gateway-store.svelte';
  import type { Notify } from './types';
  import type { GatewayRow } from '$lib/api/server';

  let { notify }: { notify: Notify } = $props();

  const gateway = createGatewayStore((kind, message) => notify(kind, message));
  onMount(() => {
    gateway.load();
    return liveStatus.subscribe((status) => {
      gateway.applyLiveRows(status.gateways, status.gateways_error);
    });
  });

  function formatStderrTime(value: string | null) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    });
  }

  function formatBytes(value: number) {
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function stderrTitle(row: GatewayRow) {
    const updated = formatStderrTime(row.stderr_log_mtime);
    return `stderr.log${updated ? ` updated ${updated}` : ''} (${formatBytes(row.stderr_log_size)})`;
  }

  const GATEWAY_GRID = '220px 130px 140px 110px 260px';
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
          <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GATEWAY_GRID}>
            <span class="flex min-w-0 items-center gap-1.5">
              {#if row.is_default}
                <Star
                  class="shrink-0 text-amber-500"
                  fill="currentColor"
                  size={15}
                  title={`Default gateway: ${row.name}`}
                />
              {/if}
              <strong class="truncate font-sans text-sm">{row.name}</strong>
              <button
                class="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                type="button"
                onclick={() => gateway.openFolder(row)}
                title={`Open gateway folder: ${row.path}`}
                aria-label={`Open gateway folder: ${row.path}`}
              >
                <FolderOpen size={13} />
              </button>
            </span>
            <span class="space-y-1">
              <Badge variant={row.running ? 'success' : 'outline'}>
                {row.running ? 'Running' : 'Stopped'}
              </Badge>
              {#if row.pid && row.running}
                <small class="block text-xs text-muted-foreground">PID {row.pid}</small>
              {/if}
            </span>
            <span class="truncate text-xs text-muted-foreground">{row.host}:{row.port}</span>
            <span>
              <Badge variant={row.autostart_method && row.autostart_method !== 'skipped' ? 'secondary' : 'outline'}>
                {row.autostart_method ?? '-'}
              </Badge>
            </span>
            <span class="flex flex-wrap gap-1.5">
              {#if !row.running}
                <Button size="sm" variant="outline" disabled={gateway.busy} onclick={() => gateway.start(row)}><Play size={13} /> Start</Button>
              {:else}
                <Button size="sm" variant="outline" disabled={gateway.busy} onclick={() => gateway.openStop(row)}><Square size={13} /> Stop</Button>
              {/if}
              {#if row.stderr_log_exists}
                <Button
                  size="sm"
                  variant="outline"
                  class={row.stderr_log_recent ? 'border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive' : ''}
                  title={stderrTitle(row)}
                  onclick={() => gateway.openStderrLog(row)}
                >
                  <FileWarning size={13} /> stderr
                </Button>
              {/if}
              <Button size="sm" variant="destructive" onclick={() => gateway.openRemove(row)}><Trash2 size={13} /> Remove</Button>
            </span>
          </div>
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</section>

<Dialog.Root
  open={gateway.dialog === 'create'}
  onOpenChange={(next) => { if (!next) gateway.closeDialog(); }}
>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Create gateway instance</Dialog.Title>
    </Dialog.Header>
    <div class="grid gap-4">
      <FormField label="Name">
        {#snippet children()}
          <input bind:value={gateway.createForm.name} placeholder="e.g. main" />
        {/snippet}
      </FormField>
      <FormField label="Desktop public key">
        {#snippet children()}
          <textarea bind:value={gateway.createForm.desktopPublicKey} placeholder="Paste the workspace public key here"></textarea>
        {/snippet}
      </FormField>
      <FormField label="Port">
        {#snippet children()}
          <input bind:value={gateway.createForm.port} inputmode="numeric" placeholder="8765" />
        {/snippet}
      </FormField>
      <details class="grid gap-3 rounded-md border bg-muted/40 p-3">
        <summary class="cursor-pointer font-sans font-semibold">Advanced options</summary>
        <FormField label="Host">
          {#snippet children()}
            <input bind:value={gateway.createForm.host} placeholder="0.0.0.0" />
          {/snippet}
        </FormField>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={gateway.createForm.makeDefault} />
          Set as default gateway instance
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={gateway.createForm.skipAutostart} />
          Skip auto-start registration
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={gateway.createForm.elevatedTask} />
          Request elevated Task Scheduler entry
        </label>
      </details>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
      <Button disabled={gateway.busy} onclick={gateway.submitCreate}>Create</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={gateway.dialog === 'stop'}
  onOpenChange={(next) => { if (!next) gateway.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Stop gateway '{gateway.selected?.name ?? ''}'</Dialog.Title>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">This will stop the running gateway process.</p>
    <Dialog.Footer>
      <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
      <Button variant="destructive" disabled={gateway.busy} onclick={gateway.submitStop}>Stop</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root
  open={gateway.dialog === 'remove'}
  onOpenChange={(next) => { if (!next) gateway.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Remove gateway '{gateway.selected?.name ?? ''}'</Dialog.Title>
      {#if gateway.selected?.path}
        <Dialog.Description>{gateway.selected.path}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <label class="flex items-center gap-2 font-sans text-sm">
      <input type="checkbox" bind:checked={gateway.removeForm.purge} />
      Also delete instance files from disk
    </label>
    <Dialog.Footer>
      <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
      <Button variant="destructive" disabled={gateway.busy} onclick={gateway.submitRemove}>Remove</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
