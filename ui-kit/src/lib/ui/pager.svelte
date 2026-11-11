<script lang="ts">
	// "1–50 of 312" with Previous and Next, for long site lists (Settings → AdGuard).
	import { Button } from '$kit/components/ui/button/index.js';

	let { page = $bindable(0), size, count }: { page?: number; size: number; count: number } = $props();
	const last = $derived(Math.max(0, Math.ceil(count / size) - 1));
	$effect(() => {
		if (page > last) page = last;
	});
</script>

{#if count > size}
	<div class="flex items-center gap-2 text-xs text-muted-foreground">
		<span class="tabular-nums">{page * size + 1}–{Math.min(count, (page + 1) * size)} of {count}</span>
		<Button size="sm" variant="outline" class="h-7" disabled={page === 0} onclick={() => page--}>Previous</Button>
		<Button size="sm" variant="outline" class="h-7" disabled={page >= last} onclick={() => page++}>Next</Button>
	</div>
{/if}
