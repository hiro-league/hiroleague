import {
  generateDevicePairingCode,
  listDevices,
  revokeDevice,
  type DevicePairingData,
  type DeviceRow
} from '$lib/api/channels-devices';
import type { Notify } from '$lib/ui/toast-types';
import { displayDeviceName } from '../shared/channels-devices-format';

export type DevicesController = ReturnType<typeof createDevicesController>;

export function createDevicesController(notify: Notify) {
  let rows = $state<DeviceRow[]>([]);
  let loading = $state(true);
  let busy = $state(false);
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
    clearCopyFeedback();
  }

  function closeRevoke() {
    if (busy) return;
    revokeTarget = null;
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
      return busy;
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
