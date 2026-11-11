<script lang="ts">
	// A boxed line that must not be missed, in the page where it applies: what went wrong (error), what to look at
	// (warning), what went well (success) or what to know (info). An optional title, the words, and actions on the
	// right (Retry, Open settings). For the one-line result under a button, use Feedback; for something that happened
	// while the person looks elsewhere, a toast.
	// UI kit, step 2: from the HiroLeague admin's InlineDestructiveAlert and InlineWarningAlert, on the kit's colours.
	import type { Snippet } from 'svelte';
	import { CircleCheck, Info, TriangleAlert } from '@lucide/svelte';
	import { cn } from '$kit/utils';

	interface Props {
		tone?: 'error' | 'warning' | 'success' | 'info';
		title?: string;
		message?: string; // the words, when they are plain text; else `children`
		class?: string;
		/** sm: one tight line, a smaller icon (a note inside a form or a row). UI kit, step 5. */
		size?: 'default' | 'sm';
		children?: Snippet;
		actions?: Snippet;
	}
	let { tone = 'error', title, message, class: className, size = 'default', children, actions }: Props = $props();

	const TONE = {
		error: 'border-destructive/40 bg-destructive/10 [&_[data-icon]]:text-destructive',
		warning: 'border-warning/40 bg-warning/10 [&_[data-icon]]:text-warning',
		success: 'border-success/40 bg-success/10 [&_[data-icon]]:text-success',
		info: 'border-primary/40 bg-primary/10 [&_[data-icon]]:text-primary'
	} as const;
	const Icon = $derived(tone === 'success' ? CircleCheck : tone === 'info' ? Info : TriangleAlert);
</script>

<div class={cn('flex items-start rounded-lg border', size === 'sm' ? 'gap-2 px-2.5 py-1.5 text-xs' : 'gap-2.5 p-3 text-sm', TONE[tone], className)} role={tone === 'error' ? 'alert' : 'status'}>
	<Icon data-icon class={size === 'sm' ? 'mt-px size-3.5 shrink-0' : 'mt-0.5 size-4 shrink-0'} />
	<div class="min-w-0 flex-1">
		{#if title}<div class="font-medium">{title}</div>{/if}
		<div class={['break-words', title && 'text-muted-foreground']}>{#if children}{@render children()}{:else}{message}{/if}</div>
	</div>
	{#if actions}<div class="flex shrink-0 flex-wrap items-center gap-2">{@render actions()}</div>{/if}
</div>
