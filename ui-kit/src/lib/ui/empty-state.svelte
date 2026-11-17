<script lang="ts">
	// What a list, table or section shows when it has loaded and holds nothing: the words, an optional line under
	// them (why, or what to do), an icon above and actions below (Add the first one).
	// UI kit, step 7b: built on shadcn-svelte's Empty (its media, title, description and content); the dashed box and
	// the sizes are the kit's.
	import type { Snippet } from 'svelte';
	import * as Empty from '$kit/components/ui/empty/index.js';
	import { cn } from '$kit/utils';

	interface Props {
		message: string;
		hint?: string;
		class?: string;
		icon?: Snippet;
		actions?: Snippet;
	}
	let { message, hint, class: className, icon, actions }: Props = $props();
</script>

<Empty.Root class={cn('flex-initial gap-2 rounded-lg border border-dashed px-4 py-8', className)}>
	<Empty.Header class="gap-2">
		{#if icon}<Empty.Media class="mb-0 text-muted-foreground [&_svg]:size-6">{@render icon()}</Empty.Media>{/if}
		<Empty.Title class="text-sm font-normal text-muted-foreground">{message}</Empty.Title>
		{#if hint}<Empty.Description class="text-xs text-muted-foreground/80">{hint}</Empty.Description>{/if}
	</Empty.Header>
	{#if actions}<Empty.Content class="mt-2 flex-row flex-wrap justify-center gap-2">{@render actions()}</Empty.Content>{/if}
</Empty.Root>
