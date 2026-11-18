// A test environment and what it reaches of the outside systems this app uses: its switchboard, as the backend's
// /api/me says it (`place`; the backend kit's auth/api.py PlaceOut, from hiro_commons.switchboard). Live and env0 say
// none: everything is real there. The banner above every page (place-banner.svelte) shows it.

export type PlaceMode = 'real' | 'read' | 'fake' | 'off';

export type Place = {
	place: string; // "env2"
	preset: string; // "Safe"
	problem?: string; // the switchboard couldn't be read: every system is off
	systems?: { id: string; name: string; mode: PlaceMode }[];
};

/** A mode in the banner's words. */
export const MODE_WORDS: Record<PlaceMode, string> = { real: 'real', read: 'read only', fake: 'fake', off: 'off' };

/** What a mode means there, for the hover. */
export const MODE_MEANS: Record<PlaceMode, string> = {
	real: 'the real system, as live: what is done here happens for real',
	read: 'the real system is read; nothing is written to it',
	fake: 'a stand-in answers; nothing real is reached or paid',
	off: 'not reached here'
};

/** The place in an answer to "who is asking", whatever else the app's own answer holds; null: none said. */
export function placeOf(me: unknown): Place | null {
	const place = (me as { place?: Place | null } | null)?.place;
	return place && typeof place.place === 'string' ? place : null;
}

/** The systems in the order the banner shows them: the real ones first (they are the ones to watch). */
export function inBannerOrder(place: Place): NonNullable<Place['systems']> {
	const systems = place.systems ?? [];
	return [...systems.filter((s) => s.mode === 'real'), ...systems.filter((s) => s.mode !== 'real')];
}
