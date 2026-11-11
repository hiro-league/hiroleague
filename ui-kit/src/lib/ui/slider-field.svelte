<script lang="ts">
	// A number picked on a slider, in a form: the label, the value as it stands (in its unit), the slider, and
	// "back to the default" when the app gives one. `format` writes the value (a percent, a duration).
	// UI kit, step 3: the apps and the admin each built this from a bare range input and a span.
	import { Slider } from '$kit/components/ui/slider/index.js';
	import Field from '$kit/ui/field.svelte';

	interface Props {
		label: string;
		value: number;
		onchange: (v: number) => void;
		min?: number;
		max?: number;
		step?: number;
		format?: (v: number) => string;
		hint?: string;
		help?: string;
		/** the default: shows "back to the default" while the value differs */
		reset?: number;
		/** a default that is not a number ("not set"): your own reset, shown while `modified` (default true) */
		onreset?: () => void;
		modified?: boolean;
		/** called once when the slider is let go (a save, an undo step), not on every move */
		oncommit?: (v: number) => void;
		disabled?: boolean;
		id?: string;
		class?: string;
	}
	let { label, value, onchange, min = 0, max = 100, step = 1, format = String, hint, help, reset, onreset, modified = true, oncommit, disabled = false, id, class: className }: Props = $props();
	const resetNow = $derived(onreset ? (modified ? onreset : undefined) : reset !== undefined && reset !== value ? () => onchange(reset) : undefined);
</script>

<Field {label} for={id} {hint} {help} class={className} onreset={resetNow}>
	<div class="flex items-center gap-3">
		<Slider {id} type="single" {min} {max} {step} {disabled} value={value} onValueChange={(v: number) => onchange(v)} onValueCommit={(v: number) => oncommit?.(v)} class="flex-1" aria-label={label} />
		<span class="min-w-12 text-right text-sm tabular-nums">{format(value)}</span>
	</div>
</Field>
