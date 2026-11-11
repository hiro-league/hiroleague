<script lang="ts">
	// A section of a page in a card: its title and a line under it on the left, its actions on the right, then
	// what it holds. One way to write the card header that pages wrote by hand in two ways.
	// UI kit, step 2: the HiroLeague admin's SectionCard, on the kit's Card.
	// UI kit, step 5: `details` (the line under the title when it holds more than words: a <code>, a link),
	// `contentClass` (the body's layout: grid gap-4, tighter padding), `titleClass` and `id`.
	import type { Snippet } from 'svelte';
	import * as Card from '$kit/components/ui/card/index.js';

	interface Props {
		title?: string;
		description?: string;
		details?: Snippet;
		class?: string;
		contentClass?: string;
		titleClass?: string;
		id?: string;
		actions?: Snippet;
		children: Snippet;
		footer?: Snippet;
	}
	let { title, description, details, class: className, contentClass, titleClass, id, actions, children, footer }: Props = $props();
</script>

<Card.Root class={className} {id}>
	{#if title || actions}
		<Card.Header>
			{#if title}<Card.Title class={titleClass}>{title}</Card.Title>{/if}
			{#if details}<Card.Description>{@render details()}</Card.Description>
			{:else if description}<Card.Description>{description}</Card.Description>{/if}
			{#if actions}<Card.Action class="flex flex-wrap items-center gap-2">{@render actions()}</Card.Action>{/if}
		</Card.Header>
	{/if}
	<Card.Content class={contentClass}>{@render children()}</Card.Content>
	{#if footer}<Card.Footer class="gap-2">{@render footer()}</Card.Footer>{/if}
</Card.Root>
