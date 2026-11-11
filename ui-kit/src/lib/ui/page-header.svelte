<script lang="ts">
	// The top of every page: its title with its tabs on the same line (they scroll sideways when the window is too
	// narrow, never drop to a line of their own), the page's actions to the right, and an optional row under them
	// (inner tabs, filters). It stays at the top of the window while the page scrolls. Its height is published as
	// --page-header, so a bar further down the page can stick right under it (StickyBar).
	import type { Snippet } from 'svelte';

	interface Props {
		title?: string;
		heading?: Snippet; // in place of the title (a floor picker)
		tabs?: Snippet;
		actions?: Snippet; // right of the tabs; may wrap under them on a narrow window
		children?: Snippet; // the row under the title: inner tabs, filters
	}
	let { title, heading, tabs, actions, children }: Props = $props();

	let height = $state(0);
	$effect(() => {
		document.documentElement.style.setProperty('--page-header', `${height}px`);
		return () => document.documentElement.style.removeProperty('--page-header');
	});
</script>

<header class="sticky top-0 z-20 -mx-4 -mt-2 mb-3 bg-background/85 px-4 py-2 backdrop-blur md:-mx-6 md:px-6" bind:clientHeight={height}>
	<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
		<div class="flex max-w-full min-w-0 items-center gap-4">
			{#if heading}{@render heading()}{:else}<h1 class="brand-text-gradient shrink-0 text-xl font-semibold">{title}</h1>{/if}
			{#if tabs}<div class="min-w-0 overflow-x-auto overflow-y-hidden [scrollbar-width:none]">{@render tabs()}</div>{/if}
		</div>
		{#if actions}<div class="ml-auto flex flex-wrap items-center gap-2">{@render actions()}</div>{/if}
	</div>
	{#if children}<div class="mt-2">{@render children()}</div>{/if}
</header>
