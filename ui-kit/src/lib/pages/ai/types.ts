// What an app says on its AI pages ($hiro-app/ai.ts: `export const AI: AiApp = {…}`): its own words and lists. The
// profiles, the uses (their names and what they send) and the voices come from the core; these are only the app's
// sentences around them. `voices` is there only for an app that speaks (HomeHiro): its Voices tab reads it.

/** A card of what moved to HiroLeague's admin: each line says what it was, and where it is now. */
export type Moved = {
	title: string;
	description: string;
	items: { what: string; was: string; page: string }[];
	footer: string;
};

export type VoicesApp = {
	/** Under the title of the first card: what the app's speech is, and who makes it. */
	about: string;
	/** After "Picking one here saves it in HiroLeague; it is edited there.": what else may pick a voice. */
	pickNote: string;
	/** Under the title of the profiles card: what can pick from them. */
	listAbout: string;
	moved: Moved;
};

export type AiApp = {
	/** Under the title of the first card: what the app asks an AI for. */
	about: string;
	/** Under the title of the Uses card. */
	usesAbout: string;
	/** After the Uses card's "edited there" line: what else is true of the app's uses ('' = nothing). */
	usesNote: string;
	/** What moved to HiroLeague (null = no such card). */
	moved: Moved | null;
	voices?: VoicesApp;
};
