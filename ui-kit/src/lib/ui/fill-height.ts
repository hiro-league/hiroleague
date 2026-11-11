// Makes an element reach down to the bottom of the window, whatever else is on the page: its height
// is the window's height minus where it starts (and a small gap). Kept up to date when the window
// resizes and when things above it move it (a tab shown, a banner added): its position is checked
// on the next frames after it appears and then twice a second while the tab is shown, which is cheap.
import { repeat } from '$kit/state/poll.svelte';

export function fillHeight(node: HTMLElement, gap = 24) {
	let lastTop = NaN;
	let lastInner = NaN;
	const set = () => {
		const top = node.getBoundingClientRect().top + window.scrollY;
		if (top === lastTop && window.innerHeight === lastInner) return;
		[lastTop, lastInner] = [top, window.innerHeight];
		node.style.height = `${Math.max(360, Math.floor(window.innerHeight - top - gap))}px`;
	};
	set();
	const frames = [requestAnimationFrame(() => (set(), frames.push(requestAnimationFrame(set))))];
	const stop = repeat(set, 500);
	window.addEventListener('resize', set);
	return {
		destroy() {
			frames.forEach(cancelAnimationFrame);
			stop();
			window.removeEventListener('resize', set);
		}
	};
}
