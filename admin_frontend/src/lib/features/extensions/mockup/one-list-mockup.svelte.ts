// mockup: the one list's state, on mock rows (one-list-mock.ts). Switching and removing change only these
// rows, in this browser tab; nothing is sent to the core.
import { ask } from '$kit/ui/confirm.svelte';
import type { Notify } from '$kit/ui/toast.svelte';
import { MOCK_EXTENSIONS, sortExtensions, type MockExtension } from './one-list-mock';

export type OneListMockup = ReturnType<typeof createOneListMockup>;

export function createOneListMockup(notify: Notify) {
  let rows = $state<MockExtension[]>(sortExtensions(MOCK_EXTENSIONS));
  let selectedId = $state<string | null>(null);
  const selected = $derived(rows.find((row) => row.extension_id === selectedId) ?? null);
  const connectedCount = $derived(rows.filter((row) => row.connected && row.enabled !== false).length);

  function open(row: MockExtension) {
    selectedId = row.extension_id;
  }

  function close() {
    selectedId = null;
  }

  /** A started extension's switch: off stops it, on starts it with a fresh pairing code if it needs one. */
  function toggle(row: MockExtension) {
    const on = !row.enabled;
    rows = rows.map((r) =>
      r.extension_id === row.extension_id
        ? { ...r, enabled: on, connected: on, since: new Date().toISOString() }
        : r
    );
    notify('success', `${row.label} is ${on ? 'on' : 'off'} (mockup: nothing was sent).`);
  }

  async function remove(row: MockExtension) {
    const yes = await ask({
      title: `Remove ${row.label}?`,
      description:
        row.kind === 'app'
          ? `${row.label} loses its key and has to pair again with a new code.`
          : `The core stops ${row.label}, forgets its key and settings, and uninstalls its plugin.`,
      action: 'Remove',
      danger: true
    });
    if (!yes) return;
    rows = rows.filter((r) => r.extension_id !== row.extension_id);
    if (selectedId === row.extension_id) selectedId = null;
    notify('success', `${row.label} removed (mockup: nothing was sent).`);
  }

  /** What a button that isn't drawn yet would do. */
  function notYet(what: string) {
    notify('success', `Mockup: ${what}.`);
  }

  return {
    get rows() {
      return rows;
    },
    get selected() {
      return selected;
    },
    get connectedCount() {
      return connectedCount;
    },
    open,
    close,
    toggle,
    remove,
    notYet
  };
}
