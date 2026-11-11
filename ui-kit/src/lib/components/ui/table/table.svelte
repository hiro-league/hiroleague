<script lang="ts">
	import { cn, type WithElementRef } from "$kit/utils.js";
	import type { HTMLTableAttributes } from "svelte/elements";

	let {
		ref = $bindable(null),
		class: className,
		children,
		compact = false, // UI kit, step 3: dense lists (logs, runs): smaller words, tighter rows
		scroll = true, // false: no side-scroll wrapper, so a sticky head pins to the parent that scrolls (not to the wrapper)
		...restProps
	}: WithElementRef<HTMLTableAttributes> & { compact?: boolean; scroll?: boolean } = $props();
</script>

<div data-slot="table-container" class={["relative w-full", scroll && "overflow-x-auto"]}>
	<table bind:this={ref} data-slot="table" class={cn("w-full caption-bottom text-sm", compact && "text-xs [&_td]:px-2 [&_td]:py-1 [&_th]:h-8", className)} {...restProps}>
		{@render children?.()}
	</table>
</div>
