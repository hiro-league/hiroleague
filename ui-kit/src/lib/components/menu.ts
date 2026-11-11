// The side menu in two levels. Groups (level 1) hold pages (level 2); a page's tabs are small icons on its
// row, each a link to `?tab=`, and the page's own link opens its first tab. A tab may hold sub-tabs (Settings'
// groups): the address names the sub-tab, and the tab's icon opens its first one. Which pages and tabs a user gets comes from pages.ts and the same
// rules the pages use for their tabs. Pure, with tests (lib/app/menu.test.ts).
// UI kit, step 1: the menu itself (its groups, pages and tabs) is the app's own, in lib/app/menu.ts; this file is
// the same in every Hiro app.
import type { Component } from 'svelte';
import type { Me } from '$hiro-app/api';
import { MENU_GROUPS, MENU_PAGES } from '$hiro-app/menu';
import type { PrefKey } from '$hiro-app/prefs';
import { inMenu, trimSlash, under } from '$kit/state/pages';

export type MenuSub = { value: string; title: string; icon: Component; shown?: (me: Me | null) => boolean };
// subs: the tab's own tabs; then `value` names the group only, and the address names one of its subs
export type MenuTab = MenuSub & { subs?: MenuSub[] };
// pref: where the page remembers its tab; first: the tab of a first visit, when not the first one
export type MenuPage = { route: string; title: string; icon: Component; tabs?: MenuTab[]; pref?: PrefKey; first?: string };
export type MenuGroup = { id: string; title: string; pages: MenuPage[] };

const allowed = (me: Me | null) => (t: MenuSub) => !t.shown || t.shown(me);

/** The tabs this user gets on a page: the ones their role has, and a tab with sub-tabs only while one is left. */
function tabsFor(me: Me | null, tabs: MenuTab[] | undefined): MenuTab[] | undefined {
	return tabs
		?.filter(allowed(me))
		.map((t) => (t.subs ? { ...t, subs: t.subs.filter(allowed(me)) } : t))
		.filter((t) => !t.subs || t.subs.length > 0);
}

/** A page's tabs for this user, for the page itself (Settings). */
export const pageTabs = (me: Me | null, route: string): MenuTab[] =>
	tabsFor(me, (Object.values(MENU_PAGES) as MenuPage[]).find((p) => trimSlash(p.route) === trimSlash(route))?.tabs) ?? [];

/** The tabs the address can name: each sub-tab of a tab that has them, else the tab itself. */
export const leavesOf = (tabs: MenuTab[]): string[] => tabs.flatMap((t) => (t.subs ? t.subs.map((s) => s.value) : [t.value]));

/** The tab an address's tab belongs to (itself, or the tab holding that sub-tab). */
export const topOf = (tabs: MenuTab[], leaf: string): MenuTab | undefined => tabs.find((t) => t.value === leaf || t.subs?.some((s) => s.value === leaf));

/** What a tab's link opens: its first sub-tab, or itself. */
export const firstLeaf = (t: MenuTab) => t.subs?.[0]?.value ?? t.value;

/** The menu this user gets: only the pages in their menu and the tabs their role has; a group left empty is
 * dropped. */
export function menuFor(me: Me | null): MenuGroup[] {
	return MENU_GROUPS.map((g) => ({
		id: g.id,
		title: g.title,
		pages: g.pages
			.map((k): MenuPage => MENU_PAGES[k])
			.filter((p) => inMenu(me, p.route))
			.map((p) => ({ ...p, tabs: tabsFor(me, p.tabs) }))
	})).filter((g) => g.pages.length > 0);
}

/** Whether a page's `tabs` tab icons fit on its row beside its name (`nameWidth` px) in a menu `width` px wide.
 * The row: the group's and the button's padding and the page icon before the name (40), a gap (6), each icon 24
 * with a gap of 2, and the icons' inset from the row's end (10). */
export const tabsFit = (width: number, nameWidth: number, tabs: number) => 40 + nameWidth + 6 + tabs * 26 - 2 + 12 <= width;

/** Whether the route id shown is this page or one under it (Streams › Replay). */
export const onPage = (p: MenuPage, routeId: string | null) => under(p.route, routeId);

/** The tab a page shows, as UrlTab decides it: the address's `?tab=`, else the one remembered, else the
 * first visit's; for a sub-tab, the tab holding it. Null for a page without tabs. */
export function tabShown(p: MenuPage, inAddress: string | null, remembered: unknown): string | null {
	const tabs = p.tabs ?? [];
	const leaves = leavesOf(tabs);
	if (!leaves.length) return null;
	const pick = (v: unknown) => (typeof v === 'string' && leaves.includes(v) ? v : null);
	const leaf = pick(inAddress) ?? pick(remembered) ?? pick(p.first) ?? leaves[0];
	return topOf(tabs, leaf)?.value ?? null;
}
