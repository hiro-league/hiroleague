<script lang="ts">
	// A time of day as hour, minute and AM/PM (the browser's own time box can show a 24-hour clock).
	// The value is "HH:MM", 24-hour, as the entry keeps it.
	interface Props {
		value: string;
		onchange: (v: string) => void;
		label?: string;
	}
	let { value, onchange, label = 'Time' }: Props = $props();
	const h24 = $derived(Number(value.split(':')[0]));
	const min = $derived(Number(value.split(':')[1]));
	const h12 = $derived(h24 % 12 || 12);
	const pm = $derived(h24 >= 12);
	const pad = (n: number) => String(n).padStart(2, '0');
	const set = (h: number, m: number, p: boolean) => onchange(`${pad((h % 12) + (p ? 12 : 0))}:${pad(m)}`);
	const MINUTES = Array.from({ length: 12 }, (_, k) => k * 5);
	const SELECT = 'h-8 rounded-md border bg-background px-1.5 text-sm tabular-nums';
</script>

<span class="inline-flex items-center gap-1" role="group" aria-label={label}>
	<select class={SELECT} aria-label="Hour" value={h12} onchange={(e) => set(Number(e.currentTarget.value), min, pm)}>
		{#each Array.from({ length: 12 }, (_, k) => k + 1) as h (h)}<option value={h}>{h}</option>{/each}
	</select>
	<span class="text-muted-foreground">:</span>
	<select class={SELECT} aria-label="Minute" value={min} onchange={(e) => set(h12, Number(e.currentTarget.value), pm)}>
		{#if !MINUTES.includes(min)}<option value={min}>{pad(min)}</option>{/if}
		{#each MINUTES as m (m)}<option value={m}>{pad(m)}</option>{/each}
	</select>
	<select class={SELECT} aria-label="AM or PM" value={pm ? 'PM' : 'AM'} onchange={(e) => set(h12, min, e.currentTarget.value === 'PM')}>
		<option value="AM">AM</option>
		<option value="PM">PM</option>
	</select>
</span>
