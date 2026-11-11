// The sample app the kit's gallery and tests run against: what a real app keeps in its src/lib/app (the kit reads
// it at $hiro-app). A new app starts by copying this folder and changing its words.
import { Shapes } from '@lucide/svelte';
import type { ApiHooks } from '$kit/api/client';

export const APP = {
	/** The app's name, as people read it. */
	name: 'Hiro kit',
	/** Its icon: beside the name in the menu, and on the sign-in page. */
	icon: Shapes,
	/** What the home page ('/') is called, for the "couldn't open" page's way back. */
	homeTitle: 'Gallery',
	/** Before every key kept in the browser ($kit/state/persist). */
	storagePrefix: 'hirokit.',
	/** Pages that show alone, with no sign-in and no menu. */
	openRoutes: [] as string[],
	/** What this app's backend needs around every call ($kit/api/client's ApiHooks). */
	api: {} as ApiHooks,
	signIn: {
		/** Under the sign-in button: what one sign-in means here. */
		about: 'One sign-in for HiroLeague and its apps. You come back here, to the page you opened, and stay signed in for 90 days.',
		/** A second line, for another way in ('' = none). */
		also: '',
		/** How someone who didn't come through HiroLeague's sign-in is signed in: "<this> as <name>". */
		otherWay: 'Signed in'
	}
};
