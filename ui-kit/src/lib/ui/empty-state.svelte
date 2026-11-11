<script lang="ts">
	// What a list, table or section shows when it has loaded and holds nothing: the words, an optional line under
	// them (why, or what to do), an icon above and actions below (Add the first one).
	// UI kit, step 2: from the HiroLeague admin's InlineEmptyState.
	import type { Snippet } from 'svelte';
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

<div class={cn('flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center', className)}>
	{#if icon}<div class="text-muted-foreground [&_svg]:size-6">{@render icon()}</div>{/if}
	<p class="text-sm text-muted-foreground">{message}</p>
	{#if hint}<p class="text-xs text-muted-foreground/80">{hint}</p>{/if}
	{#if actions}<div class="mt-2 flex flex-wrap items-center justify-center gap-2">{@render actions()}</div>{/if}
</div>
