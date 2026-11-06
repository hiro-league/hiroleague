import {
  askExtensionInfo,
  generateExtensionPairingCode,
  listExtensions,
  removeExtension,
  setExtensionAddress,
  type ExtensionListen,
  type ExtensionPairingData,
  type ExtensionRow
} from '$lib/api/extensions';
import type { Notify } from '$lib/ui/toast-types';

export type ExtensionsController = ReturnType<typeof createExtensionsController>;

/** Extensions page state: the paired list (with live status), pairing, removal, the address. */
export function createExtensionsController(notify: Notify) {
  let rows = $state<ExtensionRow[]>([]);
  let listen = $state<ExtensionListen | null>(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let pairing = $state<ExtensionPairingData | null>(null);
  let removeTarget = $state<ExtensionRow | null>(null);
  let hostDraft = $state('');
  let copied = $state(false);
  let copiedTimer: number | null = null;
  /** extension_id → the last test-call result shown on its row. */
  let testResults = $state<Record<string, string>>({});

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
      const payload = await listExtensions();
      rows = payload.data.extensions;
      listen = payload.data.listen;
      hostDraft = payload.data.listen.host;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load extensions.';
    } finally {
      loading = false;
    }
  }

  async function generatePairingCode() {
    busy = true;
    try {
      const result = await generateExtensionPairingCode();
      pairing = result.data;
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to make a pairing code.');
    } finally {
      busy = false;
    }
  }

  function closePairing() {
    pairing = null;
    clearCopyFeedback();
    // The extension may have paired while the dialog was open.
    void load();
  }

  async function copyPairing() {
    if (!pairing) return;
    try {
      await navigator.clipboard.writeText(`${pairing.address}\n${pairing.code}`);
      if (copiedTimer) window.clearTimeout(copiedTimer);
      copied = true;
      copiedTimer = window.setTimeout(clearCopyFeedback, 1800);
    } catch {
      notify('error', 'Copy failed.');
    }
  }

  function openRemove(row: ExtensionRow) {
    removeTarget = row;
  }

  function closeRemove() {
    if (busy) return;
    removeTarget = null;
  }

  async function submitRemove() {
    if (!removeTarget) return;
    busy = true;
    try {
      const result = await removeExtension(removeTarget.extension_id);
      notify('success', result.data ?? 'Extension removed.');
      removeTarget = null;
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Remove failed.');
    } finally {
      busy = false;
    }
  }

  async function testCall(row: ExtensionRow) {
    busy = true;
    try {
      const result = await askExtensionInfo(row.extension_id);
      const { info, elapsed_ms } = result.data;
      testResults = { ...testResults, [row.extension_id]: `${info.name} ${info.version} answered in ${elapsed_ms} ms` };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'No answer.';
      testResults = { ...testResults, [row.extension_id]: `No answer: ${message}` };
    } finally {
      busy = false;
    }
  }

  async function saveAddress() {
    busy = true;
    try {
      const result = await setExtensionAddress(hostDraft.trim());
      notify(
        'success',
        result.data.restart_required
          ? 'Saved. Restart the server for the new address to take effect.'
          : 'No change.'
      );
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Saving the address failed.');
    } finally {
      busy = false;
    }
  }

  return {
    get rows() {
      return rows;
    },
    get listen() {
      return listen;
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
    get removeTarget() {
      return removeTarget;
    },
    get copied() {
      return copied;
    },
    get testResults() {
      return testResults;
    },
    get hostDraft() {
      return hostDraft;
    },
    set hostDraft(value: string) {
      hostDraft = value;
    },
    get connectedCount() {
      return rows.filter((row) => row.connected).length;
    },
    load,
    generatePairingCode,
    closePairing,
    copyPairing,
    openRemove,
    closeRemove,
    submitRemove,
    testCall,
    saveAddress
  };
}
