<script lang="ts" generics="T extends string | number | boolean">
	// One of a few choices, side by side (Group by, 24 h / 7 days, zoom steps), each a label with an
	// optional icon and a count (how many each holds): the picked one stands out, and screen readers hear which is
	// pressed. `stretch` fills the width. UI kit, step 3: count and stretch, to replace pick-one groups built from buttons.
	import type { Component } from 'svelte';

	interface Props {
		options: readonly { value: T; label: string; title?: string; icon?: Component; count?: number }[];
		value: T | null; // null: none is picked (e.g. days picked on a calendar instead)
		onchange: (v: T) => void;
		size?: 'xs' | 'sm';
		label?: string; // what the group chooses, for screen readers
		/** fill the width, the choices sharing it evenly */
		stretch?: boolean;
		class?: string;
	}
	let { options, value, onchange, size = 'xs', label, stretch = false, class: className }: Props = $props();
</script>

<div class={['flex rounded-md border p-0.5', stretch ? 'w-full' : 'w-fit', size === 'xs' ? 'text-xs' : 'text-sm', className]} role="group" aria-label={label}>
	{#each options as o (String(o.value))}
		<button
			type="button"
			class={['inline-flex items-center gap-1 rounded whitespace-nowrap [&_svg]:size-3.5', stretch && 'flex-1 justify-center', size === 'xs' ? 'px-2 py-1' : 'px-3 py-1', value === o.value ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground']}
			aria-pressed={value === o.value}
			title={o.title}
			onclick={() => onchange(o.value)}
			>{#if o.icon}<o.icon />{/if}{o.label}{#if o.count !== undefined}<span class="text-muted-foreground tabular-nums">{o.count}</span>{/if}</button
		>
	{/each}
</div>
