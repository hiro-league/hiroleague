// mockup: the one list's state, on mock rows (one-list-mock.ts). Switching and removing change only these
// rows, in this browser tab; nothing is sent to the core.
import { Draft } from '$kit/state/draft.svelte';
import { ask } from '$kit/ui/confirm.svelte';
import type { Notify } from '$kit/ui/toast.svelte';
import {
  MOCK_EXTENSIONS,
  sortExtensions,
  type ExtensionKind,
  type MockExtension,
  type MockSetting
} from './one-list-mock';

export type OneListMockup = ReturnType<typeof createOneListMockup>;

export function createOneListMockup(notify: Notify) {
  let rows = $state<MockExtension[]>(sortExtensions(MOCK_EXTENSIONS));
  /** The kinds the list shows; none picked shows every kind. */
  let kinds = $state<ExtensionKind[]>([]);
  const shown = $derived(kinds.length ? rows.filter((row) => kinds.includes(row.kind)) : rows);
  let selectedId = $state<string | null>(null);
  /** Which panel the picked row opens: About (read only) or Settings (edited in place). */
  let panel = $state<'about' | 'settings'>('about');
  const selected = $derived(rows.find((row) => row.extension_id === selectedId) ?? null);
  const connectedCount = $derived(shown.filter((row) => row.connected && row.enabled !== false).length);
  const counts = $derived({
    channel: rows.filter((row) => row.kind === 'channel').length,
    app: rows.filter((row) => row.kind === 'app').length
  });

  function open(row: MockExtension) {
    selectedId = row.extension_id;
    panel = 'about';
  }

  /** The Settings panel's copy of the picked row's settings; the EditorSheet asks before changes are lost. */
  const settingsForm = new Draft<MockSetting[] | null>(null, {
    guard: false,
    save: async (draft) => {
      const id = selectedId;
      if (!draft || !id) return;
      rows = rows.map((r) => (r.extension_id === id ? { ...r, settings: draft } : r));
      const label = rows.find((r) => r.extension_id === id)?.label ?? '';
      selectedId = null;
      notify('success', `${label}'s settings saved (mockup: nothing was sent).`);
    }
  });

  function openSettings(row: MockExtension) {
    settingsForm.load(row.settings ?? [], true);
    selectedId = row.extension_id;
    panel = 'settings';
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
    /** Every row the kind toggles let through. */
    get rows() {
      return shown;
    },
    get kinds() {
      return kinds;
    },
    setKinds: (next: ExtensionKind[]) => {
      kinds = next;
    },
    get counts() {
      return counts;
    },
    get selected() {
      return selected;
    },
    get panel() {
      return panel;
    },
    get connectedCount() {
      return connectedCount;
    },
    open,
    openSettings,
    settingsForm,
    close,
    toggle,
    remove,
    notYet
  };
}
