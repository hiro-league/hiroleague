import {
  askExtensionInfo,
  disableChannel,
  enableChannel,
  generateExtensionPairingCode,
  installChannel,
  listAvailableChannels,
  listExtensions,
  removeExtension,
  setExtensionAddress,
  type ExtensionPairingData,
  type ExtensionRow
} from '$lib/api/extensions';
import { Action } from '$kit/state/action.svelte';
import { Draft } from '$kit/state/draft.svelte';
import { KeyedAction } from '$kit/state/keyed-action.svelte';
import { Resource } from '$kit/state/resource.svelte';
import { ask } from '$kit/ui/confirm.svelte';
import type { Notify } from '$kit/ui/toast.svelte';
import { countKinds, ofKinds, sortExtensions, type ExtensionKind } from '../shared/extension-rows';

export type ExtensionsController = ReturnType<typeof createExtensionsController>;

/**
 * The Extensions page: the one list of every extension (channel plugins and apps) with live status, its kind
 * filter, a channel's switch, removing one, installing a channel, adding an app, the test call and the listen
 * address. The row picked opens About or Settings (each its own panel).
 */
export function createExtensionsController(notify: Notify) {
  // A channel switched on connects a few seconds later: the list reads again every 5 s while the page is open.
  const list = new Resource(listExtensions, { every: 5000 });
  const all = $derived(sortExtensions(list.data?.extensions ?? []));
  let kinds = $state<ExtensionKind[]>([]);
  const rows = $derived(ofKinds(all, kinds));
  const counts = $derived(countKinds(all));
  const listen = $derived(list.data?.listen ?? null);

  /** The channels not installed yet; read when Install a channel opens. */
  const available = new Resource(async () => (await listAvailableChannels()).channels);
  let installOpen = $state(false);
  const installAction = new Action({ then: () => list.reload() });

  const pairingAction = new Action();
  const removeAction = new Action();
  const testAction = new Action();
  /** A channel's switch, one per row. */
  const switching = new KeyedAction();
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
  const busy = $derived(pairingAction.busy || removeAction.busy || host.action.busy);
  $effect(() => {
    if (list.data) host.load(list.data.listen.host);
  });

  let pairing = $state<ExtensionPairingData | null>(null);
  let copied = $state(false);
  let copiedTimer: number | null = null;
  /** extension_id → the last test call's answer, shown in About. */
  let testResults = $state<Record<string, string>>({});

  /** The row picked, and which of its panels is open: About (read only) or Settings (edited in place). */
  let pickedId = $state<string | null>(null);
  let panel = $state<'about' | 'settings'>('about');
  const picked = $derived(all.find((row) => row.extension_id === pickedId) ?? null);

  function openAbout(row: ExtensionRow) {
    pickedId = row.extension_id;
    panel = 'about';
  }

  function openSettings(row: ExtensionRow) {
    pickedId = row.extension_id;
    panel = 'settings';
  }

  function closePanel() {
    pickedId = null;
  }

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
    // The app may have paired while the dialog was open.
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

  /** A channel's switch: off stops it and keeps its settings; on starts it. */
  async function toggle(row: ExtensionRow) {
    const on = !row.enabled;
    await switching.run(row.extension_id, async () => {
      await (on ? enableChannel(row.name) : disableChannel(row.name));
      await list.reload();
    });
    const error = switching.error(row.extension_id);
    if (error) notify('error', error);
  }

  async function remove(row: ExtensionRow) {
    const yes = await ask({
      title: `Remove ${row.label}?`,
      description:
        row.kind === 'app'
          ? `The core forgets ${row.label} and its key; it pairs again with a new code. The app itself and its data stay.`
          : `The core stops ${row.label}, deletes its settings and uninstalls its program. You can install it again later.`,
      action: 'Remove',
      danger: true
    });
    if (!yes) return;
    await removeAction.run(async () => {
      const { message } = await removeExtension(row.extension_id);
      notify('success', message);
      if (pickedId === row.extension_id) pickedId = null;
      await list.reload();
    });
    if (removeAction.error) notify('error', removeAction.error);
  }

  function openInstall() {
    installAction.clear();
    installOpen = true;
    void available.reload();
  }

  async function install(name: string) {
    await installAction.run(async () => {
      await installChannel(name);
      installOpen = false;
      notify('success', 'Installed. Switch it on, then open its Settings.');
    });
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
    /** The rows the kind filter lets through. */
    get rows() {
      return rows;
    },
    get counts() {
      return counts;
    },
    get kinds() {
      return kinds;
    },
    setKinds: (next: ExtensionKind[]) => {
      kinds = next;
    },
    get connectedCount() {
      return rows.filter((row) => row.connected).length;
    },
    get listen() {
      return listen;
    },
    get loading() {
      return list.data === null && !list.error;
    },
    get error() {
      return list.error || null;
    },
    get busy() {
      return busy;
    },
    isSwitching: (row: ExtensionRow) => switching.busy(row.extension_id),
    get picked() {
      return picked;
    },
    get panel() {
      return panel;
    },
    get pairing() {
      return pairing;
    },
    get copied() {
      return copied;
    },
    get testing() {
      return testAction.busy;
    },
    testResult: (row: ExtensionRow) => testResults[row.extension_id] ?? '',
    /** The listen address being edited (bind to `host.value`; `host.dirty` says it differs from what is saved). */
    get host() {
      return host;
    },
    get installOpen() {
      return installOpen;
    },
    closeInstall: () => {
      if (!installAction.busy) installOpen = false;
    },
    get available() {
      return available;
    },
    get installAction() {
      return installAction;
    },
    load: list.reload,
    openAbout,
    openSettings,
    closePanel,
    generatePairingCode,
    closePairing,
    copyPairing,
    toggle,
    remove,
    openInstall,
    install,
    testCall,
    saveAddress
  };
}
