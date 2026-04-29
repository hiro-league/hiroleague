<script lang="ts">
  import { Check, Copy, Link2, Link2Off, RefreshCw } from '@lucide/svelte';
  import {
    generateDevicePairingCode,
    listDevices,
    revokeDevice,
    type DevicePairingData,
    type DeviceRow
  } from '$lib/api/channels-devices';
  import Button from '$lib/components/ui/button.svelte';
  import Modal from '$lib/ui/Modal.svelte';
  import type { Notify } from './types';

  let { notify }: { notify: Notify } = $props();

  let rows = $state<DeviceRow[]>([]);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let pairing = $state<DevicePairingData | null>(null);
  let revokeTarget = $state<DeviceRow | null>(null);
  let copied = $state(false);
  let copiedTimer = $state<number | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const payload = await listDevices();
      rows = payload.data;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load devices.';
    } finally {
      loading = false;
    }
  }

  function closePairing() {
    if (busy) return;
    pairing = null;
    copied = false;
  }

  function closeRevoke() {
    if (busy) return;
    revokeTarget = null;
  }

  function formatDate(value: string | null) {
    return value ? value.replace('T', ' ').replace('Z', ' UTC') : '-';
  }

  function displayName(row: DeviceRow) {
    if (row.device_name) return row.device_name;
    return row.device_id.length > 12 ? `${row.device_id.slice(0, 12)}...` : row.device_id;
  }

  async function generatePairingCode() {
    busy = true;
    try {
      const result = await generateDevicePairingCode();
      pairing = result.data;
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to generate code.');
    } finally {
      busy = false;
    }
  }

  async function copyPairingPayload() {
    if (!pairing) return;
    try {
      await navigator.clipboard.writeText(pairing.qr_payload);
      copied = true;
      if (copiedTimer) {
        window.clearTimeout(copiedTimer);
      }
      copiedTimer = window.setTimeout(() => {
        copied = false;
        copiedTimer = null;
      }, 1800);
      notify('success', 'Pairing message copied to clipboard.');
    } catch {
      notify('error', 'Copy failed.');
    }
  }

  async function submitRevoke() {
    if (!revokeTarget) return;
    busy = true;
    try {
      const result = await revokeDevice(revokeTarget.device_id);
      notify('success', result.data ?? 'Device revoked.');
      revokeTarget = null;
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Revoke failed.');
    } finally {
      busy = false;
    }
  }

  load();
</script>

<section class="grid gap-4">
  <div class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <h3 class="text-lg font-semibold">Pair new device</h3>
        <p class="font-sans text-sm text-muted-foreground">
          Generate a short-lived code and enter it on your mobile device to authorize it.
        </p>
      </div>
      <Button disabled={busy} onclick={generatePairingCode}><Link2 size={15} /> Generate pairing code</Button>
    </div>
  </div>

  <section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <h3 class="text-lg font-semibold">Approved devices</h3>
        <span class="font-sans text-sm text-muted-foreground">{rows.length} paired</span>
      </div>
      <Button variant="outline" onclick={load}><RefreshCw size={15} /> Refresh</Button>
    </div>

    {#if loading}
      <p class="text-muted-foreground">Loading devices...</p>
    {:else if error}
      <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
        <strong class="font-sans">Could not load devices</strong>
        <span class="block text-sm">{error}</span>
      </div>
    {:else if rows.length === 0}
      <p class="text-muted-foreground">No paired devices. Use the button above to generate a pairing code.</p>
    {:else}
      <div class="overflow-x-auto rounded-md border">
        <div class="min-w-[920px]">
          <div
            class="grid grid-cols-[180px_1.5fr_190px_190px_110px] gap-3 bg-muted px-3 py-2 font-sans text-xs font-bold uppercase text-muted-foreground"
          >
            <span>Name</span>
            <span>Device ID</span>
            <span>Paired</span>
            <span>Expires</span>
            <span>Actions</span>
          </div>
          {#each rows as row}
            <div class="grid min-h-16 grid-cols-[180px_1.5fr_190px_190px_110px] gap-3 border-t px-3 py-3">
              <span class="truncate font-sans text-sm font-semibold" title={row.device_name ?? ''}>
                {row.device_name || '-'}
              </span>
              <span class="truncate font-mono text-xs text-muted-foreground" title={row.device_id}>
                {row.device_id}
              </span>
              <span class="truncate text-xs text-muted-foreground">{formatDate(row.paired_at)}</span>
              <span class="truncate text-xs text-muted-foreground">{formatDate(row.expires_at)}</span>
              <span class="flex justify-end">
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy}
                  onclick={() => (revokeTarget = row)}
                  title="Revoke device"
                >
                  <Link2Off size={13} /> Revoke
                </Button>
              </span>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  </section>
</section>

<Modal open={pairing !== null} title="Pairing code" onClose={closePairing}>
  {#if pairing}
    <div class="grid justify-items-center gap-3 text-center">
      <div
        class="grid size-48 place-items-center rounded-md border bg-white p-2 text-black [&_svg]:h-full [&_svg]:w-full"
      >
        {@html pairing.qr_svg}
      </div>
      <div class="font-mono text-5xl font-bold tracking-widest text-primary">{pairing.code}</div>
      <p class="font-sans text-sm text-muted-foreground">Expires: {formatDate(pairing.expires_at)}</p>
      <p class="font-sans text-sm text-muted-foreground">
        Scan the QR code or enter the code manually in the mobile app.
      </p>
      <div class="flex max-w-full items-center gap-1 font-mono text-xs text-muted-foreground">
        <Link2 size={13} />
        <span class="truncate">{pairing.gateway_url || 'no gateway configured'}</span>
      </div>
    </div>
  {/if}
  {#snippet footer()}
    <Button variant="outline" onclick={copyPairingPayload}>
      {#if copied}
        <Check class="text-emerald-500" size={15} />
      {:else}
        <Copy size={15} />
      {/if}
      Copy pairing message
    </Button>
    <Button onclick={closePairing}>Close</Button>
  {/snippet}
</Modal>

<Modal
  open={revokeTarget !== null}
  title={`Revoke '${revokeTarget ? displayName(revokeTarget) : ''}'?`}
  onClose={closeRevoke}
>
  <p class="text-sm text-muted-foreground">This device will no longer be able to connect.</p>
  {#snippet footer()}
    <Button variant="outline" onclick={closeRevoke}>Cancel</Button>
    <Button variant="destructive" disabled={busy} onclick={submitRevoke}>Revoke</Button>
  {/snippet}
</Modal>
