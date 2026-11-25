// People → Sign-in: the ways into HiroLeague. "Sign in with Home Assistant" is an option the owner adds, run by the
// core (admin_svelte/routes/sign_in_ways.py); the access token is kept by the core and never answered.
import { api } from '$kit/api/client';

/** A Home Assistant person with a login, and who they are in the family list ('' = nobody: they can't sign in). */
export type HaLogin = { ha_user_id: string; name: string; login: string; person_id: string };

export type HaSignIn = {
  address: string;
  token_set: boolean;
  enabled: boolean;
  /** The last connection test worked: the switch may be turned on. */
  connected: boolean;
  version: string;
  checked_at: string;
  logins: HaLogin[];
};

const BASE = 'sign-in/home-assistant';

export const getHaSignIn = (signal?: AbortSignal) => api<HaSignIn>(BASE, { signal });

/** Test the connection and keep it when it works; an empty token tests the one kept. */
export const connectHa = (address: string, token: string) =>
  api<HaSignIn>(`${BASE}/connection`, { method: 'PUT', body: { address, token } });

export const disconnectHa = () => api<HaSignIn>(`${BASE}/connection`, { method: 'DELETE' });

export const setHaSignIn = (on: boolean) => api<HaSignIn>(`${BASE}/enabled`, { method: 'PUT', body: { on } });

export const linkHaLogin = (haUserId: string, personId: string) =>
  api<HaSignIn>(`${BASE}/logins/${encodeURIComponent(haUserId)}`, { method: 'PUT', body: { person_id: personId } });
