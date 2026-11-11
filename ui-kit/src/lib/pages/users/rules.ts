// Settings → Users and Roles: the small rules both tabs share. Pure, with tests (rules.test.ts).
import type { AppUser, Feature, Role, UserChange } from './types';

/** What the owner picks for a user: a role's id, No access, or nothing yet. */
export type Choice = string | typeof NO_ACCESS | null;
export const NO_ACCESS = 'none';

/** A new user waits until the owner picks a role or No access. */
export const isWaiting = (u: AppUser) => u.role_id === null && !u.denied;

export const choiceOf = (u: AppUser): Choice => (u.denied ? NO_ACCESS : u.role_id);

/** What is saved for a user's choice. `scope` (the areas and things picked) only for an app that has one: the others
 * send the role or No access alone. */
export function change(choice: Choice, scope?: { areas: string[]; things: string[] }): UserChange {
	const base = choice === NO_ACCESS ? { role_id: null, denied: true } : { role_id: choice, denied: false };
	return scope ? { ...base, areas: scope.areas, things: scope.things } : base;
}

/** How a role reads in a list: "uses 3 features · looks at 1 feature", or "nothing yet". */
export function roleSummary(role: Pick<Role, 'access'>, features: readonly Pick<Feature, 'id'>[]): string {
	const count = (a: string) => features.filter((f) => role.access[f.id] === a).length;
	const n = (k: number) => (k === 1 ? '1 feature' : `${k} features`);
	const parts = [count('use') && `uses ${n(count('use'))}`, count('see') && `looks at ${n(count('see'))}`].filter(Boolean);
	return parts.join(' · ') || 'nothing yet';
}

/** Whether a role uses the scope's feature (HomeHiro's My room), so a user with it needs areas or things there. */
export const hasScope = (role: Pick<Role, 'access'> | undefined, feature: string | undefined) => !!feature && role?.access[feature] === 'use';
