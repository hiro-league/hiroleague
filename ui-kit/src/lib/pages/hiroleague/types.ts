// What an app says about itself for Settings → HiroLeague ($hiro-app/hiroleague.ts: `export const HIROLEAGUE: HiroLeagueApp`).
// The app's name in the words comes from $hiro-app/app (APP.name).
export type HiroLeagueApp = {
	/** The example label for the app's own address as a subdomain: 'net' → net.hiro.local. */
	siteLabel: string;
	/** What the Edit links open in HiroLeague's admin, in the admin address's help: "its AI profiles and roles". */
	edits: string;
	/** The admin address is also where people sign in (the help says so). */
	signsInThere: boolean;
	/** A line added to the help under the app's address, e.g. another address that keeps working. */
	siteNote?: string;
};
