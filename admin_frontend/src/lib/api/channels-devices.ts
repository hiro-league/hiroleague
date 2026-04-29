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

export async function enableChannel(name: string) {
  return apiRequest<string>(`/channels/${encodeURIComponent(name)}/enable`, { method: 'POST' });
}

export async function disableChannel(name: string) {
  return apiRequest<string>(`/channels/${encodeURIComponent(name)}/disable`, { method: 'POST' });
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
