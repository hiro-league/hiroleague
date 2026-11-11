import {
  createGateway,
  listGateways,
  openPath,
  removeGateway,
  startGateway,
  stopGateway,
  type GatewayRow
} from '$lib/api/server';
import { createResource } from '$lib/state/create-resource.svelte';
import { Action } from '$kit/state/action.svelte';
import { errorMessage } from '$kit/api/client';
import type { Notify } from '$kit/ui/toast.svelte';

export type GatewayDialog = 'create' | 'stop' | 'remove' | null;

export function createGatewayStore(notify: Notify) {
  const listResource = createResource(
    async (): Promise<GatewayRow[]> => {
      const payload = await listGateways();
      return payload;
    },
    {
      initial: [],
      initialLoading: true,
      errorPrefix: 'Failed to load gateways.'
    }
  );

  let error = $state<string | null>(null);
  let hydrated = $state(false);
  let dialog = $state<GatewayDialog>(null);
  let selected = $state<GatewayRow | null>(null);
  /** One thing at a time: the create / start / stop / remove in progress (its failure is told by a toast). */
  const work = new Action();

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

  const runningCount = $derived(listResource.data.filter((row) => row.running).length);

  function rowsChanged(nextRows: GatewayRow[]) {
    return JSON.stringify(listResource.data) !== JSON.stringify(nextRows);
  }

  async function load(options: { silent?: boolean } = {}) {
    if (options.silent && work.busy) return;
    await listResource.load({ silent: options.silent });
    if (!options.silent) {
      error = listResource.error;
    }
    hydrated = true;
  }

  function applyLiveRows(nextRows: GatewayRow[], nextError: string | null) {
    if (rowsChanged(nextRows)) {
      listResource.replace(nextRows);
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
    const result = await work.run(async () => {
      const done = await createGateway({
        name: createForm.name,
        desktop_public_key: createForm.desktopPublicKey,
        port: Number(createForm.port),
        host: createForm.host.trim() || '0.0.0.0',
        make_default: createForm.makeDefault,
        skip_autostart: createForm.skipAutostart,
        elevated_task: createForm.elevatedTask
      });
      resetDialog();
      await load();
      return done;
    });
    if (work.error) notify('error', work.error);
    else notify('success', result ?? 'Gateway created.');
  }

  async function start(row: GatewayRow) {
    const result = await work.run(async () => {
      const started = await startGateway(row.name);
      await load();
      return started;
    });
    if (work.error) notify('error', work.error);
    else if (result?.already_running) notify('warning', `Gateway '${row.name}' is already running.`);
    else if (result) notify('success', `Gateway '${row.name}' started (PID ${result.pid}).`);
  }

  async function submitStop() {
    if (!selected) return;
    const { name } = selected;
    const stopped = await work.run(async () => {
      const result = await stopGateway(name);
      resetDialog();
      await load();
      return result;
    });
    if (work.error) notify('error', work.error);
    else if (stopped) notify('success', `Gateway '${name}' stopped.`);
    else notify('warning', `Gateway '${name}' was not running.`);
  }

  async function submitRemove() {
    if (!selected) return;
    const { name } = selected;
    const result = await work.run(async () => {
      const done = await removeGateway(name, removeForm.purge);
      resetDialog();
      await load();
      return done;
    });
    if (work.error) notify('error', work.error);
    else notify('success', result ?? 'Gateway removed.');
  }

  async function openStderrLog(row: GatewayRow) {
    if (!row.stderr_log_exists) return;
    try {
      await openPath(row.stderr_log_path);
      notify('info', `Opening stderr log: ${row.stderr_log_path}`);
    } catch (err) {
      notify('error', errorMessage(err));
    }
  }

  async function openFolder(row: GatewayRow) {
    try {
      await openPath(row.path);
      notify('info', `Opening folder: ${row.path}`);
    } catch (err) {
      notify('error', errorMessage(err));
    }
  }

  return {
    get rows() {
      return listResource.data;
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
    get removeForm() {
      return removeForm;
    },
    get runningCount() {
      return runningCount;
    },
    load,
    applyLiveRows,
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
