import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WorkspaceRow } from '$lib/api/server';

// Stub the network boundary; every store method funnels through these.
vi.mock('$lib/api/server', () => ({
  listWorkspaces: vi.fn(),
  createWorkspace: vi.fn(),
  updateWorkspace: vi.fn(),
  removeWorkspace: vi.fn(),
  restartWorkspace: vi.fn(),
  setupWorkspace: vi.fn(),
  startWorkspace: vi.fn(),
  stopWorkspace: vi.fn(),
  getWorkspacePublicKey: vi.fn(),
  regenerateWorkspaceKey: vi.fn(),
  openWorkspaceFolder: vi.fn(),
  openPath: vi.fn()
}));

vi.mock('$lib/runtime/feature-errors', () => ({
  featureErrorFrom: (err: unknown, fallback = 'Request failed.') => {
    if (err instanceof Error) return err.message;
    return fallback;
  }
}));

import * as api from '$lib/api/server';
import { createWorkspaceStore } from './workspace-store.svelte';

const wsRow = (over: Partial<WorkspaceRow> = {}): WorkspaceRow =>
  ({
    id: 'w1',
    name: 'work',
    path: '/ws/work',
    is_configured: true,
    running: false,
    is_default: false,
    is_current: false,
    gateway_url: null,
    http_port: 8080,
    admin_port: 8083,
    pid: null,
    autostart_method: null,
    stderr_log_exists: false,
    stderr_log_recent: false,
    stderr_log_mtime: null,
    stderr_log_size: 0,
    stderr_log_path: '/ws/work/stderr.log',
    ...over
  }) as WorkspaceRow;

function make() {
  const notify = vi.fn();
  const store = createWorkspaceStore(notify);
  return { store, notify };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listWorkspaces).mockResolvedValue({ data: [], hosting_workspace_id: null } as never);
});

describe('createWorkspaceStore — defaults', () => {
  it('starts loading, empty, with no dialog and zero derived counts', () => {
    const { store } = make();
    expect(store.loading).toBe(true);
    expect(store.rows).toEqual([]);
    expect(store.dialog).toBeNull();
    expect(store.configuredCount).toBe(0);
    expect(store.runningCount).toBe(0);
  });
});

