<script lang="ts">
  import { Play, RefreshCw, Square, Trash2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Modal from '$lib/ui/Modal.svelte';
  import { createGatewayStore } from './gateway-store.svelte';
  import type { Notify } from './types';

  let { notify }: { notify: Notify } = $props();

  const gateway = createGatewayStore((kind, message) => notify(kind, message));
  gateway.load();
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
      <Button variant="outline" onclick={gateway.load}><RefreshCw size={15} /> Refresh</Button>
      <Button onclick={gateway.openCreate}>Create gateway</Button>
    </div>
  </div>

  {#if gateway.loading}
    <p class="text-muted-foreground">Loading gateways...</p>
  {:else if gateway.error}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
      <strong class="font-sans">Could not load gateways</strong>
      <span class="block text-sm">{gateway.error}</span>
    </div>
  {:else if gateway.rows.length === 0}
    <p class="text-muted-foreground">No gateway instances configured yet.</p>
  {:else}
    <div class="overflow-x-auto rounded-md border">
      <div class="min-w-[980px]">
        <div class="grid grid-cols-[150px_130px_140px_95px_1fr_180px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground">
          <span>Name</span>
          <span>Status</span>
          <span>Host : Port</span>
          <span>Default</span>
          <span>Path</span>
          <span>Actions</span>
        </div>
        {#each gateway.rows as row}
          <div class="grid min-h-16 grid-cols-[150px_130px_140px_95px_1fr_180px] gap-3 border-t px-3 py-3">
            <span class="truncate font-sans text-sm font-semibold">{row.name}</span>
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
              {#if row.is_default}
                <Badge variant="secondary">default</Badge>
              {:else}
                <small class="text-muted-foreground">-</small>
              {/if}
            </span>
            <span class="truncate text-xs text-muted-foreground">{row.path}</span>
            <span class="flex flex-wrap gap-1.5">
              {#if !row.running}
                <Button size="sm" variant="outline" disabled={gateway.busy} onclick={() => gateway.start(row)}><Play size={13} /> Start</Button>
              {:else}
                <Button size="sm" variant="outline" disabled={gateway.busy} onclick={() => gateway.openStop(row)}><Square size={13} /> Stop</Button>
              {/if}
              <Button size="sm" variant="destructive" onclick={() => gateway.openRemove(row)}><Trash2 size={13} /> Remove</Button>
            </span>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</section>

<Modal open={gateway.dialog === 'create'} title="Create gateway instance" onClose={gateway.closeDialog}>
  <label>Name<input bind:value={gateway.createForm.name} placeholder="e.g. main" /></label>
  <label>Desktop public key<textarea bind:value={gateway.createForm.desktopPublicKey} placeholder="Paste the workspace public key here"></textarea></label>
  <label>Port<input bind:value={gateway.createForm.port} inputmode="numeric" placeholder="8765" /></label>
  <details>
    <summary>Advanced options</summary>
    <label>Host<input bind:value={gateway.createForm.host} placeholder="0.0.0.0" /></label>
    <label class="check-row"><input type="checkbox" bind:checked={gateway.createForm.makeDefault} /> Set as default gateway instance</label>
    <label class="check-row"><input type="checkbox" bind:checked={gateway.createForm.skipAutostart} /> Skip auto-start registration</label>
    <label class="check-row"><input type="checkbox" bind:checked={gateway.createForm.elevatedTask} /> Request elevated Task Scheduler entry</label>
  </details>
  {#snippet footer()}
    <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
    <Button disabled={gateway.busy} onclick={gateway.submitCreate}>Create</Button>
  {/snippet}
</Modal>

<Modal open={gateway.dialog === 'stop'} title={`Stop gateway '${gateway.selected?.name ?? ''}'`} onClose={gateway.closeDialog}>
  <p class="text-sm text-muted-foreground">This will stop the running gateway process.</p>
  {#snippet footer()}
    <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
    <Button variant="destructive" disabled={gateway.busy} onclick={gateway.submitStop}>Stop</Button>
  {/snippet}
</Modal>

<Modal open={gateway.dialog === 'remove'} title={`Remove gateway '${gateway.selected?.name ?? ''}'`} subtitle={gateway.selected?.path ?? ''} onClose={gateway.closeDialog}>
  <label class="check-row"><input type="checkbox" bind:checked={gateway.removeForm.purge} /> Also delete instance files from disk</label>
  {#snippet footer()}
    <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
    <Button variant="destructive" disabled={gateway.busy} onclick={gateway.submitRemove}>Remove</Button>
  {/snippet}
</Modal>
