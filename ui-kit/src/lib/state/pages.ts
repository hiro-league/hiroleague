// Which page needs which feature (backend auth/access.py): the menu shows only the pages a role has, and the
// layout shows "not part of your <app>" on the others. The backend refuses their calls anyway
// (auth/guard.py); this only keeps people from pages that would fail. Pure, with tests (lib/app/pages.test.ts).
// UI kit, step 1: the list of pages is the app's own, in lib/app/pages.ts; this file is the same in every Hiro app.
import type { Access, Me } from '$hiro-app/api';
import { PAGES } from '$hiro-app/pages';

const RANK: Record<Access, number> = { no: 0, see: 1, use: 2 };

/** Whether this user may do `need` with a feature. Sign-in off and owners have everything. */
export const can = (me: Me | null, feature: string, need: Access = 'see') => !!me && RANK[me.access[feature] ?? 'no'] >= RANK[need];

/** A page of the app. `any`: the features that open it, at `need` (look, unless it says use). `ownerOnly`: for
 * owners alone, whatever the features. `menu`: in the menu only with this feature at this level, even for
 * someone who may open the page. `inBuild`: false when this build leaves the page out (a feature not ready):
 * then nobody has it, an owner neither (UI kit, step 1c: the HiroLeague admin hides pages this way). */
export type Page = {
	route: string;
	any: string[];
	need?: Access;
	ownerOnly?: boolean;
	menu?: { feature: string; need: Access };
	inBuild?: () => boolean;
};

/** A route id or an address's path without the slash some apps end theirs with ('/server/' is '/server').
 * UI kit, step 1c: both are accepted until every app's routes have none. */
export const trimSlash = (path: string) => (path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path);

/** Whether `routeId` is the page at `route` or one under it (Streams › Replay). */
export function under(route: string, routeId: string | null): boolean {
	if (routeId === null) return false;
	const [page, here] = [trimSlash(route), trimSlash(routeId)];
	return here === page || (page !== '/' && here.startsWith(page + '/'));
}

const pageOf = (routeId: string | null) => PAGES.find((p) => under(p.route, routeId));

/** Whether this user may open the page with this route id. A route not listed (an error page) is open. */
export function pageAllowed(me: Me | null, routeId: string | null): boolean {
	if (!me) return false;
	const p = pageOf(routeId);
	if (p?.inBuild && !p.inBuild()) return false;
	if (me.owner) return true;
	if (!p) return true;
	return !p.ownerOnly && p.any.some((f) => can(me, f, p.need));
}

/** Whether a page is in this user's menu: the pages they may open; a page with `menu` only with that feature. */
export function inMenu(me: Me | null, routeId: string): boolean {
	const only = PAGES.find((p) => trimSlash(p.route) === trimSlash(routeId))?.menu;
	return only ? can(me, only.feature, only.need) : pageAllowed(me, routeId);
}

/** Where this user starts: the first page in menu order they may open, or null (none). */
export function firstPage(me: Me | null): string | null {
	return PAGES.find((p) => !p.ownerOnly && pageAllowed(me, p.route))?.route ?? null;
}
