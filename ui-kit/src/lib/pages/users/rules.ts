// Settings → Users and Roles: the small rules both tabs share. Pure, with tests (rules.test.ts).
import type { AppUser, Feature, Role, UserChange } from './types';

/** A new user waits until the owner gives them a role or No access. */
export const isWaiting = (u: Pick<AppUser, 'role_ids' | 'denied'>) => u.role_ids.length === 0 && !u.denied;

/** Hold a role or let it go, in the roles' order (`order`: every role's id, as the Roles tab lists them). */
export function toggleRole(held: readonly string[], id: string, order: readonly string[]): string[] {
	const next = held.includes(id) ? held.filter((x) => x !== id) : [...held, id];
	return next.sort((a, b) => order.indexOf(a) - order.indexOf(b));
}

/** What Save sends: the roles and No access, and `scope` (the areas and things picked) only for an app that has one. */
export function change(roleIds: string[], denied: boolean, scope?: { areas: string[]; things: string[] }): UserChange {
	const base = { role_ids: roleIds, denied };
	return scope ? { ...base, areas: scope.areas, things: scope.things } : base;
}

/** How a role reads in a list: "uses 3 features · looks at 1 feature", or "nothing yet". */
export function roleSummary(role: Pick<Role, 'access'>, features: readonly Pick<Feature, 'id'>[]): string {
	const count = (a: string) => features.filter((f) => role.access[f.id] === a).length;
	const n = (k: number) => (k === 1 ? '1 feature' : `${k} features`);
	const parts = [count('use') && `uses ${n(count('use'))}`, count('see') && `looks at ${n(count('see'))}`].filter(Boolean);
	return parts.join(' · ') || 'nothing yet';
}

/** Whether a role uses the scope's feature (HomeHiro's My room), so a user holding it needs areas or things there. */
export const hasScope = (role: Pick<Role, 'access'> | undefined, feature: string | undefined) => !!feature && role?.access[feature] === 'use';

/** A role's rights in one feature, in words: "Everything", "See, Switch devices (their own)", or "" for none. Each key
 * is built from the feature's declared actions, never found by its id's prefix (a feature id may hold dots). */
export function rightsText(keys: readonly string[], feature: Pick<Feature, 'id' | 'rights'>): string {
	const words = feature.rights.flatMap((r) => {
		const key = `${feature.id}.${r.id}`;
		return keys.includes(key) ? [r.name] : keys.includes(`${key}:own`) ? [`${r.name} (their own)`] : [];
	});
	if (!words.length) return '';
	const all = feature.rights.every((r) => keys.includes(`${feature.id}.${r.id}`));
	return all && feature.rights.length > 1 ? 'Everything' : words.join(', '); // "Everything" as HiroLeague's table says it
}
