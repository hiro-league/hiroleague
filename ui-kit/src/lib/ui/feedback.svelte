<script lang="ts">
	// What a button did, in one line under it: what went wrong (red), else what it did (green). Give it
	// the Action; `error` adds a problem from elsewhere (e.g. reading the page's data).
	import type { Action } from '$kit/state/action.svelte';

	let { action, error = '', class: cls = 'text-sm' }: { action?: Action; error?: string; class?: string } = $props();
	const problem = $derived(action?.error || error);
	const done = $derived(action?.done ?? '');
</script>

{#if problem}
	<p class="{cls} text-destructive" role="alert">{problem}</p>
{:else if done}
	<p class="{cls} text-success" role="status">{done}</p>
{/if}
