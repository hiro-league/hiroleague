<script lang="ts">
	// A small heading over a group inside a card or panel ("EVENT TYPES", "WHAT USES IT"): quiet, small capitals.
	// `actions` sit at its right (a count, a small button). UI kit, step 5: each app wrote this span by hand.
	import type { Snippet } from 'svelte';
	import { cn } from '$kit/utils';

	interface Props {
		class?: string;
		children: Snippet;
		actions?: Snippet;
		/** The heading level, for screen readers; a plain span when not given. */
		level?: 2 | 3 | 4;
	}
	let { class: className, children, actions, level }: Props = $props();
	const tag = $derived(level ? `h${level}` : 'span');
</script>

{#if actions}
	<div class={cn('flex items-center justify-between gap-2', className)}>
		<svelte:element this={tag} class="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{@render children()}</svelte:element>
		<div class="flex items-center gap-1.5">{@render actions()}</div>
	</div>
{:else}
	<svelte:element this={tag} class={cn('block text-[11px] font-semibold tracking-wide text-muted-foreground uppercase', className)}>{@render children()}</svelte:element>
{/if}
