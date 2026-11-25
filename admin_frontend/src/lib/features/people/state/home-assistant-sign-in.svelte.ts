// People → Sign-in (trust fixes): "Sign in with Home Assistant", run by the core, an option the owner adds. The core
// keeps its own connection to Home Assistant (the address here; the token kept by the core, never sent back) and who
// each Home Assistant login is in the family list; the switch that shows it on the sign-in page stays locked until
// the connection works.
import { Action } from '$kit/state/action.svelte';
import { KeyedAction } from '$kit/state/keyed-action.svelte';
import { Draft } from '$kit/state/draft.svelte';
import { Resource } from '$kit/state/resource.svelte';
import { connectHa, disconnectHa, getHaSignIn, linkHaLogin, setHaSignIn, type HaSignIn } from '$lib/api/sign-in-ways';

export type HomeAssistantSignIn = ReturnType<typeof createHomeAssistantSignIn>;

type Connection = { address: string; linkAddress: string; token: string };

export function createHomeAssistantSignIn() {
  const data = new Resource<HaSignIn>(async (signal) => {
    const answer = await getHaSignIn(signal);
    form.load({ address: answer.address, linkAddress: answer.link_address, token: '' });
    return answer;
  });
  // The address as typed, and a new token ('' = keep the one the core has)
  const form = new Draft<Connection>(
    { address: '', linkAddress: '', token: '' },
    {
      done: () => `Connected: Home Assistant ${data.data?.version ?? ''}, ${data.data?.logins.length ?? 0} logins.`,
      save: async (c) => {
        data.set(await connectHa(c.address.trim(), c.linkAddress.trim(), c.token.trim()));
        return { address: data.data?.address ?? c.address, linkAddress: data.data?.link_address ?? '', token: '' };
      }
    }
  );
  const switching = new Action();
  const disconnecting = new Action();
  const linking = new KeyedAction();

  return {
    get data() {
      return data.data;
    },
    get error() {
      return data.error;
    },
    form,
    switching,
    disconnecting,
    linking,
    /** The switch can be turned on only while the core reaches Home Assistant. */
    get canTurnOn() {
      return !!data.data?.connected;
    },
    get linkedCount() {
      return (data.data?.logins ?? []).filter((l) => l.person_id).length;
    },
    /** Connect (or test again with the token kept): needs an address, and a token unless one is kept. */
    get canConnect() {
      const c = form.value;
      // The token kept goes only to the address it was kept for
      const sameAddress = c.address.trim().replace(/\/+$/, '') === (data.data?.address ?? '');
      return !!c.address.trim() && (!!c.token.trim() || (!!data.data?.token_set && sameAddress)) && !form.action.busy;
    },
    connect: () => form.save(),
    disconnect: () =>
      disconnecting.run(async () => {
        data.set(await disconnectHa());
        form.load({ address: '', linkAddress: '', token: '' }, true);
      }),
    setOn: (on: boolean) =>
      switching.run(async () => {
        data.set(await setHaSignIn(on));
      }),
    link: (haUserId: string, personId: string) =>
      linking.run(haUserId, async () => {
        data.set(await linkHaLogin(haUserId, personId));
      })
  };
}
