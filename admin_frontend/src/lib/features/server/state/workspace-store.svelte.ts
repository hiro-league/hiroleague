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
import { createResource } from '$lib/state/create-resource.svelte';
import { Action } from '$kit/state/action.svelte';
import { errorMessage } from '$kit/api/client';
import type { Notify } from '$kit/ui/toast.svelte';

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
      // Step 1d: the rows and the hosting id are one answer ({workspaces, hosting_workspace_id}).
      return {
        rows: payload.workspaces,
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
  /** One thing at a time: the create / edit / remove / restart / setup / start / stop / key in progress (its failure is told by a toast). */
  const work = new Action();

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
    if (options.silent && work.busy) return;
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
    if (work.busy) return;
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
    const result = await work.run(async () => {
      const done = await createWorkspace({
        name: createForm.name,
        path: createForm.path.trim() || null
      });
      resetDialog();
      await load();
      return done;
    });
    if (work.error) notify('error', work.error);
    else notify('success', result ?? 'Workspace created.');
  }

  async function submitEdit() {
    if (!selected) return;
    const row = selected;
    const result = await work.run(async () => {
      const done = await updateWorkspace(row.id, {
        name: editForm.name.trim() || null,
        gateway_url: editForm.gatewayUrl.trim() || null,
        set_default: editForm.setDefault,
        previous_display_name: row.name
      });
      resetDialog();
      await load();
      return done;
    });
    if (work.error) notify('error', work.error);
    else notify('success', result ?? 'Workspace updated.');
  }

  async function submitRemove() {
    if (!selected) return;
    const row = selected;
    const result = await work.run(async () => {
      const done = await removeWorkspace(row.id, removeForm.purge);
      resetDialog();
      await load();
      return done;
    });
    if (work.error) notify('error', work.error);
    else notify('success', result ?? 'Workspace removed.');
  }

  async function submitRestart() {
    if (!selected) return;
    const row = selected;
    await work.run(async () => {
      await restartWorkspace(row.id, restartForm.admin);
      resetDialog();
      await load();
    });
    if (work.error) notify('error', work.error);
    else
      notify(
        'success',
        row.id === listResource.data.hostingWorkspaceId
          ? 'Restarting current workspace. The admin UI should return shortly.'
          : `Workspace '${row.name}' restarted.`
      );
  }

  async function submitSetup() {
    if (!selected) return;
    const row = selected;
    await work.run(async () => {
      const result = await setupWorkspace(row.id, {
        gateway_url: setupForm.gatewayUrl,
        http_port: setupForm.httpPort.trim() ? Number(setupForm.httpPort) : null,
        skip_autostart: setupForm.skipAutostart,
        start_server: setupForm.startServer,
        elevated_task: setupForm.elevatedTask
      });
      setupPublicKey = result.desktop_pub;
      dialog = 'setup-key';
      await load();
    });
    if (work.error) notify('error', work.error);
  }

  async function start(row: WorkspaceRow) {
    const result = await work.run(async () => {
      const started = await startWorkspace(row.id);
      await load();
      return started;
    });
    if (work.error) notify('error', work.error);
    else if (result?.already_running) notify('warning', `'${result.name}' is already running.`);
    else if (result) notify('success', `'${result.name}' started (PID ${result.pid}).`);
  }

  async function stop(row: WorkspaceRow) {
    const result = await work.run(async () => {
      const done = await stopWorkspace(row.id);
      await load();
      return done;
    });
    if (work.error) notify('error', work.error);
    else notify('success', result ?? `'${row.name}' stopped.`);
  }

  async function openFolder(row: WorkspaceRow) {
    try {
      await openWorkspaceFolder(row.path);
      notify('info', `Opening folder: ${row.path}`);
    } catch (err) {
      notify('error', errorMessage(err));
    }
  }

  async function openStderrLog(row: WorkspaceRow) {
    if (!row.stderr_log_exists) return;
    try {
      await openPath(row.stderr_log_path);
      notify('info', `Opening stderr log: ${row.stderr_log_path}`);
    } catch (err) {
      notify('error', errorMessage(err));
    }
  }

  async function openPublicKey(row: WorkspaceRow) {
    selected = row;
    await work.run(async () => {
      publicKey = await getWorkspacePublicKey(row.id);
      dialog = 'public-key';
    });
    if (work.error) notify('error', work.error);
  }

  async function regenerateKey() {
    if (!selected) return;
    const row = selected;
    await work.run(async () => {
      publicKey = await regenerateWorkspaceKey(row.id);
    });
    if (work.error) notify('error', work.error);
    else notify('warning', `New key generated for '${row.name}'. Update your gateway.`);
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
      return work.busy;
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
