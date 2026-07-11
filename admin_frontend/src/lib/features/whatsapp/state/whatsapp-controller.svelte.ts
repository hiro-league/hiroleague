import {
  disableWhatsApp,
  enableWhatsApp,
  getWhatsAppConfig,
  getWhatsAppQr,
  getWhatsAppStatus,
  logoutWhatsApp,
  reconnectWhatsApp,
  setWhatsAppConfig,
  type WhatsAppStatus
} from '$lib/api/whatsapp';
import { createPoller } from '$lib/state/create-poller.svelte';
import type { Notify } from '$lib/ui/toast-types';
import { sanitizeQrSvg } from '../shared/sanitize-qr-svg';

export type WhatsAppController = ReturnType<typeof createWhatsAppController>;

/** Human-readable explanation for a terminal/needs-action WhatsApp state. */
function whatsappStatusMessage(status: WhatsAppStatus | null): string {
  const detail = (status?.detail ?? {}) as Record<string, unknown>;
  const reason = typeof detail.reason === 'string' && detail.reason ? ` (${detail.reason})` : '';
  switch (status?.state) {
    case 'logged_out':
      return `WhatsApp unlinked this device${reason}. Scan the QR below to re-pair.`;
    case 'banned': {
      const expire = detail.expire ? ` until ${String(detail.expire)}` : '';
      return `WhatsApp temporarily banned this account${expire}. You'll need to wait it out, then re-pair.`;
    }
    case 'replaced':
      return 'Another linked WhatsApp Web/Desktop client took over this session. Scan the QR to re-link.';
    case 'error': {
      const msg = typeof detail.message === 'string' && detail.message ? `: ${detail.message}` : '';
      return `WhatsApp connection error${reason}${msg}. Retrying — re-pair if it persists.`;
    }
    default:
      return '';
  }
}

export function createWhatsAppController(notify: Notify) {
  let status = $state<WhatsAppStatus | null>(null);
  let qrSvg = $state('');
  let loading = $state(true);
  let saving = $state(false);
  let busy = $state(false); // a lifecycle action (enable/disable/logout/reconnect) is running
  let error = $state<string | null>(null);

  // Config form draft.
  let ownerNumber = $state('');
  let allowedSenders = $state(''); // comma/space-separated in the UI
  let sendReadReceipts = $state(true);
  let audioOut = $state(true); // relay TTS replies as WhatsApp voice notes (P7)

  const connected = $derived(status?.state === 'connected' || status?.state === 'paired');
  // Terminal / needs-action states: the session is unlinked or blocked, so the
  // user must re-pair (or wait out a ban) — reconnect alone won't recover it.
  const needsRepair = $derived(
    ['logged_out', 'banned', 'replaced', 'error'].includes(status?.state ?? '')
  );

  async function loadConfig() {
    const cfg = (await getWhatsAppConfig()).data.config;
    ownerNumber = cfg.owner_number == null ? '' : String(cfg.owner_number);
    const allowed = cfg.allowed_senders;
    allowedSenders = Array.isArray(allowed) ? allowed.map(String).join(', ') : '';
    sendReadReceipts = cfg.send_read_receipts !== false;
    audioOut = cfg.audio_out !== false;
  }

  async function refreshStatus() {
    status = (await getWhatsAppStatus()).data;
    qrSvg = status?.has_qr ? sanitizeQrSvg((await getWhatsAppQr()).data.qr_svg) : '';
  }

  async function load() {
    loading = true;
    error = null;
    try {
      await Promise.all([loadConfig(), refreshStatus()]);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load WhatsApp state.';
    } finally {
      loading = false;
    }
  }

  // Poll connection/QR so pairing and disconnects reflect live. Wire via
  // `$effect(() => ctrl.startPolling())` so it disposes on unmount.
  function startPolling(): () => void {
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
      const allowed = allowedSenders
        .split(/[,\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      await setWhatsAppConfig('owner_number', ownerNumber.trim());
      await setWhatsAppConfig('allowed_senders', allowed);
      await setWhatsAppConfig('send_read_receipts', sendReadReceipts);
      await setWhatsAppConfig('audio_out', audioOut);
      notify('success', 'WhatsApp settings saved. Restart the server to apply.');
      await loadConfig();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Failed to save settings.');
    } finally {
      saving = false;
    }
  }

  async function runAction(fn: () => Promise<unknown>, okMsg: string, failMsg: string) {
    busy = true;
    try {
      await fn();
      await refreshStatus();
      notify('success', okMsg);
    } catch (err) {
      notify('error', err instanceof Error ? err.message : failMsg);
    } finally {
      busy = false;
    }
  }

  const enable = () => runAction(enableWhatsApp, 'WhatsApp enabled.', 'Failed to enable.');
  const disable = () => runAction(disableWhatsApp, 'WhatsApp disabled.', 'Failed to disable.');
  const logout = () =>
    runAction(logoutWhatsApp, 'Logged out — scan the new QR to re-pair.', 'Failed to log out.');
  const reconnect = () => runAction(reconnectWhatsApp, 'Reconnecting…', 'Failed to reconnect.');

  return {
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
      return whatsappStatusMessage(status);
    },
    get enabled() {
      return status?.enabled ?? false;
    },
    get ownerNumber() {
      return ownerNumber;
    },
    set ownerNumber(v: string) {
      ownerNumber = v;
    },
    get allowedSenders() {
      return allowedSenders;
    },
    set allowedSenders(v: string) {
      allowedSenders = v;
    },
    get sendReadReceipts() {
      return sendReadReceipts;
    },
    set sendReadReceipts(v: boolean) {
      sendReadReceipts = v;
    },
    get audioOut() {
      return audioOut;
    },
    set audioOut(v: boolean) {
      audioOut = v;
    },
    load,
    save,
    startPolling,
    enable,
    disable,
    logout,
    reconnect
  };
}
