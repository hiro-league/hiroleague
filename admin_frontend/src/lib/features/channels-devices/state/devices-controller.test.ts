import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DevicePairingData, DeviceRow } from '$lib/api/channels-devices';

vi.mock('$lib/api/channels-devices', () => ({
  listDevices: vi.fn(),
  generateDevicePairingCode: vi.fn(),
  revokeDevice: vi.fn()
}));

import * as api from '$lib/api/channels-devices';
import { createDevicesController } from './devices-controller.svelte';

const deviceRow = (over: Partial<DeviceRow> = {}): DeviceRow => ({
  device_id: 'dev-abc123456789',
  device_name: 'Phone',
  paired_at: '2026-06-19T10:00:00Z',
  expires_at: '2027-06-19T10:00:00Z',
  ...over
});

const pairingData = (over: Partial<DevicePairingData> = {}): DevicePairingData => ({
  code: '123456',
  expires_at: '2026-06-19T11:00:00Z',
  gateway_url: 'wss://gw.example',
  qr_payload: 'pair-payload',
  qr_svg: '<svg></svg>',
  ...over
});

function make() {
  const notify = vi.fn();
  const ctrl = createDevicesController(notify);
  return { ctrl, notify };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listDevices).mockResolvedValue({ data: [] } as never);
  vi.stubGlobal('navigator', {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) }
  });
  vi.stubGlobal('window', {
    setTimeout: vi.fn(() => 99),
    clearTimeout: vi.fn()
  });
});

describe('createDevicesController — defaults', () => {
  it('starts loading with empty rows and closed dialogs', () => {
    const { ctrl } = make();
    expect(ctrl.loading).toBe(true);
    expect(ctrl.rows).toEqual([]);
    expect(ctrl.error).toBeNull();
    expect(ctrl.pairing).toBeNull();
    expect(ctrl.revokeTarget).toBeNull();
    expect(ctrl.busy).toBe(false);
    expect(ctrl.copied).toBe(false);
    expect(ctrl.revokeDisplayName).toBe('');
  });
});

describe('load', () => {
  it('populates rows and clears loading on success', async () => {
    const { ctrl } = make();
    vi.mocked(api.listDevices).mockResolvedValue({ data: [deviceRow()] } as never);
    await ctrl.load();
    expect(ctrl.rows).toHaveLength(1);
    expect(ctrl.loading).toBe(false);
    expect(ctrl.error).toBeNull();
  });

  it('records the error message on failure', async () => {
    const { ctrl } = make();
    vi.mocked(api.listDevices).mockRejectedValue(new Error('devices down'));
    await ctrl.load();
    expect(ctrl.error).toBe('devices down');
    expect(ctrl.loading).toBe(false);
  });
});

describe('generatePairingCode', () => {
  it('opens pairing dialog data and reloads the list', async () => {
    const { ctrl } = make();
    const pairing = pairingData();
    vi.mocked(api.generateDevicePairingCode).mockResolvedValue({ data: pairing } as never);
    vi.mocked(api.listDevices).mockResolvedValue({ data: [deviceRow()] } as never);

    await ctrl.generatePairingCode();

    expect(ctrl.pairing).toEqual(pairing);
    expect(api.listDevices).toHaveBeenCalledTimes(1);
    expect(ctrl.busy).toBe(false);
  });

  it('notifies on failure', async () => {
    const { ctrl, notify } = make();
    vi.mocked(api.generateDevicePairingCode).mockRejectedValue(new Error('pair fail'));
    await ctrl.generatePairingCode();
    expect(notify).toHaveBeenCalledWith('error', 'pair fail');
    expect(ctrl.pairing).toBeNull();
  });
});

describe('revoke flow', () => {
  it('openRevoke sets target and revokeDisplayName', () => {
    const { ctrl } = make();
    const row = deviceRow({ device_name: 'Tablet' });
    ctrl.openRevoke(row);
    expect(ctrl.revokeTarget).toEqual(row);
    expect(ctrl.revokeDisplayName).toBe('Tablet');
  });

  it('submitRevoke calls API, notifies, clears target, and reloads', async () => {
    const { ctrl, notify } = make();
    const row = deviceRow();
    ctrl.openRevoke(row);
    vi.mocked(api.revokeDevice).mockResolvedValue({ data: 'revoked' } as never);
    vi.mocked(api.listDevices).mockResolvedValue({ data: [] } as never);

    await ctrl.submitRevoke();

    expect(api.revokeDevice).toHaveBeenCalledWith(row.device_id);
    expect(notify).toHaveBeenCalledWith('success', 'revoked');
    expect(ctrl.revokeTarget).toBeNull();
    expect(ctrl.busy).toBe(false);
  });

  it('closeRevoke is ignored while busy', async () => {
    const { ctrl } = make();
    ctrl.openRevoke(deviceRow());
    vi.mocked(api.revokeDevice).mockImplementation(
      () => new Promise(() => {
        /* hang */
      })
    );
    void ctrl.submitRevoke();
    expect(ctrl.busy).toBe(true);
    ctrl.closeRevoke();
    expect(ctrl.revokeTarget).not.toBeNull();
  });
});

describe('copyPairingPayload', () => {
  it('copies qr_payload and notifies on success', async () => {
    const { ctrl, notify } = make();
    vi.mocked(api.generateDevicePairingCode).mockResolvedValue({
      data: pairingData({ qr_payload: 'payload-xyz' })
    } as never);
    await ctrl.generatePairingCode();
    await ctrl.copyPairingPayload();

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('payload-xyz');
    expect(notify).toHaveBeenCalledWith('success', 'Pairing message copied to clipboard.');
    expect(ctrl.copied).toBe(true);
  });

  it('no-ops when pairing is closed', async () => {
    const { ctrl, notify } = make();
    await ctrl.copyPairingPayload();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });

  it('notifies on clipboard failure', async () => {
    const { ctrl, notify } = make();
    vi.mocked(api.generateDevicePairingCode).mockResolvedValue({
      data: pairingData()
    } as never);
    await ctrl.generatePairingCode();
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(new Error('denied'));
    await ctrl.copyPairingPayload();
    expect(notify).toHaveBeenCalledWith('error', 'Copy failed.');
  });
});

describe('closePairing', () => {
  it('clears pairing and copy feedback when not busy', async () => {
    const { ctrl } = make();
    vi.mocked(api.generateDevicePairingCode).mockResolvedValue({
      data: pairingData()
    } as never);
    await ctrl.generatePairingCode();
    await ctrl.copyPairingPayload();
    expect(ctrl.copied).toBe(true);
    ctrl.closePairing();
    expect(ctrl.pairing).toBeNull();
    expect(ctrl.copied).toBe(false);
    expect(window.clearTimeout).toHaveBeenCalled();
  });
});
