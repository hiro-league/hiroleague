// HiroLeague's AI and voices as an app's backend passes them on (each Hiro backend: llm/core_ai.py + ai_api.py, and
// voices_api.py in HomeHiro): the core's AI profiles and the profile each of the app's uses asks with, the core's voice
// profiles and the Speak default; while the core doesn't answer, the last list it sent (`reachable` false, `fetched_at`).
// Written by hand to the shape the backends' OpenAPI files give (CoreAiOut, VoicesOut).
import { api } from '$kit/api/client';

/** An AI profile of the HiroLeague core. kind: api (paid per question), local (a server in the house), plan (a tool on a plan). */
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

/** One of an app's uses of AI (id: ask, wakeword, sites, write, study), and the core's profile it asks with now. */
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
	/** Where the core's admin opens, for the Edit links. */
	admin_url?: string;
};

/** One of the core's voice profiles. */
export type CoreVoice = { id: string; name: string; line?: string };

export type CoreVoices = {
	reachable: boolean;
	fetched_at: string | null;
	error?: string | null;
	profiles: CoreVoice[];
	default_id?: string | null;
	admin_url?: string;
};

export const getCoreAi = (signal?: AbortSignal) => api<CoreAi>('ai', { signal });
/** Pick the core's profile one of the app's uses asks with (saved in HiroLeague); null clears it. */
export const setAiUse = (use: string, profileId: string | null) =>
	api<CoreAi>(`ai/uses/${encodeURIComponent(use)}`, { method: 'PUT', body: { profile_id: profileId } });

export const getVoices = (signal?: AbortSignal) => api<CoreVoices>('voices', { signal });
export const setDefaultVoice = (profileId: string | null) => api<CoreVoices>('voices/default', { method: 'PUT', body: { profile_id: profileId } });

/** The core's admin on its Profiles tab (AI or voice profiles); "" while its address is unknown. */
export const coreProfilesUrl = (adminUrl: string | null | undefined, kind: 'ai' | 'voice') =>
	adminUrl ? `${adminUrl}/catalog/?tab=${kind === 'voice' ? 'voices' : 'profiles'}` : '';
/** Edit opens the profile's editor in the core's admin (the apps have no profile editor of their own). */
export const coreEditUrl = (adminUrl: string | null | undefined, kind: 'ai' | 'voice', id: string) =>
	adminUrl ? `${coreProfilesUrl(adminUrl, kind)}&edit=${encodeURIComponent(id)}` : '';
