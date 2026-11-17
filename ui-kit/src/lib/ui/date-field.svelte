<script lang="ts">
	// A day, shown the house's way ("Tue, Oct 6"); a click opens a calendar to pick another. The value is
	// YYYY-MM-DD, as the entry keeps it.
	// UI kit, step 7c: shadcn-svelte's Date Picker (a Popover with its Calendar), not the browser's own date picker
	// behind a hidden input; the button's words and the clear button are the kit's.
	import { parseDate, type DateValue } from '@internationalized/date';
	import { Button } from '$kit/components/ui/button/index.js';
	import { Calendar } from '$kit/components/ui/calendar/index.js';
	import * as Popover from '$kit/components/ui/popover/index.js';
	import { dayOf, shortDate, weekday } from '$kit/format/time';
	import { CalendarDays, X } from '@lucide/svelte';

	interface Props {
		value: string;
		onchange: (v: string) => void;
		label?: string; // the button's words instead of the date (e.g. "Skip a day…")
		min?: string;
		max?: string;
		/** a small X beside the day that sends "" (the field is optional) */
		clearable?: boolean;
		disabled?: boolean;
	}
	let { value, onchange, label, min, max, clearable = false, disabled = false }: Props = $props();
	let open = $state(false);
	const text = $derived(value ? `${weekday(dayOf(value))}, ${shortDate(dayOf(value))}` : 'Pick a day');
	const day = (v: string | undefined) => (v ? parseDate(v) : undefined);

	function picked(d: DateValue | undefined) {
		if (!d) return; // a click on the picked day again: keep it
		open = false;
		const v = d.toString(); // YYYY-MM-DD
		if (v !== value) onchange(v);
	}
</script>

<span class="inline-flex items-center gap-1">
	<Popover.Root bind:open>
		<Popover.Trigger {disabled}>
			{#snippet child({ props })}
				<Button {...props} size="sm" variant="outline" {disabled}><CalendarDays />{label ?? text}</Button>
			{/snippet}
		</Popover.Trigger>
		<Popover.Content class="w-auto overflow-hidden p-0" align="start">
			<Calendar type="single" value={day(value)} onValueChange={picked} minValue={day(min)} maxValue={day(max)} captionLayout="dropdown" />
		</Popover.Content>
	</Popover.Root>
	{#if clearable && value}<Button size="icon-xs" variant="ghost" {disabled} aria-label="Clear the day" title="Clear" onclick={() => onchange('')}><X /></Button>{/if}
</span>
