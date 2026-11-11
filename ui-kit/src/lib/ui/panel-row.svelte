<script lang="ts">
	// One option in an options panel (the floor plan's): its name on the left, its control on the right. `off`: it does
	// nothing now, so it is dimmed and says why. With `checked` (and no children) the control is a switch.
	import { Switch } from '$kit/components/ui/switch/index.js';
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		title?: string; // what it does, on hover
		off?: string | null; // why it does nothing now
		checked?: boolean;
		onchange?: (v: boolean) => void;
		children?: Snippet;
	}
	let { label, title, off = null, checked, onchange, children }: Props = $props();
</script>

<div class={['flex min-h-8 items-center justify-between gap-3', off && 'pointer-events-none opacity-50']} title={off ?? title}>
	<span class="text-xs">{label}</span>
	{#if children}
		{@render children()}
	{:else}
		<Switch size="sm" checked={!!checked} onCheckedChange={(v) => onchange?.(v)} aria-label={label} />
	{/if}
</div>
