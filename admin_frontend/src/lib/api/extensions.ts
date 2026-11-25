import { apiRequest } from './client';

/** Something an app offers other apps or Hiro: one of its `knows` or `can_do` entries. */
export type ExtensionOffer = { name: string; says: string };

/**
 * One extension of the one list, a channel plugin or an app (the route's `ExtensionRow`), with its live
 * connection when the server runs here.
 */
export type ExtensionRow = {
  extension_id: string;
  name: string;
  /** The name people read: an app's site title, a channel's catalog label. */
  label: string;
  kind: 'channel' | 'app';
  version: string;
  description: string;
  paired_at: string | null;
  last_seen: string | null;
  relays_chat: boolean;
  started_by_core: boolean;
  /** A started extension's switch; null for an app. */
  enabled: boolean | null;
  /** The channel phones' chat needs: it can't be switched off or removed. */
  mandatory: boolean;
  /** Its settings form, kept in the core. */
  has_settings: boolean;
  /** How its account is linked ("qr"), or "" when it has none. */
  pairing: string;
  site: string;
  offers: ExtensionOffer[];
  uses: string[];
  connected: boolean;
  connected_at: string | null;
  remote: string | null;
  /** A channel with an account: whether it is linked now (null when it has none, or the server isn't here). */
  linked: boolean | null;
  account: string;
  /** Permissions phase 8: an app never answered (it gets nothing it asks for). */
  pending: boolean;
  /** An app with something that waits for the owner's yes, and how many items. */
  waits: boolean;
  waiting_count: number;
};

/** Where extensions connect: the configured address plus what the running server does. */
export type ExtensionListen = {
  host: string;
  port: number;
  address: string;
  changed: boolean;
  restart_required: boolean;
  note: string;
  /** null when this workspace's server isn't the one running here. */
  listening: boolean | null;
  error: string | null;
  /** The address the running server listens on (differs from `host` until a restart). */
  live_host: string | null;
};

export type ExtensionListData = {
  listen: ExtensionListen;
  extensions: ExtensionRow[];
};

export type ExtensionPairingData = {
  code: string;
  expires_at: string;
  address: string;
  /** A code that pairs one paired app again: its name ("" = a code for a new app). */
  pairs_again: string;
};

export type ExtensionAddressData = Omit<ExtensionListen, 'listening' | 'error' | 'live_host'>;

export type ExtensionInfoData = {
  info: { name: string; version: string; description?: string };
  elapsed_ms: number;
};

export async function listExtensions(signal?: AbortSignal) {
  return apiRequest<ExtensionListData>('/extensions', { signal });
}

export async function generateExtensionPairingCode() {
  return apiRequest<ExtensionPairingData>('/extensions/pairing-code', { method: 'POST' });
}

/** A code for one paired app that lost its key: it pairs again keeping its rights, AI picks and LAN name. */
export async function pairExtensionAgain(extensionId: string) {
  return apiRequest<ExtensionPairingData>(`/extensions/${encodeURIComponent(extensionId)}/pair-again`, {
    method: 'POST'
  });
}

/** Remove one extension: an app is forgotten; a channel loses its settings and its program is uninstalled. */
export async function removeExtension(extensionId: string) {
  return apiRequest<{ message: string }>(`/extensions/${encodeURIComponent(extensionId)}`, {
    method: 'DELETE',
    timeoutMs: 120000
  });
}

export async function setExtensionAddress(host: string) {
  return apiRequest<ExtensionAddressData>('/extensions/address', {
    method: 'PUT',
    body: { host }
  });
}

/** The core's test call: ask a connected extension for its name and version. */
export async function askExtensionInfo(extensionId: string) {
  return apiRequest<ExtensionInfoData>(`/extensions/${encodeURIComponent(extensionId)}/info`, {
    method: 'POST'
  });
}

// --- Permissions phase 8: what an app is approved for (the route's AppApproval) ---

/** One thing an app asks: a permission, its subject (the app asked, the address, "name:port"), in the owner's words. */
export type ApprovalItem = {
  permission: string;
  subject: string;
  words: string;
  required: boolean;
  why: string;
  approved: boolean;
  waiting: boolean;
  understood: boolean;
};

