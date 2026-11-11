// What Settings → Users and Roles reads of the backend (every Hiro backend's auth/api.py answers the same, apart from
// the optional My-room-style fields) and what an app tells the page about itself ($hiro-app/users).

/** One thing a feature lets a role do ("See", "Switch devices"). */
export type Right = { id: string; name: string; says: string };
/** A feature and its rights, as HiroLeague's core defines them. */
export type Feature = { id: string; name: string; rights: Right[]; not_for_owner?: boolean };
/** A role: its rights come from HiroLeague; `users` are the names that have it. */
export type Role = {
	id: string;
	name: string;
	says: string;
	built_in: boolean;
	/** false: the role exists in this app only, not in HiroLeague (HomeHiro before its family list was brought over). */
	core?: boolean;
	rights: string[];
	access: Record<string, 'no' | 'see' | 'use'>;
	users: string[];
};
export type Roles = { roles: Role[]; features: Feature[]; admin_url?: string };

/** Something picked for a user: a room, a thing. */
export type Ref = { id: string; name: string };

/** Someone who opened the app. role_id null + denied false: waiting for a role; role_id null + denied true: No access. */
export type AppUser = {
	id: string;
	name: string;
	role_id: string | null;
	denied: boolean;
	first_seen: string;
	last_seen: string;
	last_way: string;
	last_device: string;
	/** Only in an app with a scope (UsersApp.scope): the linked person and what is picked. */
	person?: Ref | null;
	person_things?: Ref[];
	areas?: string[];
	things?: string[];
};
export type UserChange = { role_id?: string | null; denied?: boolean; areas?: string[]; things?: string[] };

/** An area (room) the owner can give a user, as the app lists them. */
export type ScopeArea = { id: string; name: string; removed_at?: string | null };

/** A feature that needs more than a role: which areas and things the user may see in it (HomeHiro's My room). */
export type UsersScope = {
	/** The feature's id: a role that uses it needs the user to have areas or things. */
	feature: string;
	/** Its name in words ("My room"). */
	label: string;
	loadAreas: (signal?: AbortSignal) => Promise<ScopeArea[]>;
	/** What is linked to the person, in words ("In Home Assistant"), shown before their name. */
	linkedLabel: string;
	/** For a user with no person linked: under the name in the sheet, and the waiting list's tail. */
	notLinked: string;
	waitingNotLinked: string;
	areasHelp: string;
	thingsHelp: string;
	noThings: string;
};

export type UsersApp = {
	/** The Users tab's opening words: how people sign in here and where the role comes from. */
	intro: string;
	/** The user's last way in (the backend's last_way) in words. */
	ways: Record<string, string>;
	/** The app's own scope; null when a role is all it takes. */
	scope: UsersScope | null;
};
