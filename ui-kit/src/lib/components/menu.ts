// The side menu in two levels. Groups (level 1) hold pages (level 2); a page's tabs are small icons on its
// row, shown while the row is hovered (menu-row.svelte), each a link to `?tab=`, and the page's own link opens its
// first tab. A tab may hold sub-tabs (Settings' groups): the address names the sub-tab, and the tab's icon opens its
// first one. A group may instead list one page's tabs as its pages (`tabsOf`: Code reports' Work), each row a link
// to its tab, the group's title the page's name. Which pages and tabs a user gets comes from pages.ts and the same
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
// pref: where the page remembers its tab; first: the tab of a first visit, when not the first one;
// tab and of: a row that is one tab of the page `of` (a group's `tabsOf`), shown while that tab is
export type MenuPage = {
	route: string;
	title: string;
	icon: Component;
	tabs?: MenuTab[];
	pref?: PrefKey;
	first?: string;
	tab?: MenuTab;
	of?: MenuPage;
};
// title: the heading that folds the group away; "" for pages alone, with no heading (an app's Dashboard, its Settings)
export type MenuGroup = { id: string; title: string; pages: MenuPage[] };

// The app's groups, as menu.ts writes them; tabsOf: a page whose tabs are the group's pages, in place of `pages`
type AppGroup = { id: string; title: string; pages: readonly string[]; tabsOf?: string };
const APP_PAGES = MENU_PAGES as Record<string, MenuPage>;

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

/** A page's tabs as rows of their own (a group's `tabsOf`): the tabs this user gets, each a page of its own. */
function tabRows(me: Me | null, key: string): MenuPage[] {
	const p = APP_PAGES[key];
	if (!p || !inMenu(me, p.route)) return [];
	const of = { ...p, tabs: tabsFor(me, p.tabs) };
	return (of.tabs ?? []).map((t) => ({ route: p.route, title: t.title, icon: t.icon, pref: p.pref, tab: t, of }));
}

/** The menu this user gets: only the pages in their menu and the tabs their role has; a group left empty is
 * dropped. */
export function menuFor(me: Me | null): MenuGroup[] {
	return (MENU_GROUPS as readonly AppGroup[])
		.map((g) => ({
			id: g.id,
			title: g.title,
			pages: g.tabsOf
				? tabRows(me, g.tabsOf)
				: g.pages
						.map((k): MenuPage => APP_PAGES[k])
						.filter((p) => inMenu(me, p.route))
						.map((p) => ({ ...p, tabs: tabsFor(me, p.tabs) }))
		}))
		.filter((g) => g.pages.length > 0);
}

/** A row's key in its group: its route, and its tab for a tab's row. */
export const rowKey = (p: MenuPage) => (p.tab ? `${p.route}?tab=${p.tab.value}` : p.route);

/** Whether the route id shown is this page or one under it (Streams › Replay). */
export const onPage = (p: MenuPage, routeId: string | null) => under(p.route, routeId);

/** Whether a row is the one shown: its page (or one under it), and for a tab's row, that tab (as tabShown decides
 * it from the address's tab and the one remembered). */
export const rowShown = (p: MenuPage, routeId: string | null, inAddress: string | null, remembered: unknown) =>
	onPage(p, routeId) && (!p.tab || !p.of || tabShown(p.of, inAddress, remembered) === p.tab.value);

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
