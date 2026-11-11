<script lang="ts">
	// A page's filters further down (a list's search and pickers): they stick right under the page's header
	// (PageHeader) while the list scrolls. It sticks only while its parent box is on screen, so put it in the box
	// that holds the list. `class` for the background inside a card (bg-card).
	// Its height is published as --sticky-bar, so a table's head can stick right under it (UI kit, step 3: the
	// HiroLeague admin's tables do), and it clears the app's top bar when there is one (--app-top).
	import type { Snippet } from 'svelte';

	interface Props {
		class?: string;
		children: Snippet;
	}
	let { class: cls = 'bg-background', children }: Props = $props();

	let height = $state(0);
	$effect(() => {
		document.documentElement.style.setProperty('--sticky-bar', `${height}px`);
		return () => document.documentElement.style.removeProperty('--sticky-bar');
	});
</script>

<div class={['sticky top-[calc(var(--app-top,0px)+var(--page-header,0px))] z-10 py-2', cls]} bind:clientHeight={height}>{@render children()}</div>
