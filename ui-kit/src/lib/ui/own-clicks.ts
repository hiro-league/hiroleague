// For buttons over a plan view (the 3D view's markers, the room arrows): keeps a press from reaching
// the 3D orbit controls, which would capture the pointer so the click never arrives. A listener on the
// element itself, since Svelte handles `onpointerdown` at the page root, after the controls have seen
// the press. No three.js here: pages without 3D use it too.
export function ownClicks(el: HTMLElement) {
	const stop = (e: PointerEvent) => e.stopPropagation();
	el.addEventListener('pointerdown', stop);
	return () => el.removeEventListener('pointerdown', stop);
}
