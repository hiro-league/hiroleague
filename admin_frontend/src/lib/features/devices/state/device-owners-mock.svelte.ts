// mockup: Permissions phase 3 ("Hiro per person"). Whose each device is and who a pairing code is for, kept in the
// page: a pick changes nothing on the server until the core keeps a device's person.
import { listPeople, type Person } from '$lib/api/people';
import type { DeviceRow } from '$lib/api/devices';
import { Resource } from '$kit/state/resource.svelte';
import type { PickOption } from '$kit/ui/pick';
import { HALLWAY, ownedDevices, ownerOf, type OwnedDevice } from '../shared/device-people-mock';

export class DeviceOwnersMock {
  readonly #rows: () => readonly DeviceRow[];
  readonly #people = new Resource(listPeople);
  /** A device's person as picked on the page, over the mock's. */
  #picked = $state<Record<string, string>>({});
  #pairFor = $state('');

  constructor(rows: () => readonly DeviceRow[]) {
    this.#rows = rows;
  }

  get people(): readonly Person[] {
    return this.#people.data?.people ?? [];
  }

  /** The devices with their person. */
  readonly devices = $derived.by((): OwnedDevice[] =>
    ownedDevices(this.#rows(), this.people).map((d) => ({ ...d, person_id: this.#picked[d.device_id] ?? d.person_id }))
  );

  /** Everyone a device may belong to: the people, and the mock person made for a shared device. */
  readonly options = $derived.by((): PickOption[] => [
    ...this.people.map((p) => ({ value: p.person_id, label: p.name })),
    { value: HALLWAY.person_id, label: HALLWAY.name }
  ]);

  nameOf = (personId: string): string => this.options.find((o) => o.value === personId)?.label ?? '';

  pick = (deviceId: string, personId: string) => {
    this.#picked = { ...this.#picked, [deviceId]: personId };
  };

  /** Who the next pairing code is for: the owner until another is picked. */
  get pairFor(): string {
    return this.#pairFor || (ownerOf(this.people)?.person_id ?? '');
  }

  set pairFor(personId: string) {
    this.#pairFor = personId;
  }

  /** A person's devices, for the People page. */
  devicesOf = (personId: string): OwnedDevice[] => this.devices.filter((d) => d.person_id === personId);
}
