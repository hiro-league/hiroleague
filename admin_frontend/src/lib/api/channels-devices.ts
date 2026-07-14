import { apiRequest } from './client';

export type ChannelRow = {
  name: string;
  enabled: boolean;
  command: string;
  config_keys: string[];
};

export type ChannelListData = {
  channels: ChannelRow[];
  mandatory_channel_name: string;
};

/** An installable channel from the catalog, not yet configured in this workspace. */
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
  /** POST /config only: true when the change was live-pushed to the running plugin. */
  applied?: boolean;
};

export type DeviceRow = {
  device_id: string;
  device_name: string | null;
  paired_at: string;
  expires_at: string | null;
};

export type DevicePairingData = {
  code: string;
  expires_at: string;
  gateway_url: string;
  qr_payload: string;
  qr_svg: string;
};

export async function listChannels() {
  return apiRequest<ChannelListData>('/channels');
}

/** Installable channels (catalog minus already-configured) for the "Add a channel" picker. */
export async function listAvailableChannels() {
  return apiRequest<{ channels: AvailableChannel[] }>('/channels/available');
}

/**
 * Install a channel in one step: `uv tool install hiro-channel-<name>` (isolated env, may pull
 * large native deps like neonize's Go lib + ffmpeg), then write its config so it joins the
 * managed list (disabled). No separate "add" step. Long timeout — install can run for minutes.
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

/** Uninstall = inverse of install: stop the plugin, delete its config, uninstall the package. */
export async function uninstallChannel(name: string) {
  return apiRequest<{ uninstalled: boolean }>(
    `/channels/${encodeURIComponent(name)}/uninstall`,
    { method: 'POST', timeoutMs: 120000 }
  );
}

// --- Generic per-channel admin (design §5.3): status / pairing / descriptor / config / actions ---

export async function getChannelStatus(name: string) {
  return apiRequest<ChannelStatus>(`/channels/${encodeURIComponent(name)}/status`);
}

export async function getChannelPairing(name: string) {
  return apiRequest<ChannelPairing>(`/channels/${encodeURIComponent(name)}/pairing`);
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

/** Trigger a declared admin action (e.g. logout, reconnect) — forwarded as channel.<action>. */
export async function channelAction(name: string, action: string) {
  return apiRequest<{ requested: boolean; action: string }>(
    `/channels/${encodeURIComponent(name)}/action/${encodeURIComponent(action)}`,
    { method: 'POST' }
  );
}

export async function listDevices() {
  return apiRequest<DeviceRow[]>('/devices');
}

export async function generateDevicePairingCode() {
  return apiRequest<DevicePairingData>('/devices/pairing-code', { method: 'POST' });
}

export async function revokeDevice(deviceId: string) {
  return apiRequest<string>(`/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' });
}
