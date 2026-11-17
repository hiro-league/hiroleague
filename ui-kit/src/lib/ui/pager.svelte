<script lang="ts">
	// "1–50 of 312" with Previous and Next, for long site lists (Settings → AdGuard).
	// UI kit, step 7b: built on shadcn-svelte's Pagination (its Previous and Next buttons, its page state); the range
	// line is the kit's. `page` counts from 0, Pagination from 1.
	import * as Pagination from '$kit/components/ui/pagination/index.js';
	import { buttonVariants } from '$kit/components/ui/button/index.js';
	import { cn } from '$kit/utils';

	let { page = $bindable(0), size, count }: { page?: number; size: number; count: number } = $props();
	const last = $derived(Math.max(0, Math.ceil(count / size) - 1));
	$effect(() => {
		if (page > last) page = last;
	});
	const BUTTON = cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'h-7 px-2.5! text-xs');
</script>

{#if count > size}
	<Pagination.Root {count} perPage={size} bind:page={() => page + 1, (p) => (page = p - 1)} class="mx-0 w-auto justify-start">
		<div class="flex items-center gap-2 text-xs text-muted-foreground">
			<span class="tabular-nums">{page * size + 1}–{Math.min(count, (page + 1) * size)} of {count}</span>
			<Pagination.PrevButton class={BUTTON}>Previous</Pagination.PrevButton>
			<Pagination.NextButton class={BUTTON}>Next</Pagination.NextButton>
		</div>
	</Pagination.Root>
{/if}
