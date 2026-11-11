import {
  askExtensionInfo,
  generateExtensionPairingCode,
  listExtensions,
  removeExtension,
  setExtensionAddress,
  type ExtensionPairingData,
  type ExtensionRow
} from '$lib/api/extensions';
import { Action } from '$kit/state/action.svelte';
import { Draft } from '$kit/state/draft.svelte';
import { Resource } from '$kit/state/resource.svelte';
import type { Notify } from '$kit/ui/toast.svelte';

export type ExtensionsController = ReturnType<typeof createExtensionsController>;

/** Extensions page state: the paired list (with live status), pairing, removal, the address. */
export function createExtensionsController(notify: Notify) {
  const list = new Resource(listExtensions);
  const rows = $derived(list.data?.extensions ?? []);
  const listen = $derived(list.data?.listen ?? null);
  /** One action per kind of change; `busy` is any of them, so one button waits for all. */
  const pairingAction = new Action();
  const removeAction = new Action();
  const testAction = new Action();
  /** The listen address being edited; it follows what the server says until the person edits it. */
  const host = new Draft<string>('', {
    equal: (a, b) => a.trim() === b.trim(),
    save: async (draft) => {
      const result = await setExtensionAddress(draft.trim());
      notify(
        'success',
        result.restart_required
          ? 'Saved. Restart the server for the new address to take effect.'
          : 'No change.'
      );
      await list.reload();
      return draft.trim();
    }
  });
  const busy = $derived(
    pairingAction.busy || removeAction.busy || testAction.busy || host.action.busy
  );
  $effect(() => {
    if (list.data) host.load(list.data.listen.host);
  });
  let pairing = $state<ExtensionPairingData | null>(null);
  let removeTarget = $state<ExtensionRow | null>(null);
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

  async function generatePairingCode() {
    await pairingAction.run(async () => {
      pairing = await generateExtensionPairingCode();
    });
    if (pairingAction.error) notify('error', pairingAction.error);
  }

  function closePairing() {
    pairing = null;
    clearCopyFeedback();
    // The extension may have paired while the dialog was open.
    void list.reload();
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
    const row = removeTarget;
    await removeAction.run(async () => {
      const result = await removeExtension(row.extension_id);
      notify('success', result ?? 'Extension removed.');
      removeTarget = null;
      await list.reload();
    });
    if (removeAction.error) notify('error', removeAction.error);
  }

  async function testCall(row: ExtensionRow) {
    const answer = await testAction.run(async () => {
      const { info, elapsed_ms } = await askExtensionInfo(row.extension_id);
      return `${info.name} ${info.version} answered in ${elapsed_ms} ms`;
    });
    testResults = {
      ...testResults,
      [row.extension_id]: testAction.error ? `No answer: ${testAction.error}` : (answer ?? '')
    };
  }

  async function saveAddress() {
    await host.save();
    if (host.action.error) notify('error', host.action.error);
  }

  return {
    get rows() {
      return rows;
    },
    get listen() {
      return listen;
    },
    get loading() {
      return list.data === null && !list.error;
    },
    get busy() {
      return busy;
    },
    get error() {
      return list.error || null;
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
    /** The listen address being edited (bind to `host.value`; `host.dirty` says it differs from what is saved). */
    get host() {
      return host;
    },
    get connectedCount() {
      return rows.filter((row) => row.connected).length;
    },
    load: list.reload,
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
