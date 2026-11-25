// People → Sign-in: the ways into HiroLeague. "Sign in with Home Assistant" is an option the owner adds, run by the
// core (admin_svelte/routes/sign_in_ways.py); the access token is kept by the core and never answered.
import { api } from '$kit/api/client';

/** A Home Assistant person with a login: who the owner linked it to ('' = nobody: it can't sign in), and who it seems
 * to be by name (a suggestion: it signs nobody in until the owner links it). */
export type HaLogin = { ha_user_id: string; name: string; login: string; person_id: string; suggested_id: string };

export type HaSignIn = {
  /** Where the core reaches Home Assistant. */
  address: string;
  /** Where people's browsers log in; '' = the same. */
  link_address: string;
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

/** Test the connection and keep it when it works; an empty token tests the one kept (same address only). */
export const connectHa = (address: string, linkAddress: string, token: string) =>
  api<HaSignIn>(`${BASE}/connection`, { method: 'PUT', body: { address, link_address: linkAddress, token } });

export const disconnectHa = () => api<HaSignIn>(`${BASE}/connection`, { method: 'DELETE' });

export const setHaSignIn = (on: boolean) => api<HaSignIn>(`${BASE}/enabled`, { method: 'PUT', body: { on } });

export const linkHaLogin = (haUserId: string, personId: string) =>
  api<HaSignIn>(`${BASE}/logins/${encodeURIComponent(haUserId)}`, { method: 'PUT', body: { person_id: personId } });
