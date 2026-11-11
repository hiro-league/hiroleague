<script lang="ts">
	// "Loading…" where something is on its way: a small turning mark and the words (say what, when it helps:
	// "Asking HiroLeague…"). UI kit, step 2: from the HiroLeague admin's InlineLoading.
	import { LoaderCircle } from '@lucide/svelte';
	import { cn } from '$kit/utils';

	let { label = 'Loading…', class: className }: { label?: string; class?: string } = $props();
</script>

<p class={cn('flex items-center gap-2 text-sm text-muted-foreground', className)} role="status" aria-live="polite">
	<LoaderCircle class="size-4 animate-spin" />{label}
</p>
