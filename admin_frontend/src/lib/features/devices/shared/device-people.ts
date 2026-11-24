// Permissions phase 3: whose a device is. Pure: the Devices page and the People page read it.
import type { DeviceRow } from '$lib/api/devices';
import type { Person } from '$lib/api/people';
import type { PickOption } from '$kit/ui/pick';

/** The owner: whose a device paired is when nobody else is picked. */
export function ownerOf(people: readonly Person[]): Person | undefined {
  return people.find((p) => p.role_ids.includes('owner'));
}

/** Everyone a device may belong to, by name. */
export function personOptions(people: readonly Person[]): PickOption[] {
  return people.map((p) => ({ value: p.person_id, label: p.name }));
}

/** A person's devices. */
export function devicesOf(devices: readonly DeviceRow[], personId: string): DeviceRow[] {
  return devices.filter((d) => d.person_id === personId);
}
