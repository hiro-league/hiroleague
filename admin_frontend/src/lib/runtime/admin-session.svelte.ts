/**
 * Who is signed in to the admin (Phase 6: HiroLeague's own sign-in).
 *
 * The layout checks once at start and shows the sign-in page until someone signs in;
 * any API call answered 401 later (session ended, password changed elsewhere) brings
 * the sign-in page back through `sign-in-signal`.
 */
import { getAuthMe, signIn as apiSignIn, signOut as apiSignOut, type SignedInPerson } from '$lib/api/auth';
import { registerSignedOutHandler } from './sign-in-signal';

type SessionState = 'checking' | 'signed-out' | 'signed-in' | 'unreachable';

function createAdminSession() {
  let state = $state<SessionState>('checking');
  let person = $state<SignedInPerson | null>(null);
  let anyoneSignsIn = $state(true);
  let error = $state<string | null>(null);

  async function check() {
    try {
      const me = (await getAuthMe()).data;
      person = me.person;
      anyoneSignsIn = me.anyone_signs_in;
      state = me.signed_in ? 'signed-in' : 'signed-out';
      error = null;
    } catch (err) {
      state = 'unreachable';
      error = err instanceof Error ? err.message : 'The server did not answer.';
    }
  }

  async function signIn(name: string, password: string): Promise<string | null> {
    try {
      person = (await apiSignIn(name, password)).data.person;
      state = 'signed-in';
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : 'Sign-in failed.';
    }
  }

  async function signOut() {
    try {
      await apiSignOut();
    } finally {
      person = null;
      state = 'signed-out';
    }
  }

  registerSignedOutHandler(() => {
    if (state === 'signed-in') {
      person = null;
      state = 'signed-out';
    }
  });

  return {
    get state() {
      return state;
    },
    get person() {
      return person;
    },
    get anyoneSignsIn() {
      return anyoneSignsIn;
    },
    get error() {
      return error;
    },
    check,
    signIn,
    signOut
  };
}

export const adminSession = createAdminSession();
