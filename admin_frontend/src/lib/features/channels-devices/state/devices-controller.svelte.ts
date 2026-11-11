import { errorMessage } from '$kit/api/client';
import { Action } from '$kit/state/action.svelte';
import {
  generateDevicePairingCode,
  listDevices,
  revokeDevice,
  type DevicePairingData,
  type DeviceRow
} from '$lib/api/channels-devices';
import type { Notify } from '$kit/ui/toast.svelte';
import { displayDeviceName } from '../shared/channels-devices-format';

export type DevicesController = ReturnType<typeof createDevicesController>;

export function createDevicesController(notify: Notify) {
  let rows = $state<DeviceRow[]>([]);
  let loading = $state(true);
  const work = new Action();
  let error = $state<string | null>(null);
  let pairing = $state<DevicePairingData | null>(null);
  let revokeTarget = $state<DeviceRow | null>(null);
  let copied = $state(false);
  let copiedTimer = $state<number | null>(null);

  function clearCopyFeedback() {
    copied = false;
    if (copiedTimer) {
      window.clearTimeout(copiedTimer);
      copiedTimer = null;
    }
  }

  async function load() {
    loading = true;
    error = null;
    try {
      const payload = await listDevices();
      rows = payload;
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }

  function closePairing() {
    if (work.busy) return;
    pairing = null;
    clearCopyFeedback();
  }

  function closeRevoke() {
    if (work.busy) return;
    revokeTarget = null;
  }

  async function generatePairingCode() {
    await work.run(async () => {
      pairing = await generateDevicePairingCode();
      await load();
    });
    if (work.error) notify('error', work.error);
  }

  async function copyPairingPayload() {
    if (!pairing) return;
    try {
      await navigator.clipboard.writeText(pairing.qr_payload);
      if (copiedTimer) window.clearTimeout(copiedTimer);
      copied = true;
      copiedTimer = window.setTimeout(clearCopyFeedback, 1800);
      notify('success', 'Pairing message copied to clipboard.');
    } catch {
      notify('error', 'Copy failed.');
    }
  }

  async function submitRevoke() {
    if (!revokeTarget) return;
    const target = revokeTarget;
    await work.run(async () => {
      const result = await revokeDevice(target.device_id);
      notify('success', result ?? 'Device revoked.');
      revokeTarget = null;
      await load();
    });
    if (work.error) notify('error', work.error);
  }

  function openRevoke(row: DeviceRow) {
    revokeTarget = row;
  }

  return {
    get rows() {
      return rows;
    },
    get loading() {
      return loading;
    },
    get busy() {
      return work.busy;
    },
    get error() {
      return error;
    },
    get pairing() {
      return pairing;
    },
    get revokeTarget() {
      return revokeTarget;
    },
    get copied() {
      return copied;
    },
    get revokeDisplayName() {
      return revokeTarget ? displayDeviceName(revokeTarget) : '';
    },
    load,
    closePairing,
    closeRevoke,
    generatePairingCode,
    copyPairingPayload,
    submitRevoke,
    openRevoke
  };
}
