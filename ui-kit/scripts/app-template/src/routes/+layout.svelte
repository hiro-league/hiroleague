<script lang="ts">
	// The app's own layout: its colours, its tab icon, and the shared shell around every page
	// (lib/components/app-shell.svelte: sign-in, the menu, the page). UI kit, step 1c: the shell's logic moved
	// there, so an app's layout only says what is its own (a top bar, banners, another signed-out view).
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import AppShell from '$kit/components/app-shell.svelte';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<AppShell>{@render children()}</AppShell>
