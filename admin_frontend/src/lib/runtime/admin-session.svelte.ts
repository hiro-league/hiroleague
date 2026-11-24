/**
 * Who is signed in to the admin (Phase 6: HiroLeague's own sign-in).
 *
 * The layout checks once at start and shows the sign-in page until someone signs in;
 * any API call answered 401 later (session ended, password changed elsewhere) brings
 * the sign-in page back through `sign-in-signal`.
 */
import { errorMessage } from '$kit/api/client';
import type { Place } from '$kit/components/place';
import {
  getAuthMe,
  signIn as apiSignIn,
  signOut as apiSignOut,
  type SignedInPerson,
  type SignInOffer
} from '$lib/api/auth';
import { registerSignedOutHandler } from './sign-in-signal';

type SessionState = 'checking' | 'signed-out' | 'signed-in' | 'unreachable';

function createAdminSession() {
  let state = $state<SessionState>('checking');
  let person = $state<SignedInPerson | null>(null);
  let anyoneSignsIn = $state(true);
  // Permissions phase 2: whether any admin page opens, the Owner role, and each core feature's level
  let canOpenSettings = $state(false);
  let owner = $state(false);
  let levels = $state<Record<string, 'no' | 'see' | 'use'>>({});
  let roleName = $state<string | null>(null);
  let offers = $state<SignInOffer[]>([]);
  // A test environment and what its core reaches, for the kit's banner; null in live and env0
  let place = $state<Place | null>(null);
  let error = $state<string | null>(null);

  async function check() {
    try {
      const me = (await getAuthMe());
      person = me.person;
      anyoneSignsIn = me.anyone_signs_in;
      canOpenSettings = me.can_open_settings;
      owner = me.owner;
      levels = me.levels;
      roleName = me.role_name;
      offers = me.sign_in_offers ?? [];
      place = me.place ?? null;
      state = me.signed_in ? 'signed-in' : 'signed-out';
      error = null;
    } catch (err) {
      state = 'unreachable';
      error = errorMessage(err);
    }
  }

  async function signIn(name: string, password: string): Promise<string | null> {
    try {
      await apiSignIn(name, password);
      // Read who they are again: their role decides whether the settings open (Phase 8).
      await check();
      return null;
    } catch (err) {
      return errorMessage(err);
    }
  }

  async function signOut() {
    try {
      // Phase 8: signing out here signs this browser out of the apps' sites too (HomeHiro), passing through them.
      const then = (await apiSignOut())?.then;
      if (then) {
        window.location.assign(then);
        return;
      }
    } finally {
      person = null;
      canOpenSettings = false;
      owner = false;
      levels = {};
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
    get canOpenSettings() {
      return canOpenSettings;
    },
    get owner() {
      return owner;
    },
    /** Each core feature's level for the pages, as the core worked it out from the person's roles. */
    get levels() {
      return levels;
    },
    get roleName() {
      return roleName;
    },
    get place() {
      return place;
    },
    get offers() {
      return offers;
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
