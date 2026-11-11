import { errorMessage } from '$kit/api/client';
import { Action } from '$kit/state/action.svelte';
import {
  channelAction,
  disableChannel,
  enableChannel,
  getChannelConfig,
  getChannelDescriptor,
  getChannelPairing,
  getChannelStatus,
  setChannelConfig,
  uninstallChannel,
  type ChannelStatus
} from '$lib/api/channels-devices';
import { createPoller } from '$lib/state/create-poller.svelte';
import type { Notify } from '$kit/ui/toast.svelte';
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
  const settingsSave = new Action();
  const lifecycle = new Action(); // enable / disable / a capability action
  const teardown = new Action(); // full teardown (uninstall)
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
    const config = (await getChannelConfig(name)).config;
    seedDraft(config);
  }

  async function refreshStatus() {
    status = (await getChannelStatus(name));
    qrSvg = status?.has_qr ? sanitizePairingQrSvg((await getChannelPairing(name)).qr_svg) : '';
  }

  // The descriptor (config schema + capabilities → the settings form, pairing pane and
  // action buttons) only exists once the plugin has registered, which can be a few
  // seconds after Enable. Track whether we have it so the poller can keep trying.
  let descriptorLoaded = false;
  async function loadDescriptor() {
    const descriptor = (await getChannelDescriptor(name));
    fields = fieldsFromSchema(descriptor.config_schema);
    capabilities = descriptor.capabilities;
    if (descriptor.capabilities) descriptorLoaded = true;
  }

  async function load() {
    loading = true;
    error = null;
    try {
      await loadDescriptor();
      baseline = {};
      await Promise.all([loadConfig(), refreshStatus()]);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }

  // Poll status/QR live. Until the descriptor has loaded (plugin registered), also
  // re-fetch it while the channel is enabled — so the QR pane, actions and settings
  // form appear on their own after Enable, with no manual refresh.
  async function poll() {
    await refreshStatus();
    if (!descriptorLoaded && (status?.enabled ?? false)) {
      await loadDescriptor();
      if (descriptorLoaded) await loadConfig();
    }
  }

  function startPolling(): () => void {
    if (!(capabilities?.live_status ?? true)) return () => {};
    const poller = createPoller(() => poll(), {
      intervalMs: 2500,
      immediate: false,
      pauseWhenHidden: true
    });
    return poller.start();
  }

  async function save() {
    await settingsSave.run(async () => {
      let wrote = false;
      let applied = false;
      for (const field of fields) {
        const value = draft[field.key];
        if (field.secret) {
          // Only write a secret when a new value was typed; blank = leave unchanged.
          if (typeof value === 'string' && value.trim() !== '') {
            applied = (await setChannelConfig(name, field.key, value)).applied ?? false;
            wrote = true;
          }
        } else if (value !== baseline[field.key]) {
          applied = (await setChannelConfig(name, field.key, parseDraftValue(field, value)))
            .applied ?? false;
          wrote = true;
        }
      }
      // The server live-applies to a running plugin (applied=true); otherwise the change
      // lands on the next Enable/start.
      notify(
        'success',
        !wrote
          ? 'No changes to save.'
          : applied
            ? 'Settings saved and applied to the running channel.'
            : 'Settings saved. Enable the channel to apply.'
      );
      await loadConfig();
    });
    if (settingsSave.error) notify('error', settingsSave.error);
  }

  async function clearSecret(key: string) {
    try {
      await setChannelConfig(name, key, null);
      draft[key] = '';
      secretSet[key] = false;
      notify('success', `${key} cleared.`);
    } catch (err) {
      notify('error', errorMessage(err));
    }
  }

  async function runLifecycle(fn: () => Promise<unknown>, okMsg: string) {
    await lifecycle.run(async () => {
      await fn();
      await refreshStatus();
      onChanged?.();
      notify('success', okMsg);
    });
    if (lifecycle.error) notify('error', lifecycle.error);
  }

  // Full teardown (inverse of Install): stop + delete config + uv uninstall. Returns true
  // so the caller can navigate back to the list (the channel no longer exists).
  async function uninstall(): Promise<boolean> {
    await teardown.run(async () => {
      const res = await uninstallChannel(name);
      notify(
        'success',
        res.uninstalled
          ? `Uninstalled '${name}' and removed its package.`
          : `Uninstalled '${name}' (package left in place).`
      );
      onChanged?.();
    });
    if (teardown.error) notify('error', teardown.error);
    return !teardown.error;
  }

  const enable = () => runLifecycle(() => enableChannel(name), 'Channel enabled.');
  const disable = () => runLifecycle(() => disableChannel(name), 'Channel disabled.');
  const runAction = (action: string) =>
    runLifecycle(() => channelAction(name, action), `${action} requested.`);

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
      return settingsSave.busy;
    },
    get busy() {
      return lifecycle.busy;
    },
    get uninstalling() {
      return teardown.busy;
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
    uninstall,
    enable,
    disable,
    runAction
  };
}
