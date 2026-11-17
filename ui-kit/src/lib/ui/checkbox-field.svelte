<script lang="ts">
	// A checkbox on a row of its own: the label, a "?" with help beside it, a longer explanation (markup) under it, and
	// "back to the default" while the row is pointed at or focused. `anchor` tags the row so a search can scroll to it,
	// as Field does.
	// UI kit, step 7c: built on shadcn-svelte's Field (horizontal, its content, title and description), the whole row
	// one label so a click anywhere ticks it; the boxed row, the help tip and "back to the default" are the kit's.
	import type { Snippet } from 'svelte';
	import { Checkbox } from '$kit/components/ui/checkbox/index.js';
	import * as Field from '$kit/components/ui/field/index.js';
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

<Field.Label
	data-field-anchor={anchor}
	class={cn('group w-full rounded-md border-border/50 bg-card/45 font-sans', className)}
>
	<!-- the label pads the row inside it (p-2.5, from a child selector): the kit's own padding needs the ! to win -->
	<Field.Field
		orientation="horizontal"
		class={cn('gap-3 px-3!', details ? 'py-2.5!' : 'min-h-10 items-center! py-0!')}
		data-disabled={disabled ? true : undefined}
	>
		<Checkbox bind:checked {disabled} onCheckedChange={() => onchange?.()} />
		<Field.Content>
			<Field.Title class="gap-1.5">
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
			</Field.Title>
			{#if details}<Field.Description class="text-xs">{@render details()}</Field.Description>{/if}
		</Field.Content>
	</Field.Field>
</Field.Label>
