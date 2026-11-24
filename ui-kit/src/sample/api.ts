// What the kit reads of an app's API ($hiro-app/api): who is asking. A real app re-exports these from its own API files
// (generated from its backend); the sample answers from memory, so the gallery opens with no backend.

export type Access = 'no' | 'see' | 'use';

/** Who is asking, as every Hiro backend's /api/me answers. */
export type Me = {
	id: string;
	name: string;
	way: 'ha' | 'web' | 'dev';
	state: 'ok' | 'waiting' | 'denied';
	/** Every role they hold, in the roles' order; their rights add up. */
	role_ids: string[];
	role_names: string[];
	owner: boolean;
	access: Record<string, Access>;
	rights?: string[];
	reason?: string;
};

export const getMe = async (): Promise<Me> => ({
	id: 'sample',
	name: 'Sample Person',
	way: 'dev',
	state: 'ok',
	role_ids: ['owner'],
	role_names: ['Owner'],
	owner: true,
	access: { gallery: 'use' }
});

/** Start a sign-in and come back to `next` (an app sends the browser to its backend's /api/auth/start). */
export const startSignIn = (next: string) => console.info('sample app: a sign-in would start, back to', next);

/** End the session; `then` is where the browser goes next (HiroLeague's sign-out), or null. */
export const signOut = async (): Promise<{ then: string | null }> => ({ then: null });
