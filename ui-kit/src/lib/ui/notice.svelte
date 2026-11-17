<script lang="ts">
	// A boxed line that must not be missed, in the page where it applies: what went wrong (error), what to look at
	// (warning), what went well (success) or what to know (info). An optional title, the words, and actions on the
	// right (Retry, Open settings). For the one-line result under a button, use Feedback; for something that happened
	// while the person looks elsewhere, a toast.
	// UI kit, step 7b: built on shadcn-svelte's Alert (its icon column, title and description); the four tones and the
	// actions column are the kit's.
	import type { Snippet } from 'svelte';
	import { CircleCheck, Info, TriangleAlert } from '@lucide/svelte';
	import * as Alert from '$kit/components/ui/alert/index.js';
	import { cn } from '$kit/utils';

	interface Props {
		tone?: 'error' | 'warning' | 'success' | 'info';
		title?: string;
		message?: string; // the words, when they are plain text; else `children`
		class?: string;
		/** sm: one tight line, a smaller icon (a note inside a form or a row). */
		size?: 'default' | 'sm';
		children?: Snippet;
		actions?: Snippet;
	}
	let { tone = 'error', title, message, class: className, size = 'default', children, actions }: Props = $props();

	const TONE = {
		error: 'border-destructive/40 bg-destructive/10 *:[svg]:text-destructive',
		warning: 'border-warning/40 bg-warning/10 *:[svg]:text-warning',
		success: 'border-success/40 bg-success/10 *:[svg]:text-success',
		info: 'border-primary/40 bg-primary/10 *:[svg]:text-primary'
	} as const;
	const Icon = $derived(tone === 'success' ? CircleCheck : tone === 'info' ? Info : TriangleAlert);
</script>

<Alert.Root
	role={tone === 'error' ? 'alert' : 'status'}
	class={cn(
		'text-foreground',
		actions && 'has-[>svg]:grid-cols-[auto_1fr_auto]',
		size === 'sm' ? 'px-2.5 py-1.5 text-xs *:[svg:not([class*=size-])]:size-3.5' : 'p-3',
		TONE[tone],
		className
	)}
>
	<Icon />
	{#if title}<Alert.Title>{title}</Alert.Title>{/if}
	<Alert.Description class={cn('break-words text-[length:inherit]', !title && 'text-foreground', !title && 'row-span-2 self-center')}
		>{#if children}{@render children()}{:else}{message}{/if}</Alert.Description
	>
	{#if actions}<div class="col-start-3 row-span-2 row-start-1 flex shrink-0 flex-wrap items-center gap-2 self-start">{@render actions()}</div>{/if}
</Alert.Root>
