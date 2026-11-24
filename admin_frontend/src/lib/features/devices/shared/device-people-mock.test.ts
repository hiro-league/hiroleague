// mockup: Permissions phase 3, whose each device is
import { describe, expect, it } from 'vitest';
import type { Person } from '$lib/api/people';
import { HALLWAY, mockDevices, ownedDevices } from './device-people-mock';

const person = (person_id: string, role_ids: string[]): Person => ({
  person_id,
  name: person_id,
  calls_them: '',
  whatsapp: '',
  role_id: role_ids[0],
  role_ids,
  sign_in: null,
  has_sign_in: false,
  created_at: '',
  updated_at: ''
});

const people = [person('misho', ['owner']), person('joe', ['adult']), person('mark', ['kid'])];

describe('device-people-mock', () => {
  it('makes a device paired before phase 3 the owner’s', () => {
    const rows = [{ device_id: 'd1', device_name: 'zozo', paired_at: '', expires_at: null }];
    expect(ownedDevices(rows, people)).toEqual([{ ...rows[0], person_id: 'misho', mock: false }]);
  });

  it('shows the owner’s, an adult’s, a kid’s and a shared device when none is paired', () => {
    expect(ownedDevices([], people).map((d) => d.person_id)).toEqual(['misho', 'joe', 'mark', HALLWAY.person_id]);
  });

  it('leaves out a case nobody holds', () => {
    expect(mockDevices([people[0]]).map((d) => d.person_id)).toEqual(['misho', HALLWAY.person_id]);
  });
});
