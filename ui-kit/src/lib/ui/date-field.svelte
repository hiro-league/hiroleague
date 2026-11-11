<script lang="ts">
	// A day, shown the house's way ("Tue, Oct 6"); a click opens the browser's date picker. The value is
	// YYYY-MM-DD, as the entry keeps it.
	import { Button } from '$kit/components/ui/button/index.js';
	import { dayOf, shortDate, weekday } from '$kit/format/time';
	import { CalendarDays } from '@lucide/svelte';

	interface Props {
		value: string;
		onchange: (v: string) => void;
		label?: string; // the button's words instead of the date (e.g. "Skip a day…")
		min?: string;
		disabled?: boolean;
	}
	let { value, onchange, label, min, disabled = false }: Props = $props();
	let input = $state<HTMLInputElement>();
	const text = $derived(value ? `${weekday(dayOf(value))}, ${shortDate(dayOf(value))}` : 'Pick a day');
</script>

<span class="relative inline-flex">
	<Button size="sm" variant="outline" {disabled} onclick={() => input?.showPicker()}><CalendarDays />{label ?? text}</Button>
	<input bind:this={input} type="date" class="pointer-events-none absolute inset-0 opacity-0" tabindex="-1" aria-hidden="true" {value} {min} onchange={(e) => e.currentTarget.value && onchange(e.currentTarget.value)} />
</span>
