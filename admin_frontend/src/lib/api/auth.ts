import { apiRequest } from './client';

/** The person signed in to the admin (Phase 6: HiroLeague's own sign-in). */
export type SignedInPerson = {
  person_id: string;
  name: string;
  sign_in: string;
  role_id: string;
};

export type AuthMe = {
  signed_in: boolean;
  person: SignedInPerson | null;
  /** False until `hiro people owner` gave someone a sign-in. */
  anyone_signs_in: boolean;
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

export async function signOut() {
  return apiRequest<null>('/auth/sign-out', { method: 'POST' });
}
