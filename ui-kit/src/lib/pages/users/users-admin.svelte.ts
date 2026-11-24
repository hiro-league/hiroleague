// Settings → Users: everyone who has opened the app, with their roles. A user is a person in HiroLeague's family list
// (signed in at HiroLeague). The owner gives them one or several roles (their rights add up), or No access; where the
// app has a scope (UsersApp.scope: HomeHiro's My room), also its areas and things when a role uses it. The roles are
// HiroLeague's family list's: picking them changes that person's roles there, and HiroLeague refuses taking the only
// Owner's away (its words are shown). No access is the app's own: the panel sets it, and so does each row's button.
import { USERS } from '$hiro-app/users';
import { Draft } from '$kit/state/draft.svelte';
import { KeyedAction } from '$kit/state/keyed-action.svelte';
import { Resource } from '$kit/state/resource.svelte';
import { getRoles, getUsers, saveUser } from './api';
import { change, hasScope, isWaiting, toggleRole } from './rules';
import type { AppUser } from './types';

type Picked = { roleIds: string[]; denied: boolean; areas: string[]; things: string[] };

export class UsersAdmin {
	users = new Resource((signal) => getUsers(signal), { on: ['family', 'hello'], debounce: 300 });
	roles = new Resource((signal) => getRoles(signal), { on: ['family', 'hello'], debounce: 300 });
	/** The app's areas to pick from; nothing is asked when the app has no scope. */
	areas = new Resource(async (signal) => (USERS.scope ? await USERS.scope.loadAreas(signal) : []));
	/** Each row's No access button: one waits while the others stay free, and its error shows under its row. */
	blocking = new KeyedAction();

	waiting = $derived((this.users.data ?? []).filter(isWaiting));
	known = $derived((this.users.data ?? []).filter((u) => !isWaiting(u)));
	rooms = $derived((this.areas.data ?? []).filter((a) => !a.removed_at).sort((a, b) => a.name.localeCompare(b.name)));

	editing = $state<AppUser | null>(null);
	open = $state(false);
	/** The roles (and areas and things) being picked for `editing`; Save writes them. The sheet asks about leaving
	 * itself, not the page. */
	readonly form = new Draft<Picked>({ roleIds: [], denied: false, areas: [], things: [] }, { guard: false, save: (d) => this.#write(d) });

	roleOf = (id: string | null) => this.roles.data?.roles.find((r) => r.id === id);
	/** Each role's name a user holds, or what they are instead ("No access", "Waiting"). */
	roleNames = (u: AppUser): string[] => {
		if (u.denied) return ['No access'];
		return u.role_ids.length ? u.role_ids.map((id) => this.roleOf(id)?.name ?? id) : ['Waiting'];
	};
	/** A held role uses the scope's feature, so the user needs areas or things for it. */
	usesScope = (roleIds: string[]) => roleIds.some((id) => hasScope(this.roleOf(id), USERS.scope?.feature));
	needsScope = $derived(!this.form.value.denied && this.usesScope(this.form.value.roleIds));
	dirty = $derived(this.open && this.form.dirty);
	canSave = $derived(
		(this.form.value.denied || this.form.value.roleIds.length > 0) &&
			(!this.needsScope || this.form.value.areas.length + this.form.value.things.length > 0) &&
			!this.form.action.busy
	);

	edit = (u: AppUser) => {
		this.editing = u;
		this.form.load({ roleIds: [...u.role_ids], denied: u.denied, areas: [...(u.areas ?? [])], things: [...(u.things ?? [])] }, true);
		this.form.action.clear();
		this.open = true;
	};

	/** Hold a role or let it go, keeping the roles' order. */
	toggleRole = (id: string) => {
		this.form.value.roleIds = toggleRole(this.form.value.roleIds, id, (this.roles.data?.roles ?? []).map((r) => r.id));
	};

	toggleDenied = () => {
		this.form.value.denied = !this.form.value.denied;
	};

	toggle = (list: 'areas' | 'things', id: string) => {
		const l = this.form.value[list];
		this.form.value[list] = l.includes(id) ? l.filter((x) => x !== id) : [...l, id];
	};

	save = () => void this.form.save();

	/** No access from the list itself, or back in with the roles they hold: the app's own, nothing asked of HiroLeague. */
	block = (u: AppUser) =>
		void this.blocking.run(u.id, async () => {
			this.users.set(await saveUser(u.id, { denied: !u.denied }));
		});

	#write = async (d: Picked) => {
		const u = this.editing;
		if (!u) return;
		this.users.set(await saveUser(u.id, change(d.roleIds, d.denied, USERS.scope ? d : undefined)));
		this.open = false;
	};
}
