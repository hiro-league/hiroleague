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
import type { Notify } from './types';

const POLL_INTERVAL_MS = 5000;

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
  let rows = $state<WorkspaceRow[]>([]);
  let hostingWorkspaceId = $state<string | null>(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let dialog = $state<WorkspaceDialog>(null);
  let selected = $state<WorkspaceRow | null>(null);

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

  const configuredCount = $derived(rows.filter((row) => row.is_configured).length);
  const runningCount = $derived(rows.filter((row) => row.running).length);

  function rowsChanged(nextRows: WorkspaceRow[], nextHostingWorkspaceId: string | null) {
    return (
      hostingWorkspaceId !== nextHostingWorkspaceId ||
      JSON.stringify(rows) !== JSON.stringify(nextRows)
    );
  }

  async function load(options: { silent?: boolean } = {}) {
    if (options.silent && busy) return;
    if (!options.silent) {
      loading = true;
    }
    try {
      const payload = await listWorkspaces();
      const nextRows = payload.data;
      const nextHostingWorkspaceId = payload.hosting_workspace_id ?? null;
      if (rowsChanged(nextRows, nextHostingWorkspaceId)) {
        rows = nextRows;
        hostingWorkspaceId = nextHostingWorkspaceId;
      }
      error = null;
    } catch (err) {
      if (!options.silent) {
        error = err instanceof Error ? err.message : 'Failed to load workspaces.';
      }
    } finally {
      if (!options.silent) {
        loading = false;
      }
    }
  }

  function startPolling() {
    const id = window.setInterval(() => {
      void load({ silent: true });
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
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
      setDefault: false
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
    restartForm = { admin: row.id === hostingWorkspaceId };
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
      const result = await createWorkspace({
        name: createForm.name,
        path: createForm.path.trim() || null
      });
      notify('success', result.data ?? 'Workspace created.');
      resetDialog();
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Create failed.');
    } finally {
      busy = false;
    }
  }

  async function submitEdit() {
    if (!selected) return;
    busy = true;
    try {
      const result = await updateWorkspace(selected.id, {
        name: editForm.name.trim() || null,
        gateway_url: editForm.gatewayUrl.trim() || null,
        set_default: editForm.setDefault,
        previous_display_name: selected.name
      });
      notify('success', result.data ?? 'Workspace updated.');
      resetDialog();
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Update failed.');
    } finally {
      busy = false;
    }
  }

  async function submitRemove() {
    if (!selected) return;
    busy = true;
    try {
      const result = await removeWorkspace(selected.id, removeForm.purge);
      notify('success', result.data ?? 'Workspace removed.');
      resetDialog();
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Remove failed.');
    } finally {
      busy = false;
    }
  }

  async function submitRestart() {
    if (!selected) return;
    busy = true;
    try {
      await restartWorkspace(selected.id, restartForm.admin);
      notify(
        'success',
        selected.id === hostingWorkspaceId
          ? 'Restarting current workspace. The admin UI should return shortly.'
          : `Workspace '${selected.name}' restarted.`
      );
      resetDialog();
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Restart failed.');
    } finally {
      busy = false;
    }
  }

  async function submitSetup() {
    if (!selected) return;
    busy = true;
    try {
      const result = await setupWorkspace(selected.id, {
        gateway_url: setupForm.gatewayUrl,
        http_port: setupForm.httpPort.trim() ? Number(setupForm.httpPort) : null,
        skip_autostart: setupForm.skipAutostart,
        start_server: setupForm.startServer,
        elevated_task: setupForm.elevatedTask
      });
      setupPublicKey = result.data.desktop_pub;
      dialog = 'setup-key';
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Setup failed.');
    } finally {
      busy = false;
    }
  }

  async function start(row: WorkspaceRow) {
    busy = true;
    try {
      const result = await startWorkspace(row.id);
      notify(
        result.data.already_running ? 'warning' : 'success',
        result.data.already_running
          ? `'${result.data.name}' is already running.`
          : `'${result.data.name}' started (PID ${result.data.pid}).`
      );
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Start failed.');
    } finally {
      busy = false;
    }
  }

  async function stop(row: WorkspaceRow) {
    busy = true;
    try {
      const result = await stopWorkspace(row.id);
      notify('success', result.data ?? `'${row.name}' stopped.`);
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Stop failed.');
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
      return rows;
    },
    get hostingWorkspaceId() {
      return hostingWorkspaceId;
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
    startPolling,
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
