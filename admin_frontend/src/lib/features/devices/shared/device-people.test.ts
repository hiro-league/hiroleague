import { describe, expect, it } from 'vitest';
import type { DeviceRow } from '$lib/api/devices';
import type { Person } from '$lib/api/people';
import { devicesOf, ownerOf, personOptions } from './device-people';

const person = (person_id: string, role_ids: string[]): Person => ({
  person_id,
  name: person_id.toUpperCase(),
  calls_them: '',
  whatsapp: '',
  role_id: role_ids[0],
  role_ids,
  sign_in: null,
  has_sign_in: false,
  created_at: '',
  updated_at: ''
});

const device = (device_id: string, person_id: string): DeviceRow => ({
  device_id,
  device_name: device_id,
  paired_at: '',
  expires_at: null,
  person_id,
  person_name: ''
});

describe('device-people', () => {
  const people = [person('mona', ['adult']), person('misho', ['adult', 'owner'])];

  it('finds the owner among several roles', () => {
    expect(ownerOf(people)?.person_id).toBe('misho');
    expect(ownerOf([people[0]])).toBeUndefined();
  });

  it('offers everyone by name', () => {
    expect(personOptions(people)).toEqual([
      { value: 'mona', label: 'MONA' },
      { value: 'misho', label: 'MISHO' }
    ]);
  });

  it('gives each person their own devices', () => {
    const devices = [device('a', 'mona'), device('b', 'misho'), device('c', 'mona')];
    expect(devicesOf(devices, 'mona').map((d) => d.device_id)).toEqual(['a', 'c']);
  });
});
