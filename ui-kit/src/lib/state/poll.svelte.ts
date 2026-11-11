// Repeating work: a timer that never runs the work twice at once and rests while the browser tab
// is hidden (nobody is looking, and every request holds a connection).
import { untrack } from 'svelte';

/** Run `fn` every `ms`. A run still going when the next is due is not started again. Ticks are
 * skipped while the tab is hidden, and one runs as soon as it shows again. Returns the function
 * that stops it. `fn` shows its own errors; one that escapes is logged, not lost. */
export function repeat(fn: () => unknown, ms: number): () => void {
	let running = false;
	let missed = false;
	const tick = async () => {
		if (document.hidden) return void (missed = true);
		if (running) return;
		running = true;
		try {
			await fn();
		} catch (e) {
			console.error(e);
		} finally {
			running = false;
		}
	};
	const timer = setInterval(tick, ms);
	const onVisible = () => {
		if (document.hidden || !missed) return;
		missed = false;
		void tick();
	};
	document.addEventListener('visibilitychange', onVisible);
	return () => {
		clearInterval(timer);
		document.removeEventListener('visibilitychange', onVisible);
	};
}

/** `repeat` for a component: runs while `when()` is true (it is reactive, e.g. "a check is
 * running") and stops with the component. Call it while the component is set up (its script). */
export function poll(fn: () => unknown, ms: number, when: () => boolean = () => true): void {
	$effect(() => {
		if (!when()) return;
		return untrack(() => repeat(fn, ms));
	});
}
