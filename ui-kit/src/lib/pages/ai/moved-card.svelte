<script lang="ts">
	// The "What moved to HiroLeague" card: what a page of the app held before the core took it over, and where it is now.
	import { ArrowRight } from '@lucide/svelte';
	import Panel from '$kit/ui/panel.svelte';
	import type { Moved } from '$kit/pages/ai/types';

	let { moved }: { moved: Moved } = $props();
</script>

<Panel title={moved.title} description={moved.description}>
	<ul class="grid gap-2 text-sm">
		{#each moved.items as m (m.what)}
			<li class="flex flex-wrap items-baseline gap-x-2">
				<span class="font-medium">{m.what}</span>
				<span class="text-xs text-muted-foreground">{m.was}</span>
				<ArrowRight class="size-3 self-center text-muted-foreground" />
				<span class="text-xs">{m.page}</span>
			</li>
		{/each}
	</ul>
	{#snippet footer()}
		<p class="text-xs text-muted-foreground">{moved.footer}</p>
	{/snippet}
</Panel>
