<script lang="ts">
	// One option in an options panel (the floor plan's): its name on the left, its control on the right. `off`: it does
	// nothing now, so it is dimmed and says why. With `checked` (and no children) the control is a switch.
	import { Switch } from '$kit/components/ui/switch/index.js';
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		title?: string; // what it does, on hover
		/** a line of help under the name (UI kit, step 5: settings rows) */
		hint?: string;
		off?: string | null; // why it does nothing now
		checked?: boolean;
		onchange?: (v: boolean) => void;
		children?: Snippet;
	}
	let { label, title, hint, off = null, checked, onchange, children }: Props = $props();
</script>

<div class={['flex min-h-8 items-center justify-between gap-3', off && 'pointer-events-none opacity-50']} title={off ?? title}>
	{#if hint}<span class="grid gap-0.5"><span class="text-xs">{label}</span><span class="text-[11px] text-muted-foreground">{hint}</span></span>{:else}<span class="text-xs">{label}</span>{/if}
	{#if children}
		{@render children()}
	{:else}
		<Switch size="sm" checked={!!checked} onCheckedChange={(v) => onchange?.(v)} aria-label={label} />
	{/if}
</div>
