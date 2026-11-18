<script lang="ts">
	// One measure over time as a filled line, with limits as dashed lines and, optionally, a dashed
	// projection past now. A missing value (null: no report then, the machine was off) breaks the line.
	// Hover shows the value and the time under the pointer.
	// UI kit, step 7e: drawn by shadcn-svelte's Chart (LayerChart: its area, line, rules, highlight and tooltip), not
	// by hand-written SVG; the limits, the projection, the gaps and the house's words in the tooltip are the kit's.
	import { Area, Chart, Highlight, Rule, Spline, Svg, Tooltip } from 'layerchart';
	import * as ChartUI from '$kit/components/ui/chart/index.js';
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

	type Point = { t: number; v: number | null; projected: boolean };
	const timeAt = (i: number) => end + (i - (values.length - 1)) * stepMs;
	const measured = $derived<Point[]>(values.map((v, i) => ({ t: timeAt(i), v, projected: false })));
	// the projection starts at the last value, so its dashed line joins the filled one
	const projected = $derived<Point[]>(
		projection.length && values.at(-1) != null
			? [{ t: timeAt(values.length - 1), v: values.at(-1)!, projected: false }, ...projection.map((v, i) => ({ t: timeAt(values.length + i), v, projected: true }))]
			: []
	);
	const all = $derived([...measured, ...projected.slice(1)]);

	// the scale, as before 7e: the given top, or the data's top (limits included) plus some room; slow-moving totals
	// zoom in on their range rather than starting at 0
	const known = $derived(all.map((p) => p.v).filter((v): v is number => v !== null));
	const top = $derived(max ?? (Math.max(...known, ...limits.map((l) => l.value), 0) * 1.15 || 1));
	const bottom = $derived(max === null && known.length && Math.min(...known) > top * 0.5 ? Math.min(...known) * 0.95 : 0);

	const fmt = (v: number) => (format ? format(v) : Math.abs(v) >= 100 ? Math.round(v).toString() : v.toFixed(1));
	const config = { v: { label, color: 'var(--primary)' } } satisfies ChartUI.ChartConfig;
</script>

<ChartUI.Container {config} class="aspect-auto w-full" style="height: {height}px" role="img" aria-label={label}>
	<Chart data={all} x="t" y="v" xDomain={[all[0]?.t ?? end, all.at(-1)?.t ?? end]} yDomain={[bottom, top]} padding={{ top: 2, bottom: 2 }} tooltipContext={{ mode: 'bisect-x' }}>
		<Svg>
			<Area data={measured} y1="v" defined={(d: Point) => d.v !== null} class="fill-primary/10" line={{ class: 'stroke-primary/70 stroke-2' }} />
			{#if projected.length}
				<Spline data={projected} y="v" class="stroke-muted-foreground stroke-2 [stroke-dasharray:4_4]" />
			{/if}
			{#each limits as l (l.label)}
				{#if l.value <= top && l.value >= bottom}
					<!-- the chart container greys every line and hides rule lines (stroke 0): the limit's ! puts it back -->
					<Rule y={l.value} class="{l.tone === 'warning' ? 'stroke-warning!' : 'stroke-destructive!'} stroke-1! [stroke-dasharray:3_3]" />
				{/if}
			{/each}
			<!-- the container hides the highlight line too (stroke 0); the kit keeps its thin line under the pointer -->
			<Highlight axis="x" lines={{ class: 'stroke-foreground/40! stroke-1!' }} />
		</Svg>
		<Tooltip.Root x="data" y={-28} anchor="bottom" class="pointer-events-none z-10 rounded border bg-popover px-1.5 py-0.5 text-[11px] whitespace-nowrap text-popover-foreground shadow-sm">
			{#snippet children({ data }: { data: Point })}
				{#if data.v === null}<span class="text-muted-foreground">no report</span>{:else}<span class="font-medium tabular-nums">{fmt(data.v)} {unit}</span>{/if}{data.projected
					? ' (projected)'
					: ''} · <span class="text-muted-foreground">{dateTime(data.t)}</span>
			{/snippet}
		</Tooltip.Root>
	</Chart>
</ChartUI.Container>
