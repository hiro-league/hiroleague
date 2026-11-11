<script lang="ts">
	// One measure over time as a filled line, with limits as dashed lines and, optionally, a dashed
	// projection past now. A missing value (null: no report then, the machine was off) breaks the line.
	// Hover shows the value and the time under the pointer.
	import { dateTime } from '$kit/format/time';

	interface Props {
		values: (number | null)[];
		stepMs: number; // time between points; the last point is `end`
		end?: number;
		max: number | null; // top of the scale; null = the data's top plus some room
		unit: string;
		format?: (v: number) => string; // a value in words, unit included ("0.35 Mbit/s"); then `unit` is left empty
		height?: number;
		limits?: { value: number; tone: 'warning' | 'destructive'; label: string }[];
		projection?: number[]; // points after the last value, same step
		label: string; // for screen readers
	}
	let { values, stepMs, end = Date.now(), max, unit, format, height = 56, limits = [], projection = [], label }: Props = $props();

	const W = 300;
	const all = $derived<(number | null)[]>([...values, ...projection]);
	const known = $derived(all.filter((v): v is number => v !== null));
	const top = $derived(max ?? (Math.max(...known, ...limits.map((l) => l.value), 0) * 1.15 || 1));
	const bottom = $derived(max === null && known.length && Math.min(...known) > top * 0.5 ? Math.min(...known) * 0.95 : 0); // zoom in on slow-moving totals
	const x = (i: number) => (i / Math.max(1, all.length - 1)) * W;
	const y = (v: number) => height - 2 - ((v - bottom) / (top - bottom || 1)) * (height - 4);
	// The line in pieces, one per run of known values
	const runs = $derived.by(() => {
		const out: { i: number; v: number }[][] = [];
		let run: { i: number; v: number }[] = [];
		values.forEach((v, i) => {
			if (v === null) {
				if (run.length) out.push(run);
				run = [];
			} else run.push({ i, v });
		});
		if (run.length) out.push(run);
		return out;
	});
	const line = (r: { i: number; v: number }[]) => r.map((p) => `${x(p.i)},${y(p.v)}`).join(' ');
	const area = (r: { i: number; v: number }[]) => `${x(r[0].i)},${height} ${line(r)} ${x(r[r.length - 1].i)},${height}`;
	const last = $derived(values.at(-1));
	const proj = $derived(
		projection.length && last != null ? [`${x(values.length - 1)},${y(last)}`, ...projection.map((v, i) => `${x(values.length + i)},${y(v)}`)].join(' ') : ''
	);

	let hover = $state<number | null>(null);
	function move(e: PointerEvent) {
		const box = (e.currentTarget as SVGElement).getBoundingClientRect();
		hover = Math.round(((e.clientX - box.left) / box.width) * (all.length - 1));
	}
	const timeAt = (i: number) => end + (i - (values.length - 1)) * stepMs;
	const fmt = (v: number) => (format ? format(v) : Math.abs(v) >= 100 ? Math.round(v).toString() : v.toFixed(1));
</script>

<div class="relative">
	<svg viewBox="0 0 {W} {height}" preserveAspectRatio="none" class="block w-full" style="height: {height}px" role="img" aria-label={label} onpointermove={move} onpointerleave={() => (hover = null)}>
		{#each runs as r, k (k)}
			<polygon points={area(r)} class="fill-primary/10" />
			{#if r.length > 1}
				<polyline points={line(r)} fill="none" class="stroke-primary/70" stroke-width="2" vector-effect="non-scaling-stroke" />
			{:else}
				<line x1={x(r[0].i)} x2={x(r[0].i)} y1={y(r[0].v)} y2={height} class="stroke-primary/70" stroke-width="2" vector-effect="non-scaling-stroke" />
			{/if}
		{/each}
		{#if proj}<polyline points={proj} fill="none" class="stroke-muted-foreground" stroke-width="2" stroke-dasharray="4 4" vector-effect="non-scaling-stroke" />{/if}
		{#each limits as l (l.label)}
			{#if l.value <= top && l.value >= bottom}
				<line x1="0" x2={W} y1={y(l.value)} y2={y(l.value)} class={l.tone === 'warning' ? 'stroke-warning' : 'stroke-destructive'} stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke" />
			{/if}
		{/each}
		{#if hover !== null}
			<line x1={x(hover)} x2={x(hover)} y1="0" y2={height} class="stroke-foreground/40" stroke-width="1" vector-effect="non-scaling-stroke" />
		{/if}
	</svg>
	{#if hover !== null}
		{@const v = all[hover]}
		<div
			class="pointer-events-none absolute -top-7 z-10 rounded border bg-popover px-1.5 py-0.5 text-[11px] whitespace-nowrap shadow-sm"
			style="left: clamp(0px, calc({(x(hover) / W) * 100}% - 3rem), calc(100% - 7rem))"
		>
			{#if v === null || v === undefined}<span class="text-muted-foreground">no report</span>{:else}<span class="font-medium tabular-nums">{fmt(v)} {unit}</span
				>{/if}{hover >= values.length ? ' (projected)' : ''} · <span class="text-muted-foreground">{dateTime(timeAt(hover))}</span>
		</div>
	{/if}
</div>
