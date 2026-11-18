<script lang="ts">
	// One option in an options panel (the floor plan's): its name on the left, its control on the right. `off`: it does
	// nothing now, so it is dimmed and says why. With `checked` (and no children) the control is a switch.
	// UI kit, step 7d: shadcn-svelte's Item (its content, title, description and actions), packed tight for a panel.
	import * as Item from '$kit/components/ui/item/index.js';
	import { Switch } from '$kit/components/ui/switch/index.js';
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		title?: string; // what it does, on hover
		/** a line of help under the name (settings rows) */
		hint?: string;
		off?: string | null; // why it does nothing now
		checked?: boolean;
		onchange?: (v: boolean) => void;
		children?: Snippet;
	}
	let { label, title, hint, off = null, checked, onchange, children }: Props = $props();
</script>

<Item.Root size="xs" class={['min-h-8 flex-nowrap gap-3 border-0 p-0', off && 'pointer-events-none opacity-50']} title={off ?? title}>
	<Item.Content class="gap-0.5">
		<Item.Title class="text-xs font-normal">{label}</Item.Title>
		{#if hint}<Item.Description class="text-[11px]">{hint}</Item.Description>{/if}
	</Item.Content>
	<Item.Actions>
		{#if children}
			{@render children()}
		{:else}
			<Switch size="sm" checked={!!checked} onCheckedChange={(v) => onchange?.(v)} aria-label={label} />
		{/if}
	</Item.Actions>
</Item.Root>
