<script lang="ts">
	// A section of a page in a card: its title and a line under it on the left, its actions on the right, then
	// what it holds. One way to write the card header that pages wrote by hand in two ways.
	// UI kit, step 2: the HiroLeague admin's SectionCard, on the kit's Card.
	import type { Snippet } from 'svelte';
	import * as Card from '$kit/components/ui/card/index.js';

	interface Props {
		title?: string;
		description?: string;
		class?: string;
		actions?: Snippet;
		children: Snippet;
		footer?: Snippet;
	}
	let { title, description, class: className, actions, children, footer }: Props = $props();
</script>

<Card.Root class={className}>
	{#if title || actions}
		<Card.Header>
			{#if title}<Card.Title>{title}</Card.Title>{/if}
			{#if description}<Card.Description>{description}</Card.Description>{/if}
			{#if actions}<Card.Action class="flex flex-wrap items-center gap-2">{@render actions()}</Card.Action>{/if}
		</Card.Header>
	{/if}
	<Card.Content>{@render children()}</Card.Content>
	{#if footer}<Card.Footer class="gap-2">{@render footer()}</Card.Footer>{/if}
</Card.Root>
