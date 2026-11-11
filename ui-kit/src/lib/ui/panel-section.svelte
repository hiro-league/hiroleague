<script lang="ts">
	// One group of an options panel (the floor plan's plan-panel.svelte): a heading, then its rows.
	import type { Snippet } from 'svelte';

	let { title, children }: { title: string; children: Snippet } = $props();
</script>

<section class="border-t pt-2 first:border-t-0">
	<h3 class="mb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
	<div class="flex flex-col gap-1.5 pb-1">{@render children()}</div>
</section>
