import { apiRequest } from './client';
import type { AppTile } from '$kit/api/apps';
import type { Place } from '$kit/components/place';

/** The person signed in to the admin (Phase 6: HiroLeague's own sign-in). */
export type SignedInPerson = {
  person_id: string;
  name: string;
  sign_in: string;
  role_id: string;
  /** Every role they hold, in the roles' order (Permissions phase 1). */
  role_ids: string[];
};

/** Another way to sign in the core runs: Home Assistant's login, while the owner has it on (People → Sign-in). */
export type SignInOffer = { id: string; label: string };

export type AuthMe = {
  signed_in: boolean;
  person: SignedInPerson | null;
  role_name: string | null;
  /** The names of every role they hold, in the roles' order. */
  role_names: string[];
  /** Whether they hold the Owner role: every page, People and roles included. */
  owner: boolean;
  /** Permissions phase 2: their keys in the core's own features, over all their roles. */
  core_keys: string[];
  /** Each core feature's level for the pages (only a grant for everyone's opens one). */
  levels: Record<string, 'no' | 'see' | 'use'>;
  /** Whether any page of the admin opens for them; else only the Apps card. */
  can_open_settings: boolean;
  /** False until `hiro people owner` gave someone a sign-in. */
  anyone_signs_in: boolean;
  sign_in_offers: SignInOffer[];
  /** A test environment and what its core reaches (its switchboard); null in live and env0. */
  place?: Place | null;
};


export async function getAuthMe() {
  return apiRequest<AuthMe>('/auth/me');
}

export async function signIn(signInName: string, password: string) {
  return apiRequest<{ person: SignedInPerson }>('/auth/sign-in', {
    method: 'POST',
    body: { sign_in: signInName, password }
  });
}

/** `then`: where the browser goes next to be signed out of the apps' sites too (Phase 8); null = nowhere. */
export async function signOut() {
  return apiRequest<{ then: string | null }>('/auth/sign-out', { method: 'POST' });
}

export async function listApps() {
  return apiRequest<{ apps: AppTile[] }>('/apps'); // the dashboard's Apps card; the app switcher (UI kit) reads the same
}

/**
 * Phase 8: where a signed-in browser goes to get back to an extension's site (the backend sends it on
 * with a one-time code). `forApp` is the extension's name from ?for=.
 */
export function backToAppUrl(forApp: string, next: string | null): string {
  const query = new URLSearchParams({ next: next || '/' });
  return `/api/auth/for/${encodeURIComponent(forApp)}?${query}`;
}

/** Phase 8: start a sign-in a connected extension offers (off to Home Assistant's login page). */
export function offeredSignInUrl(offerId: string, forApp: string | null, next: string | null): string {
  const query = new URLSearchParams({ next: next || '/' });
  if (forApp) query.set('for', forApp);
  return `/api/auth/with/${encodeURIComponent(offerId)}?${query}`;
}
