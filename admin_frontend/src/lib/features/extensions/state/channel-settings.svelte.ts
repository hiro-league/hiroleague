import { errorMessage } from '$kit/api/client';
import { Action } from '$kit/state/action.svelte';
import { Draft } from '$kit/state/draft.svelte';
import { svgImage } from '$kit/format/svg';
import type { Notify } from '$kit/ui/toast.svelte';
import {
  channelAction,
  getChannelConfig,
  getChannelDescriptor,
  getChannelPairing,
  getChannelStatus,
  setChannelConfig,
  type ChannelStatus
} from '$lib/api/extensions';
import { channelNeedsRepair, channelStatusMessage } from '../shared/channel-status-message';
import { draftValue, fieldsFromSchema, parseDraftValue, secretIsSet, type FieldSpec } from '../shared/schema-form';

export type ChannelSettings = ReturnType<typeof createChannelSettings>;

type FormValues = Record<string, string | boolean>;

/** The words on a declared action's button; any other shows its own name. */
const ACTION_LABELS: Record<string, string> = { logout: 'Log out', reconnect: 'Reconnect' };

/**
 * One channel's Settings panel: its account (live status, the QR code to link it, its declared actions) and its
 * settings form, drawn from the schema the plugin declared. Generic across channels (design §5.5): nothing here
 * names WhatsApp. Made when the panel opens, for one channel.
 */
export function createChannelSettings(name: string, notify: Notify) {
  let fields = $state<FieldSpec[]>([]);
  let capabilities = $state<Record<string, unknown> | null>(null);
  let status = $state<ChannelStatus | null>(null);
  let qrSvg = $state('');
  let loadError = $state<string | null>(null);
  let loaded = $state(false);
  /** Which secret fields hold a value in the keyring now (they read back as a marker, never the value). */
  let secretSet = $state<Record<string, boolean>>({});
  const actionRun = new Action();

  const form = new Draft<FormValues>(
    {},
    {
      // The panel's EditorSheet asks before changes are lost.
      guard: false,
      save: async (values) => {
        let wrote = false;
        let applied = false;
        for (const field of fields) {
          const value = values[field.key];
          if (field.secret) {
            // A secret is written only when a new one was typed; blank leaves it as it is.
            if (typeof value === 'string' && value.trim() !== '') {
              applied = (await setChannelConfig(name, field.key, value)).applied ?? false;
              wrote = true;
            }
          } else if (value !== form.saved?.[field.key]) {
            applied = (await setChannelConfig(name, field.key, parseDraftValue(field, value))).applied ?? false;
            wrote = true;
          }
        }
        // The server applies a change to a running channel at once; otherwise at its next start.
        notify(
          'success',
          !wrote
            ? 'No changes to save.'
            : applied
              ? 'Settings saved and applied to the running channel.'
              : 'Settings saved. They apply when the channel is switched on.'
        );
        return await readConfig();
      }
    }
  );

  const linked = $derived(['connected', 'paired', 'ready'].includes(status?.state ?? ''));
  const pairingKind = $derived(String((capabilities?.pairing as string) ?? ''));
  const actions = $derived(((capabilities?.actions as string[]) ?? []).filter(Boolean));

  async function readConfig(): Promise<FormValues> {
    const config = (await getChannelConfig(name)).config;
    const values: FormValues = {};
    const set: Record<string, boolean> = {};
    for (const field of fields) {
      values[field.key] = draftValue(field, config);
      if (field.secret) set[field.key] = secretIsSet(field, config);
    }
    secretSet = set;
    return values;
  }

  /** The account's live state, and its QR code while it waits to be linked. */
  async function refreshStatus() {
    try {
      status = await getChannelStatus(name);
      qrSvg = status.has_qr ? (await getChannelPairing(name)).qr_svg : '';
    } catch (err) {
      // A missed round shows the last state; the next round tries again.
      loadError = errorMessage(err);
    }
  }

  async function load() {
    loadError = null;
    try {
      const descriptor = await getChannelDescriptor(name);
      fields = fieldsFromSchema(descriptor.config_schema);
      capabilities = descriptor.capabilities;
      form.load(await readConfig(), true);
      await refreshStatus();
    } catch (err) {
      loadError = errorMessage(err);
    } finally {
      loaded = true;
    }
  }

  async function runAction(action: string) {
    await actionRun.run(async () => {
      await channelAction(name, action);
      await refreshStatus();
      notify('success', `${ACTION_LABELS[action] ?? action}: asked.`);
    });
    if (actionRun.error) notify('error', actionRun.error);
  }

  async function clearSecret(key: string) {
    try {
      await setChannelConfig(name, key, null);
      form.load(await readConfig(), true);
      notify('success', `${key} cleared.`);
    } catch (err) {
      notify('error', errorMessage(err));
    }
  }

  return {
    name,
    form,
    get fields() {
      return fields;
    },
    get secretSet() {
      return secretSet;
    },
    get loaded() {
      return loaded;
    },
    get error() {
      return loadError;
    },
    get status() {
      return status;
    },
    get linked() {
      return linked;
    },
    get needsRepair() {
      return channelNeedsRepair(status?.state);
    },
    get repairMessage() {
      return channelStatusMessage(status);
    },
    get pairingKind() {
      return pairingKind;
    },
    /** The QR code as an image source, while the account waits to be linked; '' otherwise. */
    get qrImage() {
      return qrSvg && !linked ? svgImage(qrSvg) : '';
    },
    get actions() {
      return actions;
    },
    actionLabel: (action: string) => ACTION_LABELS[action] ?? action,
    get acting() {
      return actionRun.busy;
    },
    load,
    refreshStatus,
    runAction,
    clearSecret
  };
}