export type AppApproval = {
  extension_id: string;
  name: string;
  approved_for_everything: boolean;
  pending: boolean;
  waits: boolean;
  items: ApprovalItem[];
  claimed: string[];
};

export async function getExtensionApproval(extensionId: string, signal?: AbortSignal) {
  return apiRequest<AppApproval>(`/extensions/${encodeURIComponent(extensionId)}/approval`, { signal });
}

/** The owner's yes: every required item, and the optional ones switched on ("permission" or "permission:subject"). */
export async function approveExtension(extensionId: string, optional: string[]) {
  return apiRequest<AppApproval>(`/extensions/${encodeURIComponent(extensionId)}/approval`, {
    method: 'PUT',
    body: { optional }
  });
}

// --- What only a channel has, by name: its switch, its settings, its account, installing one ---

export type AvailableChannel = {
  name: string;
  label: string;
  description: string;
  package: string;
};

export type ChannelCapabilities = {
  pairing?: string;
  actions?: string[];
  live_status?: boolean;
  state_machine?: string[];
};

export type ChannelStatus = {
  state: string;
  account: string;
  has_qr: boolean;
  enabled: boolean;
  state_at: string | null;
  detail?: Record<string, unknown>;
  capabilities?: ChannelCapabilities | null;
};

export type ChannelPairing = { kind: string; qr_svg: string; qr_at: string | null };

export type ChannelDescriptorData = {
  config_schema: Record<string, unknown> | null;
  capabilities: ChannelCapabilities | null;
  version: string;
};

export type ChannelConfigData = {
  config: Record<string, unknown>;
  /** True when the change was applied live to the running channel. */
  applied?: boolean;
};

/** The channels not installed yet, for Install a channel. */
export async function listAvailableChannels() {
  return apiRequest<{ channels: AvailableChannel[] }>('/channels/available');
}

/**
 * Install a channel in one step: `uv tool install hiro-channel-<name>` (isolated env, may pull
 * large native deps like neonize's Go lib + ffmpeg), then write its config so it joins the
 * list (switched off). Long timeout: an install can run for minutes.
 */
export async function installChannel(name: string) {
  return apiRequest<{ package: string; name: string; enabled: boolean }>(
    `/channels/${encodeURIComponent(name)}/install`,
    { method: 'POST', body: {}, timeoutMs: 600000 }
  );
}

export async function enableChannel(name: string) {
  return apiRequest<{ enabled: boolean }>(`/channels/${encodeURIComponent(name)}/enable`, {
    method: 'POST'
  });
}

export async function disableChannel(name: string) {
  return apiRequest<{ enabled: boolean }>(`/channels/${encodeURIComponent(name)}/disable`, {
    method: 'POST'
  });
}

export async function getChannelStatus(name: string, signal?: AbortSignal) {
  return apiRequest<ChannelStatus>(`/channels/${encodeURIComponent(name)}/status`, { signal });
}

export async function getChannelPairing(name: string, signal?: AbortSignal) {
  return apiRequest<ChannelPairing>(`/channels/${encodeURIComponent(name)}/pairing`, { signal });
}

export async function getChannelDescriptor(name: string) {
  return apiRequest<ChannelDescriptorData>(`/channels/${encodeURIComponent(name)}/descriptor`);
}

export async function getChannelConfig(name: string) {
  return apiRequest<ChannelConfigData>(`/channels/${encodeURIComponent(name)}/config`);
}

/** Set a single config key (value: any JSON; null unsets). Secrets route to the keyring (§5.6). */
export async function setChannelConfig(name: string, key: string, value: unknown) {
  return apiRequest<ChannelConfigData>(`/channels/${encodeURIComponent(name)}/config`, {
    method: 'POST',
    body: { key, value }
  });
}

/** A declared admin action (logout, reconnect), forwarded as channel.<action>. */
export async function channelAction(name: string, action: string) {
  return apiRequest<{ requested: boolean; action: string }>(
    `/channels/${encodeURIComponent(name)}/action/${encodeURIComponent(action)}`,
    { method: 'POST' }
  );
}
