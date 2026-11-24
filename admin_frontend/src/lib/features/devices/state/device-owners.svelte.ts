// Permissions phase 3: whose each paired device is, and whose the next one will be. A device shows and writes only its
// person's conversations; a device several people use belongs to a person made for it (like "Hallway") on People.
import { listPeople, type Person } from '$lib/api/people';
import { setDevicePerson } from '$lib/api/devices';
import { KeyedAction } from '$kit/state/keyed-action.svelte';
import { Resource } from '$kit/state/resource.svelte';
import type { PickOption } from '$kit/ui/pick';
import { ownerOf, personOptions } from '../shared/device-people';

export class DeviceOwners {
  readonly #people = new Resource(listPeople);
  #pairFor = $state('');
  /** Saving a device's person: one run per device, then the list read again. */
  readonly assign: KeyedAction;

  /** `reload` reads the devices again after a device's person is saved. */
  constructor(reload: () => unknown) {
    this.assign = new KeyedAction({ then: () => reload() });
  }

  get people(): readonly Person[] {
    return this.#people.data?.people ?? [];
  }

  /** Everyone a device may belong to. */
  readonly options = $derived.by((): PickOption[] => personOptions(this.people));

  /** Save whose a device is. */
  pick = (deviceId: string, personId: string) =>
    void this.assign.run(deviceId, () => setDevicePerson(deviceId, personId));

  /** Who the next pairing code is for: the owner until another is picked. */
  get pairFor(): string {
    return this.#pairFor || (ownerOf(this.people)?.person_id ?? '');
  }

  set pairFor(personId: string) {
    this.#pairFor = personId;
  }

  nameOf = (personId: string): string => this.people.find((p) => p.person_id === personId)?.name ?? '';
}
