// The sample app's side menu: its groups, their pages, and each page's tabs. How a menu works: $kit/components/menu.
import type { MenuPage } from '$kit/components/menu';
import { LayoutGrid, Palette, Shapes } from '@lucide/svelte';

export const MENU_PAGES = {
	gallery: {
		route: '/',
		title: 'Gallery',
		icon: Shapes,
		pref: 'gallery.tab',
		tabs: [
			{ value: 'pieces', title: 'Pieces', icon: LayoutGrid },
			{ value: 'colours', title: 'Colours', icon: Palette }
		]
	}
} satisfies Record<string, MenuPage>;

type PageKey = keyof typeof MENU_PAGES;

export const MENU_GROUPS: { id: string; title: string; pages: PageKey[] }[] = [{ id: 'kit', title: 'UI kit', pages: ['gallery'] }];
