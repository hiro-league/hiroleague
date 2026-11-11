<script lang="ts">
	// A page's filters further down (a list's search and pickers): they stick right under the page's header
	// (PageHeader) while the list scrolls. It sticks only while its parent box is on screen, so put it in the box
	// that holds the list. `class` for the background inside a card (bg-card).
	import type { Snippet } from 'svelte';

	interface Props {
		class?: string;
		children: Snippet;
	}
	let { class: cls = 'bg-background', children }: Props = $props();
</script>

<div class={['sticky top-[var(--page-header,0px)] z-10 py-2', cls]}>{@render children()}</div>
