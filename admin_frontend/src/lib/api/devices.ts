import { apiRequest } from './client';

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

export async function listDevices() {
  return apiRequest<DeviceRow[]>('/devices');
}

export async function generateDevicePairingCode() {
  return apiRequest<DevicePairingData>('/devices/pairing-code', { method: 'POST' });
}

export async function revokeDevice(deviceId: string) {
  return apiRequest<string>(`/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' });
}
