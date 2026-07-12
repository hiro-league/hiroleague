import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChannelRow } from '$lib/api/channels-devices';

vi.mock('$lib/api/channels-devices', () => ({
  listChannels: vi.fn(),
  enableChannel: vi.fn(),
  disableChannel: vi.fn()
}));

import * as api from '$lib/api/channels-devices';
import { createChannelsController } from './channels-controller.svelte';

const channelRow = (over: Partial<ChannelRow> = {}): ChannelRow => ({
  name: 'devices',
  enabled: true,
  command: 'python -m devices',
  config_keys: ['token'],
  ...over
});

function make() {
  const notify = vi.fn();
  const ctrl = createChannelsController(notify);
  return { ctrl, notify };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listChannels).mockResolvedValue({
    data: { channels: [], mandatory_channel_name: 'devices' }
  } as never);
});

describe('createChannelsController — defaults', () => {
  it('starts loading with empty rows and zero enabled count', () => {
    const { ctrl } = make();
    expect(ctrl.loading).toBe(true);
    expect(ctrl.rows).toEqual([]);
    expect(ctrl.error).toBeNull();
    expect(ctrl.enabledCount).toBe(0);
    expect(ctrl.busyChannel).toBeNull();
  });
});

describe('load', () => {
  it('populates rows, mandatory channel, and clears loading on success', async () => {
    const { ctrl } = make();
    vi.mocked(api.listChannels).mockResolvedValue({
      data: {
        channels: [channelRow({ name: 'a', enabled: true }), channelRow({ name: 'b', enabled: false })],
        mandatory_channel_name: 'a'
      }
    } as never);
    await ctrl.load();
    expect(ctrl.rows.map((r) => r.name)).toEqual(['a', 'b']);
    expect(ctrl.mandatoryChannelName).toBe('a');
    expect(ctrl.enabledCount).toBe(1);
    expect(ctrl.loading).toBe(false);
    expect(ctrl.error).toBeNull();
  });

  it('records the error message on failure', async () => {
    const { ctrl } = make();
    vi.mocked(api.listChannels).mockRejectedValue(new Error('channels down'));
    await ctrl.load();
    expect(ctrl.error).toBe('channels down');
    expect(ctrl.loading).toBe(false);
  });
});

describe('isMandatory / isBusy', () => {
  it('flags the mandatory channel name from the last load', async () => {
    const { ctrl } = make();
    vi.mocked(api.listChannels).mockResolvedValue({
      data: {
        channels: [channelRow({ name: 'devices' }), channelRow({ name: 'telegram' })],
        mandatory_channel_name: 'devices'
      }
    } as never);
    await ctrl.load();
    expect(ctrl.isMandatory(ctrl.rows[0]!)).toBe(true);
    expect(ctrl.isMandatory(ctrl.rows[1]!)).toBe(false);
  });
});

describe('toggle', () => {
  it('disables an enabled channel, notifies, and reloads', async () => {
    const { ctrl, notify } = make();
    const row = channelRow({ name: 'telegram', enabled: true });
    vi.mocked(api.disableChannel).mockResolvedValue({ data: { enabled: false } } as never);
    vi.mocked(api.listChannels).mockResolvedValue({
      data: { channels: [row], mandatory_channel_name: 'devices' }
    } as never);

    await ctrl.toggle(row);

    expect(api.disableChannel).toHaveBeenCalledWith('telegram');
    expect(notify).toHaveBeenCalledWith('success', "Channel 'telegram' disabled.");
    expect(api.listChannels).toHaveBeenCalledTimes(1);
    expect(ctrl.busyChannel).toBeNull();
  });

  it('enables a disabled channel', async () => {
    const { ctrl, notify } = make();
    const row = channelRow({ name: 'telegram', enabled: false });
    vi.mocked(api.enableChannel).mockResolvedValue({ data: null } as never);
    vi.mocked(api.listChannels).mockResolvedValue({
      data: { channels: [row], mandatory_channel_name: 'devices' }
    } as never);

    await ctrl.toggle(row);

    expect(api.enableChannel).toHaveBeenCalledWith('telegram');
    expect(notify).toHaveBeenCalledWith('success', "Channel 'telegram' enabled.");
  });

  it('notifies on failure without leaving busyChannel set', async () => {
    const { ctrl, notify } = make();
    const row = channelRow({ enabled: true });
    vi.mocked(api.disableChannel).mockRejectedValue(new Error('nope'));

    await ctrl.toggle(row);

    expect(notify).toHaveBeenCalledWith('error', 'nope');
    expect(ctrl.busyChannel).toBeNull();
  });

  it('marks the row busy for the duration of toggle', async () => {
    const { ctrl } = make();
    const row = channelRow({ name: 'x', enabled: true });
    let busyDuringCall = false;
    vi.mocked(api.disableChannel).mockImplementation(async () => {
      busyDuringCall = ctrl.isBusy(row);
      return { data: 'ok' } as never;
    });
    vi.mocked(api.listChannels).mockResolvedValue({
      data: { channels: [row], mandatory_channel_name: 'devices' }
    } as never);

    await ctrl.toggle(row);

    expect(busyDuringCall).toBe(true);
    expect(ctrl.isBusy(row)).toBe(false);
  });
});
