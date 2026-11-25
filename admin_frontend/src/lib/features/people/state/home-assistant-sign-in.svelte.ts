// mockup — People → Sign-in (trust fixes, fix 2, option A): the core runs "Sign in with Home Assistant" itself, an
// option the owner adds. The switch that shows it on the sign-in page stays off until the core reaches Home Assistant;
// who is who (a Home Assistant person → a person in the family list) is kept in the core. Mock data only: nothing
// here calls the backend yet.
import { Action } from '$kit/state/action.svelte';

/** A person in Home Assistant, as the core would read them once connected. */
export type HaPerson = { ha_user_id: string; name: string; login: string };

/** What the connection test answers. */
export type HaConnection = { version: string; people: HaPerson[] };

// mockup: the answer a working connection would give
const MOCK_ANSWER: HaConnection = {
  version: '2026.11.2',
  people: [
    { ha_user_id: 'u1', name: 'Michel', login: 'michel' },
    { ha_user_id: 'u2', name: 'Mona', login: 'mona' },
    { ha_user_id: 'u3', name: 'Mark', login: 'mark' },
    { ha_user_id: 'u4', name: 'Joe', login: 'joe' },
    { ha_user_id: 'u5', name: 'Guest', login: 'guest' }
  ]
};

export type HomeAssistantSignIn = ReturnType<typeof createHomeAssistantSignIn>;

/** `family` is the family list as the People tab has it: a Home Assistant person is linked to one of them. */
export function createHomeAssistantSignIn(family: () => { person_id: string; name: string }[]) {
  let address = $state('');
  let token = $state('');
  let connection = $state<HaConnection | null>(null);
  let on = $state(false);
  // ha_user_id → person_id; '' = nobody (that login can't sign in)
  let links = $state<Record<string, string>>({});
  const connecting = new Action();

  // mockup: a first connection suggests the family person of the same name; the owner confirms each
  function suggest(people: HaPerson[]) {
    const byName = new Map(family().map((p) => [p.name.toLowerCase(), p.person_id]));
    links = Object.fromEntries(people.map((p) => [p.ha_user_id, links[p.ha_user_id] ?? byName.get(p.name.toLowerCase()) ?? '']));
  }

  return {
    get address() {
      return address;
    },
    set address(v: string) {
      address = v;
    },
    get token() {
      return token;
    },
    set token(v: string) {
      token = v;
    },
    get connection() {
      return connection;
    },
    get on() {
      return on;
    },
    get links() {
      return links;
    },
    connecting,
    /** The switch can be turned on only while the core reaches Home Assistant. */
    get canTurnOn() {
      return connection !== null;
    },
    get linkedCount() {
      return Object.values(links).filter(Boolean).length;
    },
    connect: () =>
      connecting.run(async () => {
        // mockup: a pause, then the answer a working connection would give (an address and a token are needed)
        await new Promise((r) => setTimeout(r, 600));
        if (!address.trim() || !token.trim()) throw new Error("Type Home Assistant's address and an access token.");
        connection = MOCK_ANSWER;
        suggest(MOCK_ANSWER.people);
        return `Connected: Home Assistant ${MOCK_ANSWER.version}, ${MOCK_ANSWER.people.length} people.`;
      }),
    disconnect: () => {
      connection = null;
      on = false;
      token = '';
    },
    setOn: (next: boolean) => {
      on = next && connection !== null;
    },
    link: (haUserId: string, personId: string) => {
      links = { ...links, [haUserId]: personId };
    }
  };
}
