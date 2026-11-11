<script lang="ts">
	// The side menu's edge, in place of shadcn's rail: drag it to make the menu wider or narrower, click it to
	// collapse or expand the menu (as the rail did). Collapsed to icons, it only expands.
	import { useSidebar } from '$kit/components/ui/sidebar/index.js';
	import { clampWidth } from './sidebar-width';

	interface Props {
		width: number; // the menu's width now, in pixels
		onwidth: (px: number) => void;
	}
	let { width, onwidth }: Props = $props();

	const sidebar = useSidebar();
	let from: { x: number; width: number } | null = null;
	let dragged = false;

	const down = (e: PointerEvent) => {
		if (e.button !== 0 || sidebar.state === 'collapsed') return;
		e.preventDefault(); // no text selection or native drag takes the pointer away
		from = { x: e.clientX, width };
		dragged = false;
		(e.currentTarget as Element).setPointerCapture(e.pointerId);
	};
	const move = (e: PointerEvent) => {
		if (!from) return;
		const dx = e.clientX - from.x;
		if (!dragged && Math.abs(dx) < 4) return; // a click wobbles a little
		if (!dragged) document.documentElement.dataset.sidebarResizing = '';
		dragged = true;
		onwidth(clampWidth(from.width + dx));
	};
	const up = (e: PointerEvent) => {
		if (e.type === 'pointerup') move(e); // where it was let go, in case its last move wasn't reported (a cancel has no place)
		from = null;
		delete document.documentElement.dataset.sidebarResizing;
	};
	// A drag ends with a click too: only a click that didn't drag collapses the menu.
	const click = () => {
		if (!dragged) sidebar.toggle();
		dragged = false;
	};
</script>

<button
	type="button"
	data-sidebar="rail"
	data-slot="sidebar-rail"
	aria-label="Resize or collapse the menu"
	title={sidebar.state === 'collapsed' ? 'Expand menu' : 'Drag to resize the menu, click to collapse it'}
	tabindex={-1}
	onpointerdown={down}
	onpointermove={move}
	onpointerup={up}
	onpointercancel={up}
	onclick={click}
	class="absolute inset-y-0 -right-4 z-20 hidden w-4 -translate-x-1/2 cursor-col-resize touch-none after:absolute after:inset-y-0 after:start-1/2 after:w-[2px] hover:after:bg-sidebar-border sm:flex group-data-[collapsible=icon]:cursor-e-resize"
></button>
