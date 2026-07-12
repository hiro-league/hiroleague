import {
  disableChannel,
  enableChannel,
  listChannels,
  type ChannelRow
} from '$lib/api/channels-devices';
import { isFeatureActive } from '$lib/shell/features';
import type { Notify } from '$lib/ui/toast-types';

export type ChannelsController = ReturnType<typeof createChannelsController>;

export function createChannelsController(notify: Notify) {
  let allRows = $state<ChannelRow[]>([]);
  let mandatoryChannelName = $state('');
  let loading = $state(true);
  let busyChannel = $state<string | null>(null);
  let error = $state<string | null>(null);

  // When the `devices` feature is hidden, the mandatory devices channel is dropped from the
  // Channels list entirely (its own tab is already gated) so first public builds show only
  // user-facing channels like WhatsApp.
  const devicesActive = isFeatureActive('devices');
  const rows = $derived(
    devicesActive ? allRows : allRows.filter((row) => row.name !== mandatoryChannelName)
  );

  const enabledCount = $derived(rows.filter((row) => row.enabled).length);

  async function load() {
    loading = true;
    error = null;
    try {
      const payload = await listChannels();
      allRows = payload.data.channels;
      mandatoryChannelName = payload.data.mandatory_channel_name;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load channels.';
    } finally {
      loading = false;
    }
  }

  async function toggle(row: ChannelRow) {
    busyChannel = row.name;
    try {
      // enable/disable return {enabled} now (they also hot-activate, §5.3) — the
      // message is composed here, not read from the payload.
      if (row.enabled) {
        await disableChannel(row.name);
      } else {
        await enableChannel(row.name);
      }
      notify('success', `Channel '${row.name}' ${row.enabled ? 'disabled' : 'enabled'}.`);
      await load();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Channel update failed.');
    } finally {
      busyChannel = null;
    }
  }

  function isMandatory(row: ChannelRow): boolean {
    return row.name === mandatoryChannelName;
  }

  function isBusy(row: ChannelRow): boolean {
    return busyChannel === row.name;
  }

  return {
    get rows() {
      return rows;
    },
    get mandatoryChannelName() {
      return mandatoryChannelName;
    },
    get loading() {
      return loading;
    },
    get busyChannel() {
      return busyChannel;
    },
    get error() {
      return error;
    },
    get enabledCount() {
      return enabledCount;
    },
    load,
    toggle,
    isMandatory,
    isBusy
  };
}
