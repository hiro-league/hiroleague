import {
  createGateway,
  listGateways,
  openPath,
  removeGateway,
  startGateway,
  stopGateway,
  type GatewayRow
} from '$lib/api/server';
import type { Notify } from './types';

const POLL_INTERVAL_MS = 5000;

export type GatewayDialog = 'create' | 'stop' | 'remove' | null;

export function createGatewayStore(notify: Notify) {
  let rows = $state<GatewayRow[]>([]);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let dialog = $state<GatewayDialog>(null);
  let selected = $state<GatewayRow | null>(null);
  let createForm = $state({
    name: '',
    desktopPublicKey: '',
    port: '',
    host: '0.0.0.0',
    makeDefault: false,
    skipAutostart: false,
    elevatedTask: false
  });
  let removeForm = $state({ purge: false });

  const runningCount = $derived(rows.filter((row) => row.running).length);

  function rowsChanged(nextRows: GatewayRow[]) {
    return JSON.stringify(rows) !== JSON.stringify(nextRows);
  }

  async function load(options: { silent?: boolean } = {}) {
    if (options.silent && busy) return;
    if (!options.silent) {
      loading = true;
    }
    try {
      const payload = await listGateways();
      if (rowsChanged(payload.data)) {
        rows = payload.data;
      }
      error = null;
    } catch (err) {
      if (!options.silent) {
        error = err instanceof Error ? err.message : 'Failed to load gateways.';
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
    dialog = null;
    selected = null;
  }

  function openCreate() {
    createForm = {
      name: '',
      desktopPublicKey: '',
      port: '',
      host: '0.0.0.0',
      makeDefault: false,
      skipAutostart: false,
      elevatedTask: false
    };
    dialog = 'create';
  }

  function openStop(row: GatewayRow) {
    selected = row;
    dialog = 'stop';
  }

  function openRemove(row: GatewayRow) {
    selected = row;
    removeForm = { purge: false };
    dialog = 'remove';
  }

  async function submitCreate() {
    busy = true;
    try {
      const result = await createGateway({
        name: createForm.name,
        desktop_public_key: createForm.desktopPublicKey,
        port: Number(createForm.port),
        host: createForm.host.trim() || '0.0.0.0',
        make_default: createForm.makeDefault,
        skip_autostart: createForm.skipAutostart,
        elevated_task: createForm.elevatedTask
      });
      notify('success', result.data ?? 'Gateway created.');
      closeDialog();
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Create gateway failed.');
    } finally {
      busy = false;
    }
  }

  async function start(row: GatewayRow) {
    busy = true;
    try {
      const result = await startGateway(row.name);
      notify(
        result.data.already_running ? 'warning' : 'success',
        result.data.already_running
          ? `Gateway '${row.name}' is already running.`
          : `Gateway '${row.name}' started (PID ${result.data.pid}).`
      );
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Start gateway failed.');
    } finally {
      busy = false;
    }
  }

  async function submitStop() {
    if (!selected) return;
    busy = true;
    try {
      const result = await stopGateway(selected.name);
      notify(
        result.data ? 'success' : 'warning',
        result.data
          ? `Gateway '${selected.name}' stopped.`
          : `Gateway '${selected.name}' was not running.`
      );
      closeDialog();
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Stop gateway failed.');
    } finally {
      busy = false;
    }
  }

  async function submitRemove() {
    if (!selected) return;
    busy = true;
    try {
      const result = await removeGateway(selected.name, removeForm.purge);
      notify('success', result.data ?? 'Gateway removed.');
      closeDialog();
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Remove gateway failed.');
    } finally {
      busy = false;
    }
  }

  async function openStderrLog(row: GatewayRow) {
    if (!row.stderr_log_exists) return;
    try {
      await openPath(row.stderr_log_path);
      notify('info', `Opening stderr log: ${row.stderr_log_path}`);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Open stderr log failed.');
    }
  }

  async function openFolder(row: GatewayRow) {
    try {
      await openPath(row.path);
      notify('info', `Opening folder: ${row.path}`);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Open folder failed.');
    }
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
    get dialog() {
      return dialog;
    },
    get selected() {
      return selected;
    },
    get createForm() {
      return createForm;
    },
    get removeForm() {
      return removeForm;
    },
    get runningCount() {
      return runningCount;
    },
    load,
    startPolling,
    closeDialog,
    openCreate,
    openStop,
    openRemove,
    submitCreate,
    start,
    submitStop,
    submitRemove,
    openStderrLog,
    openFolder
  };
}
