import type { DeviceRow } from '$lib/api/channels-devices';

/** ISO timestamp → admin table display (UTC suffix, space-separated date/time). */
export function formatDeviceTimestamp(value: string | null): string {
  return value ? value.replace('T', ' ').replace('Z', ' UTC') : '-';
}

export function displayDeviceName(row: DeviceRow): string {
  if (row.device_name) return row.device_name;
  return row.device_id.length > 12 ? `${row.device_id.slice(0, 12)}...` : row.device_id;
}
