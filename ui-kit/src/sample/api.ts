// What the kit reads of an app's API ($hiro-app/api): who is asking, and the HiroLeague core's AI. A real app
// re-exports these from its own API files (generated from its backend); the sample answers from memory, so the
// gallery opens with no backend.

export type Access = 'no' | 'see' | 'use';

/** Who is asking, as every Hiro backend's /api/me answers. */
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

export const getMe = async (): Promise<Me> => ({
	id: 'sample',
	name: 'Sample Person',
	way: 'dev',
	state: 'ok',
	role_id: 'owner',
	role_name: 'Owner',
	owner: true,
	access: { gallery: 'use' }
});

/** An AI profile of the HiroLeague core, as an app's backend passes it on. */
export type CoreProfile = {
	id: string;
	name: string;
	kind: 'api' | 'local' | 'plan';
	provider: string;
	model: string;
	model_id: string;
	sent_to: string;
	budget?: string | null;
	max_cost_day?: number | null;
	max_per_hour?: number | null;
	at_once?: number;
	fallback_id?: string | null;
	chain?: string[];
	spent_today?: number | null;
	asks_today?: number | null;
	this_hour?: number | null;
};

/** One of an app's uses of AI, and the profile it asks with. */
export type CoreUse = {
	id: string;
	name: string;
	needs: ('pictures' | 'sound' | 'json')[];
	pictures_up_to?: number | null;
	profile_id?: string | null;
	chain?: string[];
};
export type Need = CoreUse['needs'][number];

export type CoreAi = {
	reachable: boolean;
	fetched_at: string | null;
	error?: string | null;
	core?: string | null;
	profiles: CoreProfile[];
	uses: CoreUse[];
	admin_url?: string;
};

export const getCoreAi = async (_signal?: AbortSignal): Promise<CoreAi> => ({ reachable: true, fetched_at: null, profiles: [], uses: [] });
