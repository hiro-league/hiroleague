// A side panel's width, dragged by a handle on its left edge (dragging left widens it): `set` gets the
// new width as the pointer moves, kept between `min` and `max` px.
export function dragWidth(e: PointerEvent, from: number, set: (w: number) => void, min: number, max: number) {
	e.preventDefault();
	// Followed on the window, so the drag goes on wherever the pointer goes
	const x0 = e.clientX;
	const move = (m: PointerEvent) => set(Math.round(Math.max(min, Math.min(max, from + x0 - m.clientX))));
	const up = () => {
		window.removeEventListener('pointermove', move);
		window.removeEventListener('pointerup', up);
		window.removeEventListener('pointercancel', up);
	};
	window.addEventListener('pointermove', move);
	window.addEventListener('pointerup', up);
	window.addEventListener('pointercancel', up);
}

export const isWidth = (v: unknown): v is number => typeof v === 'number' && v > 0;
