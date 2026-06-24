import {
  createGateway,
  listGateways,
  openPath,
  removeGateway,
  startGateway,
  stopGateway,
  type GatewayRow
} from '$lib/api/server';
import { createMutation, createResource } from '$lib/state/create-resource.svelte';
import type { Notify } from '$lib/ui/toast-types';

export type GatewayDialog = 'create' | 'stop' | 'remove' | null;

export function createGatewayStore(notify: Notify) {
  const listResource = createResource(
    async (): Promise<GatewayRow[]> => {
      const payload = await listGateways();
      return payload.data;
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
  let busy = $state(false);

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
    if (options.silent && busy) return;
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
    if (busy) return;
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
    busy = true;
    try {
      await createMutation(
        () =>
          createGateway({
            name: createForm.name,
            desktop_public_key: createForm.desktopPublicKey,
            port: Number(createForm.port),
            host: createForm.host.trim() || '0.0.0.0',
            make_default: createForm.makeDefault,
            skip_autostart: createForm.skipAutostart,
            elevated_task: createForm.elevatedTask
          }),
        {
          notify,
          successMsg: (result) => result.data ?? 'Gateway created.',
          errorPrefix: 'Create gateway failed.',
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

  async function start(row: GatewayRow) {
    busy = true;
    try {
      await createMutation(() => startGateway(row.name), {
        notify,
        successMsg: (result) =>
          result.data.already_running
            ? undefined
            : `Gateway '${row.name}' started (PID ${result.data.pid}).`,
        errorPrefix: 'Start gateway failed.',
        onDone: async (result) => {
          if (result.data.already_running) {
            notify('warning', `Gateway '${row.name}' is already running.`);
          }
          await load();
        }
      }).run();
    } finally {
      busy = false;
    }
  }

  async function submitStop() {
    if (!selected) return;
    busy = true;
    try {
      await createMutation(() => stopGateway(selected!.name), {
        notify,
        successMsg: (result) =>
          result.data ? `Gateway '${selected!.name}' stopped.` : undefined,
        errorPrefix: 'Stop gateway failed.',
        onDone: async (result) => {
          if (!result.data) {
            notify('warning', `Gateway '${selected!.name}' was not running.`);
          }
          resetDialog();
          await load();
        }
      }).run();
    } finally {
      busy = false;
    }
  }

  async function submitRemove() {
    if (!selected) return;
    busy = true;
    try {
      await createMutation(() => removeGateway(selected!.name, removeForm.purge), {
        notify,
        successMsg: (result) => result.data ?? 'Gateway removed.',
        errorPrefix: 'Remove gateway failed.',
        onDone: async () => {
          resetDialog();
          await load();
        }
      }).run();
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
      return listResource.data;
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
