<script lang="ts">
	// A side panel that shows one thing (not an editor: EditorSheet edits): a small line over the title, the title (with
	// something beside it: a status dot), what it holds in a middle that scrolls, and actions at the bottom (Change,
	// Open). The page behind stays readable: a light dim and a slight blur. UI kit, step 5: NetHiro copied this setup into
	// five detail panels.
	import type { Snippet } from 'svelte';
	import * as Sheet from '$kit/components/ui/sheet/index.js';
	import { cn } from '$kit/utils';

	interface Props {
		open: boolean;
		title?: string;
		/** The small line over the title (what kind, where). */
		description?: string;
		/** Beside the title (a status dot, an icon). */
		adornment?: Snippet;
		/** In place of the title's words. */
		heading?: Snippet;
		children: Snippet;
		actions?: Snippet;
		/** Wider, for panels that hold a chart or a table. */
		wide?: boolean;
		class?: string;
	}
	let { open = $bindable(), title, description, adornment, heading, children, actions, wide = false, class: className }: Props = $props();
</script>

<Sheet.Root bind:open>
	<Sheet.Content
		class={cn('flex w-full flex-col', wide ? 'data-[side=right]:sm:max-w-xl' : 'sm:max-w-md', className)}
		overlayClass="bg-black/5 supports-backdrop-filter:backdrop-blur-[1px]"
	>
		<Sheet.Header>
			{#if description}<Sheet.Description>{description}</Sheet.Description>{/if}
			<Sheet.Title class="flex items-center gap-2">
				{#if adornment}{@render adornment()}{/if}
				{#if heading}{@render heading()}{:else}{title}{/if}
			</Sheet.Title>
		</Sheet.Header>
		<div class="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 pb-6 text-sm">{@render children()}</div>
		{#if actions}<Sheet.Footer class="flex-row flex-wrap justify-end gap-2 border-t">{@render actions()}</Sheet.Footer>{/if}
	</Sheet.Content>
</Sheet.Root>
