// What the shared UI kit reads of the admin's API ($hiro-app/api): who is signed in, and signing out. The admin
// is where people sign in, so "who is there" comes from its own session (lib/runtime/admin-session), told here
// in the kit's words.
import { ApiError } from '$kit/api/client';
import { adminSession } from '$lib/runtime/admin-session.svelte';
import { signOut as apiSignOut } from '$lib/api/auth';

export type Access = 'no' | 'see' | 'use';

/** Who is asking, as the kit's shell and menu read it (every Hiro app answers the same shape). */
export type Me = {
  id: string;
  name: string;
  way: 'ha' | 'web' | 'dev';
  state: 'ok' | 'waiting' | 'denied';
  role_id: string | null;
  role_name: string | null;
  owner: boolean;
  access: Record<string, Access>;
  rights?: string[];
  reason?: string;
};

/** Ask the server who is signed in. Nobody: the kit hears "401" and the shell shows the sign-in form. */
export async function getMe(): Promise<Me> {
  await adminSession.check();
  if (adminSession.state === 'unreachable') throw new ApiError(0, adminSession.error ?? "The server didn't answer.");
  const person = adminSession.person;
  if (adminSession.state !== 'signed-in' || !person) throw new ApiError(401, 'Sign in to the admin first.');
  return {
    id: person.person_id,
    name: person.name,
    way: 'web',
    state: 'ok',
    role_id: person.role_id,
    role_name: adminSession.roleName,
    owner: false,
    // the admin's one right today: a role either opens HiroLeague's settings (every page) or signs in for the
    // apps only (no page: the layout shows it the apps)
    access: adminSession.canOpenSettings ? { settings: 'use' } : {}
  };
}

/** The admin shows its own sign-in form (the shell's signed-out view); there is nowhere to send the browser. */
export const startSignIn = (_next: string) => {};

/** End the session; `then` is where the browser goes next to be signed out of the apps' sites too, or null. */
export async function signOut(): Promise<{ then: string | null }> {
  const answer = await apiSignOut();
  return { then: answer?.then ?? null };
}
