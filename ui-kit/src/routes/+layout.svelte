<script lang="ts">
	// The kit's gallery runs as a small app of its own: the shared shell around its one page, with the sample app
	// (src/sample) standing in for a real one.
	import './layout.css';
	import AppShell from '$kit/components/app-shell.svelte';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href="/favicon.svg" />
</svelte:head>

<AppShell>{@render children()}</AppShell>
