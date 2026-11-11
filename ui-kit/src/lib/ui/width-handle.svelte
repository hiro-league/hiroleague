<script lang="ts">
	// The handle on a side panel's left edge (wide screens): a thin line with a grip in its middle, to drag
	// the panel wider or narrower (drag-width.ts). Put it inside the panel's `relative` box.
	import { GripVertical } from '@lucide/svelte';
	import { dragWidth } from './drag-width';

	let { width = $bindable(), min, max }: { width: number; min: number; max: number } = $props();
</script>

<div
	class="group absolute inset-y-0 -left-3 z-10 hidden w-3 cursor-col-resize justify-center xl:flex"
	role="separator"
	aria-orientation="vertical"
	aria-label="Drag to size this panel"
	title="Drag to size this panel"
	onpointerdown={(e) => dragWidth(e, width, (w) => (width = w), min, max)}
>
	<div class="h-full w-px bg-border group-hover:w-0.5 group-hover:bg-primary/60"></div>
	<div
		class="absolute top-1/2 flex h-8 w-3 -translate-y-1/2 items-center justify-center rounded-sm border bg-background text-muted-foreground group-hover:border-primary/60 group-hover:text-foreground"
	>
		<GripVertical class="size-3" />
	</div>
</div>
