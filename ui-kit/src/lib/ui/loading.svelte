<script lang="ts">
	// "Loading…" where something is on its way: a small turning mark and the words (say what, when it helps:
	// "Asking HiroLeague…").
	// UI kit, step 7b: the turning mark is shadcn-svelte's Spinner; the words beside it are the kit's.
	import { Spinner } from '$kit/components/ui/spinner/index.js';
	import { cn } from '$kit/utils';

	let { label = 'Loading…', class: className }: { label?: string; class?: string } = $props();
</script>

<p class={cn('flex items-center gap-2 text-sm text-muted-foreground', className)} role="status" aria-live="polite">
	<Spinner role="presentation" aria-label={undefined} />{label}
</p>
