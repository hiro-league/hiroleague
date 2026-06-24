import {
  createWorkspace,
  getWorkspacePublicKey,
  listWorkspaces,
  openPath,
  openWorkspaceFolder,
  regenerateWorkspaceKey,
  removeWorkspace,
  restartWorkspace,
  setupWorkspace,
  startWorkspace,
  stopWorkspace,
  updateWorkspace,
  type WorkspaceRow
} from '$lib/api/server';
import { createMutation, createResource } from '$lib/state/create-resource.svelte';
import type { Notify } from '$lib/ui/toast-types';

type WorkspaceListSnapshot = {
  rows: WorkspaceRow[];
  hostingWorkspaceId: string | null;
};

export type WorkspaceDialog =
  | 'create'
  | 'edit'
  | 'remove'
  | 'restart'
  | 'setup'
  | 'setup-key'
  | 'public-key'
  | null;

export function createWorkspaceStore(notify: Notify) {
  const listResource = createResource(
    async (): Promise<WorkspaceListSnapshot> => {
      const payload = await listWorkspaces();
      return {
        rows: payload.data,
        hostingWorkspaceId: payload.hosting_workspace_id ?? null
      };
    },
    {
      initial: { rows: [], hostingWorkspaceId: null },
      initialLoading: true,
      errorPrefix: 'Failed to load workspaces.'
    }
  );

  let error = $state<string | null>(null);
  let hydrated = $state(false);
  let dialog = $state<WorkspaceDialog>(null);
  let selected = $state<WorkspaceRow | null>(null);
  let busy = $state(false);

  let createForm = $state({ name: '', path: '' });
  let editForm = $state({ name: '', gatewayUrl: '', setDefault: false });
  let removeForm = $state({ purge: false });
  let restartForm = $state({ admin: false });
  let setupForm = $state({
    gatewayUrl: '',
    httpPort: '',
    skipAutostart: false,
    startServer: false,
    elevatedTask: false
  });
  let publicKey = $state('');
  let setupPublicKey = $state('');
  let copiedText = $state('');
  let copiedTimer = $state<number | null>(null);

  const configuredCount = $derived(listResource.data.rows.filter((row) => row.is_configured).length);
  const runningCount = $derived(listResource.data.rows.filter((row) => row.running).length);

  function rowsChanged(nextRows: WorkspaceRow[], nextHostingWorkspaceId: string | null) {
    return (
      listResource.data.hostingWorkspaceId !== nextHostingWorkspaceId ||
      JSON.stringify(listResource.data.rows) !== JSON.stringify(nextRows)
    );
  }

  async function load(options: { silent?: boolean } = {}) {
    if (options.silent && busy) return;
    await listResource.load({ silent: options.silent });
    if (!options.silent) {
      error = listResource.error;
    }
    hydrated = true;
  }

  function applyLiveRows(
    nextRows: WorkspaceRow[],
    nextHostingWorkspaceId: string | null,
    nextError: string | null
  ) {
    if (rowsChanged(nextRows, nextHostingWorkspaceId)) {
      listResource.replace({ rows: nextRows, hostingWorkspaceId: nextHostingWorkspaceId });
    }
    error = nextError;
    hydrated = true;
  }

  function closeDialog() {
    if (busy) return;
    resetDialog();
  }

  function resetDialog() {
    dialog = null;
    selected = null;
  }

  function openCreate() {
    createForm = { name: '', path: '' };
    dialog = 'create';
  }

  function openEdit(row: WorkspaceRow) {
    selected = row;
    editForm = {
      name: row.name,
      gatewayUrl: row.gateway_url ?? '',
      setDefault: row.is_default
    };
    dialog = 'edit';
  }

  function openRemove(row: WorkspaceRow) {
    selected = row;
    removeForm = { purge: false };
    dialog = 'remove';
  }

  function openRestart(row: WorkspaceRow) {
    selected = row;
    restartForm = { admin: row.id === listResource.data.hostingWorkspaceId };
    dialog = 'restart';
  }

  function openSetup(row: WorkspaceRow) {
    selected = row;
    setupForm = {
      gatewayUrl: row.gateway_url ?? '',
      httpPort: '',
      skipAutostart: false,
      startServer: false,
      elevatedTask: false
    };
    setupPublicKey = '';
    dialog = 'setup';
  }

  async function submitCreate() {
    busy = true;
    try {
      await createMutation(
        () =>
          createWorkspace({
            name: createForm.name,
            path: createForm.path.trim() || null
          }),
        {
          notify,
          successMsg: (result) => result.data ?? 'Workspace created.',
          errorPrefix: 'Create failed.',
          onDone: async () => {
            resetDialog();
            await load();
          }
        }
      ).run();
    } finally {
      busy = false;
    }
  }

  async function submitEdit() {
    if (!selected) return;
    busy = true;
    try {
      await createMutation(
        () =>
          updateWorkspace(selected!.id, {
            name: editForm.name.trim() || null,
            gateway_url: editForm.gatewayUrl.trim() || null,
            set_default: editForm.setDefault,
            previous_display_name: selected!.name
          }),
        {
          notify,
          successMsg: (result) => result.data ?? 'Workspace updated.',
          errorPrefix: 'Update failed.',
          onDone: async () => {
            resetDialog();
            await load();
          }
        }
      ).run();
    } finally {
      busy = false;
    }
  }

  async function submitRemove() {
    if (!selected) return;
    busy = true;
    try {
      await createMutation(() => removeWorkspace(selected!.id, removeForm.purge), {
        notify,
        successMsg: (result) => result.data ?? 'Workspace removed.',
        errorPrefix: 'Remove failed.',
        onDone: async () => {
          resetDialog();
          await load();
        }
      }).run();
    } finally {
      busy = false;
    }
  }

  async function submitRestart() {
    if (!selected) return;
    busy = true;
    try {
      await createMutation(() => restartWorkspace(selected!.id, restartForm.admin), {
        notify,
        successMsg: () =>
          selected!.id === listResource.data.hostingWorkspaceId
            ? 'Restarting current workspace. The admin UI should return shortly.'
            : `Workspace '${selected!.name}' restarted.`,
        errorPrefix: 'Restart failed.',
        onDone: async () => {
          resetDialog();
          await load();
        }
      }).run();
    } finally {
      busy = false;
    }
  }

  async function submitSetup() {
    if (!selected) return;
    busy = true;
    try {
      await createMutation(
        () =>
          setupWorkspace(selected!.id, {
            gateway_url: setupForm.gatewayUrl,
            http_port: setupForm.httpPort.trim() ? Number(setupForm.httpPort) : null,
            skip_autostart: setupForm.skipAutostart,
            start_server: setupForm.startServer,
            elevated_task: setupForm.elevatedTask
          }),
        {
          notify,
          errorPrefix: 'Setup failed.',
          onDone: async (result) => {
            setupPublicKey = result.data.desktop_pub;
            dialog = 'setup-key';
            await load();
          }
        }
      ).run();
    } finally {
      busy = false;
    }
  }

  async function start(row: WorkspaceRow) {
    busy = true;
    try {
      await createMutation(() => startWorkspace(row.id), {
        notify,
        successMsg: (result) =>
          result.data.already_running
            ? undefined
            : `'${result.data.name}' started (PID ${result.data.pid}).`,
        errorPrefix: 'Start failed.',
        onDone: async (result) => {
          if (result.data.already_running) {
            notify('warning', `'${result.data.name}' is already running.`);
          }
          await load();
        }
      }).run();
    } finally {
      busy = false;
    }
  }

  async function stop(row: WorkspaceRow) {
    busy = true;
    try {
      await createMutation(() => stopWorkspace(row.id), {
        notify,
        successMsg: (result) => result.data ?? `'${row.name}' stopped.`,
        errorPrefix: 'Stop failed.',
        onDone: () => load()
      }).run();
    } finally {
      busy = false;
    }
  }

  async function openFolder(row: WorkspaceRow) {
    try {
      await openWorkspaceFolder(row.path);
      notify('info', `Opening folder: ${row.path}`);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Open folder failed.');
    }
  }

  async function openStderrLog(row: WorkspaceRow) {
    if (!row.stderr_log_exists) return;
    try {
      await openPath(row.stderr_log_path);
      notify('info', `Opening stderr log: ${row.stderr_log_path}`);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Open stderr log failed.');
    }
  }

  async function openPublicKey(row: WorkspaceRow) {
    busy = true;
    selected = row;
    try {
      const result = await getWorkspacePublicKey(row.id);
      publicKey = result.data;
      dialog = 'public-key';
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to load public key.');
    } finally {
      busy = false;
    }
  }

  async function regenerateKey() {
    if (!selected) return;
    busy = true;
    try {
      const result = await regenerateWorkspaceKey(selected.id);
      publicKey = result.data;
      notify('warning', `New key generated for '${selected.name}'. Update your gateway.`);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Regenerate failed.');
    } finally {
      busy = false;
    }
  }

  async function copyText(text: string) {
    await navigator.clipboard.writeText(text);
    copiedText = text;
    if (copiedTimer) {
      window.clearTimeout(copiedTimer);
    }
    copiedTimer = window.setTimeout(() => {
      copiedText = '';
      copiedTimer = null;
    }, 1800);
    notify('success', 'Copied to clipboard.');
  }

  return {
    get rows() {
      return listResource.data.rows;
    },
    get hostingWorkspaceId() {
      return listResource.data.hostingWorkspaceId;
    },
    get loading() {
      return !hydrated;
    },
    get busy() {
      return busy;
    },
    get error() {
      return error;
    },
    get dialog() {
      return dialog;
    },
    get selected() {
      return selected;
    },
    get createForm() {
      return createForm;
    },
    get editForm() {
      return editForm;
    },
    get removeForm() {
      return removeForm;
    },
    get restartForm() {
      return restartForm;
    },
    get setupForm() {
      return setupForm;
    },
    get publicKey() {
      return publicKey;
    },
    get setupPublicKey() {
      return setupPublicKey;
    },
    get copiedText() {
      return copiedText;
    },
    get configuredCount() {
      return configuredCount;
    },
    get runningCount() {
      return runningCount;
    },
    load,
    applyLiveRows,
    closeDialog,
    openCreate,
    openEdit,
    openRemove,
    openRestart,
    openSetup,
    submitCreate,
    submitEdit,
    submitRemove,
    submitRestart,
    submitSetup,
    start,
    stop,
    openFolder,
    openStderrLog,
    openPublicKey,
    regenerateKey,
    copyText
  };
}
