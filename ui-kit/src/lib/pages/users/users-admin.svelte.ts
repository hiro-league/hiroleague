// Settings → Users: everyone who has opened the app, with their role. A user is a person in HiroLeague's family list
// (signed in at HiroLeague). The owner picks a role or No access; where the app has a scope (UsersApp.scope: HomeHiro's
// My room), also its areas and things when the role uses it. The role is HiroLeague's family list's: picking one
// changes that person's role there, and HiroLeague refuses taking the only Owner's away (its words are shown).
import { USERS } from '$hiro-app/users';
import { Draft } from '$kit/state/draft.svelte';
import { Resource } from '$kit/state/resource.svelte';
import { getRoles, getUsers, saveUser } from './api';
import { change, choiceOf, hasScope, isWaiting, type Choice } from './rules';
import type { AppUser } from './types';

type Picked = { choice: Choice; areas: string[]; things: string[] };

export class UsersAdmin {
	users = new Resource((signal) => getUsers(signal), { on: ['family', 'hello'], debounce: 300 });
	roles = new Resource((signal) => getRoles(signal), { on: ['family', 'hello'], debounce: 300 });
	/** The app's areas to pick from; nothing is asked when the app has no scope. */
	areas = new Resource(async (signal) => (USERS.scope ? await USERS.scope.loadAreas(signal) : []));

	waiting = $derived((this.users.data ?? []).filter(isWaiting));
	known = $derived((this.users.data ?? []).filter((u) => !isWaiting(u)));
	rooms = $derived((this.areas.data ?? []).filter((a) => !a.removed_at).sort((a, b) => a.name.localeCompare(b.name)));

	editing = $state<AppUser | null>(null);
	open = $state(false);
	/** The role (and areas and things) being picked for `editing`; Save writes them. The sheet asks about leaving
	 * itself, not the page. */
	readonly form = new Draft<Picked>({ choice: null, areas: [], things: [] }, { guard: false, save: (d) => this.#write(d) });

	roleOf = (id: string | null) => this.roles.data?.roles.find((r) => r.id === id);
	roleName = (u: AppUser) => (u.denied ? 'No access' : (this.roleOf(u.role_id)?.name ?? 'Waiting'));
	/** The picked role uses the scope's feature, so the user needs areas or things for it. */
	needsScope = $derived(hasScope(this.roleOf(this.form.value.choice), USERS.scope?.feature));
	dirty = $derived(this.open && this.form.dirty);
	canSave = $derived(
		this.form.value.choice !== null && (!this.needsScope || this.form.value.areas.length + this.form.value.things.length > 0) && !this.form.action.busy
	);

	edit = (u: AppUser) => {
		this.editing = u;
		this.form.load({ choice: choiceOf(u), areas: [...(u.areas ?? [])], things: [...(u.things ?? [])] }, true);
		this.form.action.clear();
		this.open = true;
	};

	pick = (choice: Choice) => {
		this.form.value.choice = choice;
	};

	toggle = (list: 'areas' | 'things', id: string) => {
		const l = this.form.value[list];
		this.form.value[list] = l.includes(id) ? l.filter((x) => x !== id) : [...l, id];
	};

	save = () => void this.form.save();

	#write = async (d: Picked) => {
		const u = this.editing;
		if (!u) return;
		this.users.set(await saveUser(u.id, change(d.choice, USERS.scope ? d : undefined)));
		this.open = false;
	};
}
