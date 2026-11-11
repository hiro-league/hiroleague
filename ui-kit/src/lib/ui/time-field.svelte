<script lang="ts">
	// A time of day as hour, minute and AM/PM (the browser's own time box can show a 24-hour clock).
	// The value is "HH:MM", 24-hour, as the entry keeps it. UI kit, step 3: "" is allowed (nothing picked yet: dashes);
	// the first pick fills the other two parts as 12:00 AM, and `clearable` adds an X that goes back to "".
	interface Props {
		value: string;
		onchange: (v: string) => void;
		label?: string;
		clearable?: boolean;
		disabled?: boolean;
	}
	let { value, onchange, label = 'Time', clearable = false, disabled = false }: Props = $props();
	const has = $derived(/^\d{1,2}:\d{2}$/.test(value));
	const h24 = $derived(has ? Number(value.split(':')[0]) : 0);
	const min = $derived(has ? Number(value.split(':')[1]) : 0);
	const h12 = $derived(h24 % 12 || 12);
	const pm = $derived(h24 >= 12);
	const pad = (n: number) => String(n).padStart(2, '0');
	const set = (h: number, m: number, p: boolean) => onchange(`${pad((h % 12) + (p ? 12 : 0))}:${pad(m)}`);
	const MINUTES = Array.from({ length: 12 }, (_, k) => k * 5);
	const SELECT = 'h-8 rounded-md border bg-background px-1.5 text-sm tabular-nums';
</script>

<span class="inline-flex items-center gap-1" role="group" aria-label={label}>
	<select class={SELECT} aria-label="Hour" {disabled} value={has ? h12 : ''} onchange={(e) => set(Number(e.currentTarget.value), min, pm)}>
		{#if !has}<option value="" disabled>--</option>{/if}
		{#each Array.from({ length: 12 }, (_, k) => k + 1) as h (h)}<option value={h}>{h}</option>{/each}
	</select>
	<span class="text-muted-foreground">:	{#if clearable && has}<button type="button" class="text-muted-foreground hover:text-foreground" aria-label="Clear the time" title="Clear" {disabled} onclick={() => onchange('')}>×</button>{/if}
</span>
	<select class={SELECT} aria-label="Minute" {disabled} value={has ? min : ''} onchange={(e) => set(h12, Number(e.currentTarget.value), pm)}>
		{#if !has}<option value="" disabled>--</option>{/if}
		{#if has && !MINUTES.includes(min)}<option value={min}>{pad(min)}</option>{/if}
		{#each MINUTES as m (m)}<option value={m}>{pad(m)}</option>{/each}
	</select>
	<select class={SELECT} aria-label="AM or PM" {disabled} value={has ? (pm ? 'PM' : 'AM') : ''} onchange={(e) => set(h12, min, e.currentTarget.value === 'PM')}>
		{#if !has}<option value="" disabled>--</option>{/if}
		<option value="AM">AM</option>
		<option value="PM">PM</option>
	</select>
</span>
