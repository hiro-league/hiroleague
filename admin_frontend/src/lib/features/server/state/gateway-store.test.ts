import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GatewayRow } from '$lib/api/server';

vi.mock('$lib/api/server', () => ({
  listGateways: vi.fn(),
  createGateway: vi.fn(),
  startGateway: vi.fn(),
  stopGateway: vi.fn(),
  removeGateway: vi.fn(),
  openPath: vi.fn()
}));

import * as api from '$lib/api/server';
import { createGatewayStore } from './gateway-store.svelte';

const gwRow = (over: Partial<GatewayRow> = {}): GatewayRow =>
  ({
    name: 'main',
    path: '/gw/main',
    host: '0.0.0.0',
    port: 8765,
    running: false,
    is_default: false,
    pid: null,
    autostart_method: null,
    stderr_log_exists: false,
    stderr_log_recent: false,
    stderr_log_mtime: null,
    stderr_log_size: 0,
    stderr_log_path: '/gw/main/stderr.log',
    ...over
  }) as GatewayRow;

function make() {
  const notify = vi.fn();
  const store = createGatewayStore(notify);
  return { store, notify };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listGateways).mockResolvedValue({ data: [] } as never);
});

describe('createGatewayStore — defaults & load', () => {
  it('starts loading and empty with zero running', () => {
    const { store } = make();
    expect(store.loading).toBe(true);
    expect(store.rows).toEqual([]);
    expect(store.runningCount).toBe(0);
  });

  it('load populates rows and clears loading/error', async () => {
    const { store } = make();
    vi.mocked(api.listGateways).mockResolvedValue({
      data: [gwRow({ name: 'a', running: true }), gwRow({ name: 'b' })]
    } as never);
    await store.load();
    expect(store.rows.map((r) => r.name)).toEqual(['a', 'b']);
    expect(store.runningCount).toBe(1);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it('a silent load failure leaves prior error/loading untouched', async () => {
    const { store } = make();
    await store.load();
    vi.mocked(api.listGateways).mockRejectedValue(new Error('later'));
    await store.load({ silent: true });
    expect(store.error).toBeNull();
    expect(store.loading).toBe(false);
  });
});

describe('open* dialog flows', () => {
  it('openCreate resets the form with the 0.0.0.0 host default', () => {
    const { store } = make();
    store.openCreate();
    expect(store.dialog).toBe('create');
    expect(store.createForm.host).toBe('0.0.0.0');
    expect(store.createForm.name).toBe('');
  });

  it('openStop / openRemove select the row and open the right dialog', () => {
    const { store } = make();
    const row = gwRow({ name: 'g1' });
    store.openStop(row);
    expect(store.dialog).toBe('stop');
    expect(store.selected).toBe(row);
    store.openRemove(row);
    expect(store.dialog).toBe('remove');
    expect(store.removeForm.purge).toBe(false);
  });
});

describe('submit flows', () => {
  it('submitCreate coerces the port to a number and falls back the host', async () => {
    const { store, notify } = make();
    vi.mocked(api.createGateway).mockResolvedValue({ data: 'created' } as never);
    store.openCreate();
    store.createForm.name = 'main';
    store.createForm.desktopPublicKey = 'KEY==';
    store.createForm.port = '8765';
    store.createForm.host = '   ';
    await store.submitCreate();
    expect(api.createGateway).toHaveBeenCalledWith({
      name: 'main',
      desktop_public_key: 'KEY==',
      port: 8765,
      host: '0.0.0.0',
      make_default: false,
      skip_autostart: false,
      elevated_task: false
    });
    expect(notify).toHaveBeenCalledWith('success', 'created');
    expect(store.dialog).toBeNull();
  });

  it('submitStop warns when the gateway was not running', async () => {
    const { store, notify } = make();
    vi.mocked(api.stopGateway).mockResolvedValue({ data: false } as never);
    store.openStop(gwRow({ name: 'g1' }));
    await store.submitStop();
    expect(notify).toHaveBeenCalledWith('warning', expect.stringContaining('was not running'));
  });

  it('submitStop confirms a successful stop', async () => {
    const { store, notify } = make();
    vi.mocked(api.stopGateway).mockResolvedValue({ data: true } as never);
    store.openStop(gwRow({ name: 'g1' }));
    await store.submitStop();
    expect(notify).toHaveBeenCalledWith('success', expect.stringContaining('stopped'));
    expect(store.dialog).toBeNull();
  });

  it('submitRemove forwards the purge flag', async () => {
    const { store } = make();
    vi.mocked(api.removeGateway).mockResolvedValue({ data: 'removed' } as never);
    store.openRemove(gwRow({ name: 'g1' }));
    store.removeForm.purge = true;
    await store.submitRemove();
    expect(api.removeGateway).toHaveBeenCalledWith('g1', true);
  });
});

describe('start', () => {
  it('warns when already running, reports PID otherwise', async () => {
    const { store, notify } = make();
    vi.mocked(api.startGateway).mockResolvedValue({ data: { already_running: true, pid: 7 } } as never);
    await store.start(gwRow({ name: 'g1' }));
    expect(notify).toHaveBeenCalledWith('warning', expect.stringContaining('already running'));

    vi.mocked(api.startGateway).mockResolvedValue({ data: { already_running: false, pid: 7 } } as never);
    await store.start(gwRow({ name: 'g1' }));
    expect(notify).toHaveBeenCalledWith('success', expect.stringContaining('PID 7'));
  });
});
