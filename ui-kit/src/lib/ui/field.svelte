<script lang="ts">
	// One field of a form: its label, the control, and a line of help under it. `help` is a longer explanation
	// behind a small "?" beside the label; `onreset` adds "back to the default", shown while the field is pointed at
	// or focused; `error` is what is wrong with the value, under the control; `anchor` tags the field so a search
	// can scroll to it (a settings page's "find a setting").
	// UI kit, step 2: from the HiroLeague admin's FormField (hint, help tip, reset to default, search anchor).
	import type { Snippet } from 'svelte';
	import { Label } from '$kit/components/ui/label/index.js';
	import HelpTip from '$kit/ui/help-tip.svelte';
	import ResetButton from '$kit/ui/reset-button.svelte';
	import { cn } from '$kit/utils';

	interface Props {
		label?: string; // none: the field has no caption (a bare control with a hint or an error)
		for?: string; // the control's id, so a click on the label goes to it
		hint?: string;
		help?: string;
		error?: string;
		onreset?: () => void;
		anchor?: string;
		class?: string;
		children: Snippet;
	}
	let { label = '', for: htmlFor, hint, help, error, onreset, anchor, class: className, children }: Props = $props();
</script>

<div class={cn('group/field grid gap-2', className)} data-field-anchor={anchor}>
	{#if label}
		<div class="flex items-center gap-1.5">
			<Label for={htmlFor}>{label}</Label>
			{#if help}<HelpTip {label} text={help} />{/if}
			{#if onreset}
				<ResetButton
					{onreset}
					label="Set {label} back to its default"
					class="opacity-0 group-focus-within/field:opacity-100 group-hover/field:opacity-100 focus-visible:opacity-100"
				/>
			{/if}
		</div>
	{/if}
	{@render children()}
	{#if error}<p class="text-xs text-destructive" role="alert">{error}</p>
	{:else if hint}<p class="text-xs text-muted-foreground">{hint}</p>{/if}
</div>
