// mockup: Permissions phase 3 ("Hiro per person"). Whose each paired device is, until the core keeps a device's
// person. Pure: the Devices page and the People page read the same mock.
import type { DeviceRow } from '$lib/api/devices';
import type { Person } from '$lib/api/people';

/** A device and the person it belongs to. */
export type OwnedDevice = DeviceRow & { person_id: string; mock: boolean };

/** A person made for a device several people use (Michel's decision): a mock one, with a role of its own. */
export const HALLWAY: Pick<Person, 'person_id' | 'name'> = { person_id: 'mock-hallway', name: 'Hallway' };

/** The owner: every device paired before phase 3 becomes theirs. */
export function ownerOf(people: readonly Person[]): Person | undefined {
  return people.find((p) => p.role_ids.includes('owner'));
}

const firstWith = (people: readonly Person[], role: string) => people.find((p) => p.role_ids.includes(role));

/** Mock devices for the three cases: the owner's, another person's (an adult on the web version, a kid), a shared
 *  one. Shown when no device is paired; a case with nobody to hold it is left out. */
export function mockDevices(people: readonly Person[]): OwnedDevice[] {
  const owner = ownerOf(people);
  const adult = firstWith(people, 'adult');
  const kid = firstWith(people, 'kid');
  const rows: [string, string, Person | typeof HALLWAY | undefined, string][] = [
    ['mock-device-1', 'SM-S908E', owner, '2026-11-20T12:13:00Z'],
    ['mock-device-2', 'Chrome on Windows', adult, '2026-11-21T18:40:00Z'],
    ['mock-device-3', 'Pixel 7a', kid, '2026-11-22T09:05:00Z'],
    ['mock-device-4', 'Hallway tablet', HALLWAY, '2026-11-23T16:30:00Z']
  ];
  return rows
    .filter(([, , person]) => person)
    .map(([device_id, device_name, person, paired_at]) => ({
      device_id,
      device_name,
      paired_at,
      expires_at: null,
      person_id: person?.person_id ?? '',
      mock: true
    }));
}

/** Real devices, each the owner's (what phase 3 does to the devices paired before it), else the mock ones. */
export function ownedDevices(rows: readonly DeviceRow[], people: readonly Person[]): OwnedDevice[] {
  if (rows.length === 0) return mockDevices(people);
  const owner = ownerOf(people)?.person_id ?? '';
  return rows.map((row) => ({ ...row, person_id: owner, mock: false }));
}
