import { apiRequest } from './client';

export type DeviceRow = {
  device_id: string;
  device_name: string | null;
  paired_at: string;
  expires_at: string | null;
  /** Whose it is (Permissions phase 3): it shows and writes only this person's conversations. */
  person_id: string;
  /** Their name, "" when they aren't in the family list. */
  person_name: string;
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

/** A pairing code for a person: the device approved with it is theirs. */
export async function generateDevicePairingCode(personId: string) {
  return apiRequest<DevicePairingData>('/devices/pairing-code', { method: 'POST', body: { person_id: personId || null } });
}

/** Say whose a paired device is. */
export async function setDevicePerson(deviceId: string, personId: string) {
  return apiRequest<string>(`/devices/${encodeURIComponent(deviceId)}/person`, {
    method: 'PUT',
    body: { person_id: personId }
  });
}

export async function revokeDevice(deviceId: string) {
  return apiRequest<string>(`/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' });
}