describe('load', () => {
  it('populates rows + hosting id and clears loading/error on success', async () => {
    const { store } = make();
    vi.mocked(api.listWorkspaces).mockResolvedValue({
      data: [wsRow({ id: 'a' }), wsRow({ id: 'b' })],
      hosting_workspace_id: 'a'
    } as never);
    await store.load();
    expect(store.rows.map((r) => r.id)).toEqual(['a', 'b']);
    expect(store.hostingWorkspaceId).toBe('a');
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it('records the error message and stops loading on failure', async () => {
    const { store } = make();
    vi.mocked(api.listWorkspaces).mockRejectedValue(new Error('boom'));
    await store.load();
    expect(store.error).toBe('boom');
    expect(store.loading).toBe(false);
  });

  it('a silent load failure leaves prior error/loading untouched', async () => {
    const { store } = make();
    await store.load(); // success → error null, loading false
    vi.mocked(api.listWorkspaces).mockRejectedValue(new Error('later'));
    await store.load({ silent: true });
    expect(store.error).toBeNull();
    expect(store.loading).toBe(false);
  });
});

describe('applyLiveRows + derived counts', () => {
  it('adopts live rows/hosting/error and clears loading', () => {
    const { store } = make();
    store.applyLiveRows([wsRow({ id: 'x' })], 'x', 'sync-warn');
    expect(store.rows.map((r) => r.id)).toEqual(['x']);
    expect(store.hostingWorkspaceId).toBe('x');
    expect(store.error).toBe('sync-warn');
    expect(store.loading).toBe(false);
  });

  it('derives configured/running counts from the current rows', () => {
    const { store } = make();
    store.applyLiveRows(
      [
        wsRow({ id: '1', is_configured: true, running: true }),
        wsRow({ id: '2', is_configured: true, running: false }),
        wsRow({ id: '3', is_configured: false, running: false })
      ],
      null,
      null
    );
    expect(store.configuredCount).toBe(2);
    expect(store.runningCount).toBe(1);
  });

  it('still updates error even when the row set is unchanged', () => {
    const { store } = make();
    const rows = [wsRow({ id: 'x' })];
    store.applyLiveRows(rows, 'x', null);
    store.applyLiveRows([wsRow({ id: 'x' })], 'x', 'now-failing');
    expect(store.error).toBe('now-failing');
  });
});

describe('open* dialog flows seed the right form + selection', () => {
  it('openCreate opens a blank create form', () => {
    const { store } = make();
    store.openCreate();
    expect(store.dialog).toBe('create');
    expect(store.createForm).toEqual({ name: '', path: '' });
  });

  it('openEdit copies the row into the edit form', () => {
    const { store } = make();
    const row = wsRow({ name: 'prod', gateway_url: 'ws://h:1', is_default: true });
    store.openEdit(row);
    expect(store.dialog).toBe('edit');
    expect(store.selected).toBe(row);
    expect(store.editForm).toEqual({ name: 'prod', gatewayUrl: 'ws://h:1', setDefault: true });
  });

  it('openRestart pre-checks admin only for the hosting workspace', () => {
    const { store } = make();
    store.applyLiveRows([wsRow({ id: 'host' })], 'host', null);
    store.openRestart(wsRow({ id: 'host' }));
    expect(store.restartForm.admin).toBe(true);
    store.openRestart(wsRow({ id: 'other' }));
    expect(store.restartForm.admin).toBe(false);
  });
});

describe('submit flows', () => {
  it('submitCreate sends a trimmed path → null, notifies, resets, reloads', async () => {
    const { store, notify } = make();
    vi.mocked(api.createWorkspace).mockResolvedValue({ data: 'created' } as never);
    store.openCreate();
    store.createForm.name = 'work';
    store.createForm.path = '  ';
    await store.submitCreate();
    expect(api.createWorkspace).toHaveBeenCalledWith({ name: 'work', path: null });
    expect(notify).toHaveBeenCalledWith('success', 'created');
    expect(store.dialog).toBeNull();
    expect(api.listWorkspaces).toHaveBeenCalled();
  });

  it('submitEdit sends the selected id + previous display name', async () => {
    const { store } = make();
    vi.mocked(api.updateWorkspace).mockResolvedValue({ data: 'updated' } as never);
    store.openEdit(wsRow({ id: 'w9', name: 'old' }));
    store.editForm.name = 'new';
    store.editForm.gatewayUrl = 'ws://h:2';
    store.editForm.setDefault = true;
    await store.submitEdit();
    expect(api.updateWorkspace).toHaveBeenCalledWith('w9', {
      name: 'new',
      gateway_url: 'ws://h:2',
      set_default: true,
      previous_display_name: 'old'
    });
  });

  it('submitSetup stashes the public key and advances to the setup-key dialog', async () => {
    const { store } = make();
    vi.mocked(api.setupWorkspace).mockResolvedValue({ data: { desktop_pub: 'KEY==' } } as never);
    store.openSetup(wsRow({ id: 'w1' }));
    await store.submitSetup();
    expect(store.setupPublicKey).toBe('KEY==');
    expect(store.dialog).toBe('setup-key');
  });

  it('a failing submit notifies the error and keeps the dialog open', async () => {
    const { store, notify } = make();
    vi.mocked(api.createWorkspace).mockRejectedValue(new Error('nope'));
    store.openCreate();
    await store.submitCreate();
    expect(notify).toHaveBeenCalledWith('error', 'nope');
    expect(store.dialog).toBe('create');
  });
});

describe('start', () => {
  it('warns instead of success when the workspace was already running', async () => {
    const { store, notify } = make();
    vi.mocked(api.startWorkspace).mockResolvedValue({
      data: { already_running: true, name: 'work', pid: 42 }
    } as never);
    await store.start(wsRow());
    expect(notify).toHaveBeenCalledWith('warning', expect.stringContaining('already running'));
  });

  it('reports the PID on a fresh start', async () => {
    const { store, notify } = make();
    vi.mocked(api.startWorkspace).mockResolvedValue({
      data: { already_running: false, name: 'work', pid: 42 }
    } as never);
    await store.start(wsRow());
    expect(notify).toHaveBeenCalledWith('success', expect.stringContaining('PID 42'));
  });
});

describe('closeDialog busy guard', () => {
  it('is a no-op while a submit is in flight, then resets after it resolves', async () => {
    const { store } = make();
    let release!: (v: unknown) => void;
    vi.mocked(api.createWorkspace).mockReturnValue(new Promise((r) => (release = r)) as never);
    store.openCreate();
    const pending = store.submitCreate();
    expect(store.busy).toBe(true);
    store.closeDialog();
    expect(store.dialog).toBe('create'); // guard held
    release({ data: 'ok' });
    await pending;
    expect(store.dialog).toBeNull(); // reset on success
  });
});
