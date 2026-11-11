<script lang="ts">
	// A checkbox on a row of its own: the label, a "?" with help beside it, a longer explanation (markup) under it, and
	// "back to the default" while the row is pointed at or focused. `anchor` tags the row so a search can scroll to it,
	// as Field does. UI kit, step 7: from the HiroLeague admin's SettingToggle.
	import type { Snippet } from 'svelte';
		import { Checkbox } from '$kit/components/ui/checkbox/index.js';
	import HelpTip from '$kit/ui/help-tip.svelte';
	import ResetButton from '$kit/ui/reset-button.svelte';
	import { cn } from '$kit/utils';

	interface Props {
		label: string;
		checked?: boolean;
		disabled?: boolean;
		help?: string; // plain words behind the "?"
		details?: Snippet; // longer help under the label, for markup the tooltip can't carry
		onchange?: () => void;
		onreset?: () => void;
		anchor?: string;
		class?: string;
	}
	let { label, checked = $bindable(false), disabled = false, help, details, onchange, onreset, anchor, class: className = '' }: Props = $props();
</script>

<label
	data-field-anchor={anchor}
	class={cn(
		'group flex gap-3 rounded-md border border-border/50 bg-card/45 px-3',
		details ? 'items-start py-2.5' : 'min-h-10 items-center',
		className
	)}
>
	<Checkbox class={details ? 'mt-0.5' : undefined} bind:checked {disabled} onCheckedChange={() => onchange?.()} />
	{#snippet labelRow()}
		<span class="inline-flex items-center gap-1.5 font-sans text-sm font-medium">
			<!-- data-slot="label" is what a search lights up; the title shows the dotted setting path on hover -->
			<span data-slot="label" title={anchor}>{label}</span>
			{#if help?.trim()}<HelpTip {label} text={help} />{/if}
			{#if onreset}
				<ResetButton
					{onreset}
					label="Set {label} back to its default"
					class="opacity-0 group-focus-within:opacity-100 group-hover:opacity-100 focus-visible:opacity-100"
				/>
			{/if}
		</span>
	{/snippet}
	{#if details}
		<span class="grid gap-0.5">
			{@render labelRow()}
			<span class="font-sans text-xs text-muted-foreground">
				{@render details()}
			</span>
		</span>
	{:else}
		{@render labelRow()}
	{/if}
</label>
