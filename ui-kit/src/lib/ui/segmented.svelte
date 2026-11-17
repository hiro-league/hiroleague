<script lang="ts" generics="T extends string | number | boolean">
	// One of a few choices, side by side (Group by, 24 h / 7 days, zoom steps), each a label with an
	// optional icon and a count (how many each holds): the picked one stands out, and screen readers hear which is
	// pressed. `stretch` fills the width.
	// UI kit, step 7b: built on shadcn-svelte's Toggle Group (single), not on buttons of its own. Its values are
	// strings, so a choice is found again by its value's string; clicking the picked one again keeps it picked.
	import type { Component } from 'svelte';
	import * as ToggleGroup from '$kit/components/ui/toggle-group/index.js';
	import { cn } from '$kit/utils';

	interface Props {
		options: readonly { value: T; label: string; title?: string; icon?: Component; count?: number; iconOnly?: boolean }[];
		value: T | null; // null: none is picked (e.g. days picked on a calendar instead)
		onchange: (v: T) => void;
		size?: 'xs' | 'sm';
		label?: string; // what the group chooses, for screen readers
		/** fill the width, the choices sharing it evenly */
		stretch?: boolean;
		class?: string;
	}
	let { options, value, onchange, size = 'xs', label, stretch = false, class: className }: Props = $props();

	function pick(next: string) {
		if (!next) return; // Toggle Group lets the picked one go; a Segmented always has one (or none, from outside)
		const o = options.find((o) => String(o.value) === next);
		if (o && o.value !== value) onchange(o.value);
	}
</script>

<ToggleGroup.Root
	type="single"
	bind:value={() => (value === null ? '' : String(value)), pick}
	spacing={0.5}
	aria-label={label}
	class={cn('rounded-md border p-0.5', stretch ? 'w-full' : 'w-fit', size === 'xs' ? 'text-xs' : 'text-sm', className)}
>
	{#each options as o (String(o.value))}
		<ToggleGroup.Item
			value={String(o.value)}
			title={o.title ?? (o.iconOnly ? o.label : undefined)}
			aria-label={o.iconOnly ? o.label : undefined}
			class={cn(
				'h-auto min-w-0 gap-1 rounded text-[length:inherit] font-normal text-muted-foreground hover:bg-transparent data-[state=on]:font-medium data-[state=on]:text-foreground [&_svg:not([class*=size-])]:size-3.5',
				stretch && 'flex-1',
				size === 'xs' ? 'px-2 py-1' : 'px-3 py-1'
			)}
			>{#if o.icon}<o.icon />{/if}{#if !o.iconOnly}{o.label}{/if}{#if o.count !== undefined}<span class="text-muted-foreground tabular-nums">{o.count}</span>{/if}</ToggleGroup.Item
		>
	{/each}
</ToggleGroup.Root>
