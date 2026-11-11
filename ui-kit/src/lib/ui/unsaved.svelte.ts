// Leaving a page with unsaved changes asks first. Call it while a component starts, with what says
// "there are changes"; it stops with the component.
// - Another page of the app (a link, Back): the app's own dialog, then on to where it was going.
// - Closing the tab, reloading, or another site: the browser's own "Leave site?" dialog.
// Only the query changing (another tab of the same page, `?tab=`) is not leaving.
import { beforeNavigate, goto } from '$app/navigation';
import { ask } from './confirm.svelte';

export function guardUnsaved(dirty: () => boolean) {
	let leaving = false;
	beforeNavigate((nav) => {
		if (leaving || !dirty() || (nav.to && nav.from && nav.to.url.pathname === nav.from.url.pathname)) return;
		nav.cancel();
		const to = nav.to?.url;
		if (nav.type === 'leave' || !to) return; // cancelling a leave is what makes the browser ask
		const external = nav.willUnload;
		void ask({ title: 'Leave without saving?', description: 'Your changes on this page are not saved.', action: 'Leave', danger: true }).then((ok) => {
			if (!ok) return;
			leaving = true;
			if (external) location.assign(to);
			else void goto(to);
		});
	});
}
