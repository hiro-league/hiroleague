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

export type ChannelConfigData = { config: Record<string, unknown> };

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

/**
 * Install the channel's plugin package (`uv tool install hiro-channel-<name>`), a one-time
 * provisioning step before enable. It builds an isolated env and can pull large native deps
 * (e.g. neonize's Go lib + ffmpeg), so it may run for minutes — hence the long timeout.
 */
export async function installChannel(name: string) {
  return apiRequest<{ package: string; output: string }>(
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
