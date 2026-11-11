// What the app knows of the HiroLeague core's AI: its AI profiles, the app's uses and the profile each asks with, and
// whether the core answers (backend llm/core_ai.py keeps the last list it got, with when, while the core is down).
// Settings → AI from HiroLeague and every per-copy picker read one of these; make it while a component starts.
import { getCoreAi, type CoreAi as CoreAiData, type CoreProfile, type CoreUse } from '$hiro-app/api';
import { Resource } from '$kit/state/resource.svelte';

const EVERY = 60_000; // ms: the backend reads the core again when its list is older than 30 s

export class CoreAi {
	readonly data = new Resource<CoreAiData>((signal) => getCoreAi(signal), { on: ['hello'], every: EVERY });

	profiles = $derived<CoreProfile[]>(this.data.data?.profiles ?? []);
	uses = $derived<CoreUse[]>(this.data.data?.uses ?? []);
	/** The core answered the last read (false while loading the first time too: `loaded` says which). */
	reachable = $derived(!!this.data.data?.reachable);
	loaded = $derived(!!this.data.data);
	/** When the list shown was read; null: never. */
	fetchedAt = $derived(this.data.data?.fetched_at ?? null);
	/** Why the list is old (the core not connected, or its error); the call's own error when the backend didn't answer. */
	problem = $derived(this.data.data?.error ?? this.data.error ?? null);
	core = $derived(this.data.data?.core ?? null);

	use = (id: string) => this.uses.find((u) => u.id === id);
	profile = (id: string | null | undefined) => (id ? this.profiles.find((p) => p.id === id) : undefined);
	/** A copy's saved profile as the core lists it: as saved, or as the core's import renamed the app's own (hh-<id>). */
	resolve = (id: string | null | undefined) => (id ? (this.profile(id) ?? this.profile(`hh-${id}`)) : undefined);
}
