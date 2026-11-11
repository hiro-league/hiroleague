// Settings → Roles (read-only since Phase 9a): the roles, who has each, and what each may do in the app, as HiroLeague
// grants them (backend auth/api.py). Roles are added, renamed, removed and given rights in HiroLeague's People → Roles.
import { Resource } from '$kit/state/resource.svelte';
import { coreRolesUrl, getRoles } from './api';
import type { Feature, Role } from './types';

export class RolesAdmin {
	roles = new Resource((signal) => getRoles(signal), { on: ['family', 'hello'], debounce: 300 });

	features = $derived<Feature[]>(this.roles.data?.features ?? []);
	/** Where roles change: HiroLeague's People → Roles ("" while the core's admin address is unknown). */
	editUrl = (role?: Role) => coreRolesUrl(this.roles.data?.admin_url, role?.id);

	/** A role's rights in one feature, in words: "Everything", "See, Switch devices", or "" for none. */
	rightsText = (role: Role, feature: Feature) => {
		const have = feature.rights.filter((r) => role.rights.includes(`${feature.id}.${r.id}`));
		if (!have.length) return '';
		if (have.length === feature.rights.length && feature.rights.length > 1) return 'Everything'; // as HiroLeague's table says it
		return have.map((r) => r.name).join(', ');
	};
}
