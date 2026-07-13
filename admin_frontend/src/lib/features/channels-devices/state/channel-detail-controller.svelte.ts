import {
  channelAction,
  disableChannel,
  enableChannel,
  getChannelConfig,
  getChannelDescriptor,
  getChannelPairing,
  getChannelStatus,
  installChannel,
  setChannelConfig,
  type ChannelStatus
} from '$lib/api/channels-devices';
import { createPoller } from '$lib/state/create-poller.svelte';
import type { Notify } from '$lib/ui/toast-types';
import { channelNeedsRepair, channelStatusMessage } from '../shared/channel-status-message';
import { sanitizePairingQrSvg } from '../shared/sanitize-pairing-qr-svg';
import { draftValue, fieldsFromSchema, parseDraftValue, secretIsSet, type FieldSpec } from '../shared/schema-form';

export type ChannelDetailController = ReturnType<typeof createChannelDetailController>;

type DraftValue = string | boolean;

/**
 * Generic per-channel management state (design §5.5): loads the channel's declared
 * schema + capabilities + live status, drives the schema form, pairing, and the
 * capability actions — with no channel-specific code.
 */
export function createChannelDetailController(name: string, notify: Notify, onChanged?: () => void) {
  let fields = $state<FieldSpec[]>([]);
  let capabilities = $state<Record<string, unknown> | null>(null);
  let status = $state<ChannelStatus | null>(null);
  let qrSvg = $state('');
  let loading = $state(true);
  let saving = $state(false);
  let busy = $state(false);
  let installing = $state(false); // uv tool install in flight (can run for minutes)
  let error = $state<string | null>(null);

  // Editable field values, bound by the form. Baseline is the last-loaded snapshot;
  // secretSet records which secret fields currently hold a keyring value.
  const draft = $state<Record<string, DraftValue>>({});
  let baseline: Record<string, DraftValue> = {};
  const secretSet = $state<Record<string, boolean>>({});

  const connected = $derived(status?.state === 'connected' || status?.state === 'paired');
  const needsRepair = $derived(channelNeedsRepair(status?.state));
  const pairingKind = $derived(String((capabilities?.pairing as string) ?? 'none'));
  const actions = $derived(((capabilities?.actions as string[]) ?? []).filter(Boolean));

  function seedDraft(config: Record<string, unknown>) {
    for (const field of fields) {
      const value = draftValue(field, config);
      draft[field.key] = value;
      baseline[field.key] = value;
      if (field.secret) secretSet[field.key] = secretIsSet(field, config);
    }
  }

  async function loadConfig() {
    const config = (await getChannelConfig(name)).data.config;
    seedDraft(config);
  }

  async function refreshStatus() {
    status = (await getChannelStatus(name)).data;
    qrSvg = status?.has_qr ? sanitizePairingQrSvg((await getChannelPairing(name)).data.qr_svg) : '';
  }

  async function load() {
    loading = true;
    error = null;
    try {
      const descriptor = (await getChannelDescriptor(name)).data;
      fields = fieldsFromSchema(descriptor.config_schema);
      capabilities = descriptor.capabilities;
      baseline = {};
      await Promise.all([loadConfig(), refreshStatus()]);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load channel.';
    } finally {
      loading = false;
    }
  }

  // Poll status/QR so pairing + disconnects reflect live, only while the channel
  // reports a live status (capabilities.live_status).
  function startPolling(): () => void {
    if (!(capabilities?.live_status ?? true)) return () => {};
    const poller = createPoller(() => refreshStatus(), {
      intervalMs: 2500,
      immediate: false,
      pauseWhenHidden: true
    });
    return poller.start();
  }

  async function save() {
    saving = true;
    try {
      for (const field of fields) {
        const value = draft[field.key];
        if (field.secret) {
          // Only write a secret when a new value was typed; blank = leave unchanged.
          if (typeof value === 'string' && value.trim() !== '') {
            await setChannelConfig(name, field.key, value);
          }
        } else if (value !== baseline[field.key]) {
          await setChannelConfig(name, field.key, parseDraftValue(field, value));
        }
      }
      notify('success', 'Settings saved. Restart the server to apply.');
      await loadConfig();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to save settings.');
    } finally {
      saving = false;
    }
  }

  async function clearSecret(key: string) {
    try {
      await setChannelConfig(name, key, null);
      draft[key] = '';
      secretSet[key] = false;
      notify('success', `${key} cleared.`);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : `Failed to clear ${key}.`);
    }
  }

  async function runLifecycle(fn: () => Promise<unknown>, okMsg: string, failMsg: string) {
    busy = true;
    try {
      await fn();
      await refreshStatus();
      onChanged?.();
      notify('success', okMsg);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : failMsg);
    } finally {
      busy = false;
    }
  }

  // Install is separate from the enable/disable lifecycle: it provisions the plugin package
  // (uv tool install) and can run for minutes, so it uses its own `installing` flag rather
  // than the shared `busy` used by the instant lifecycle actions.
  async function install() {
    installing = true;
    try {
      const res = await installChannel(name);
      notify('success', `Installed ${res.data.package}. You can now enable the channel.`);
      await refreshStatus();
      onChanged?.();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to install the channel plugin.');
    } finally {
      installing = false;
    }
  }

  const enable = () => runLifecycle(() => enableChannel(name), 'Channel enabled.', 'Failed to enable.');
  const disable = () => runLifecycle(() => disableChannel(name), 'Channel disabled.', 'Failed to disable.');
  const runAction = (action: string) =>
    runLifecycle(() => channelAction(name, action), `${action} requested.`, `Failed to ${action}.`);

  return {
    name,
    get fields() {
      return fields;
    },
    get draft() {
      return draft;
    },
    get secretSet() {
      return secretSet;
    },
    get status() {
      return status;
    },
    get qrSvg() {
      return qrSvg;
    },
    get loading() {
      return loading;
    },
    get saving() {
      return saving;
    },
    get busy() {
      return busy;
    },
    get installing() {
      return installing;
    },
    get error() {
      return error;
    },
    get connected() {
      return connected;
    },
    get needsRepair() {
      return needsRepair;
    },
    get statusMessage() {
      return channelStatusMessage(status);
    },
    get pairingKind() {
      return pairingKind;
    },
    get actions() {
      return actions;
    },
    get enabled() {
      return status?.enabled ?? false;
    },
    load,
    startPolling,
    save,
    clearSecret,
    install,
    enable,
    disable,
    runAction
  };
}
