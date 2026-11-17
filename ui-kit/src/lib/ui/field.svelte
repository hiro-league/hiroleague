<script lang="ts">
	// One field of a form: its label, the control, and a line of help under it. `help` is a longer explanation
	// behind a small "?" beside the label; `onreset` adds "back to the default", shown while the field is pointed at
	// or focused; `error` is what is wrong with the value, under the control; `anchor` tags the field so a search
	// can scroll to it (a settings page's "find a setting").
	// UI kit, step 7c: built on shadcn-svelte's Field (its label, description and error, and data-invalid while there
	// is an error); the help tip and "back to the default" beside the label are the kit's.
	import type { Snippet } from 'svelte';
	import * as Field from '$kit/components/ui/field/index.js';
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

<!-- w-auto: shadcn's Field is w-full; the kit's sized to its content inside a row (a toolbar's filters) and fills a column
     anyway (a block flex box fills its parent), as the grid it was before 7c did -->
<Field.Field class={cn('w-auto', className)} data-field-anchor={anchor} data-invalid={error ? true : undefined}>
	{#if label}
		<div class="flex items-center gap-1.5">
			<Field.Label for={htmlFor}>{label}</Field.Label>
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
	{#if error}<Field.Error class="text-xs">{error}</Field.Error>
	{:else if hint}<Field.Description class="text-xs">{hint}</Field.Description>{/if}
</Field.Field>
