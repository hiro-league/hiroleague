<script lang="ts">
	// The lines, newest first. A line opens to its traceback (or the rest of its message), where it came
	// from, and, for repeats, each time it happened.
	import { Badge } from '$kit/components/ui/badge/index.js';
	import { Button } from '$kit/components/ui/button/index.js';
	import EmptyState from '$kit/ui/empty-state.svelte';
	import { agoShort, dateTime, fullDateTime } from '$kit/format/time';
	import { ChevronRight, Copy } from '@lucide/svelte';
	import type { Level } from './api';
	import { areaOf, isError, SOURCES, type Group } from './lines';
	import type { LogsPage } from './logs-state.svelte';

	let { pg }: { pg: LogsPage } = $props();

	const levelClass = (l: Level) =>
		isError(l) ? 'bg-destructive/15 text-destructive' : l === 'WARNING' ? 'bg-warning/15 text-warning' : 'bg-muted text-muted-foreground';
	const time = (iso: string) => dateTime(iso, { seconds: true, now: pg.now });
	const copyText = (g: Group) =>
		`${g.line.at} ${g.line.level} ${g.line.logger}: ${g.line.message}${g.line.detail ? '\n' + g.line.detail : ''}`;
</script>

{#if !pg.shown.length}
	<EmptyState message="No lines match.">
		{#snippet actions()}
			{#if pg.search || pg.area !== 'all' || pg.source !== 'all'}<Button variant="link" size="inline" onclick={() => pg.clear()}>Clear the filters</Button>{/if}
		{/snippet}
	</EmptyState>
{:else}
	<ul class="divide-y rounded-md border">
		{#each pg.shown as g (g.key)}
			{@const l = g.line}
			{@const opened = pg.open.has(g.key)}
			<li>
				<button class="flex w-full min-w-0 flex-wrap items-start gap-x-3 gap-y-0.5 px-3 py-2 text-left text-sm hover:bg-muted/50 md:flex-nowrap" onclick={() => pg.toggle(g.key)} aria-expanded={opened}>
					<ChevronRight class={['mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform', opened ? 'rotate-90' : '']} />
					<span class="w-44 shrink-0 text-xs leading-5 whitespace-nowrap text-muted-foreground tabular-nums" title={fullDateTime(l.at)}>{time(l.at)}</span>
					<span class={['w-16 shrink-0 rounded px-1.5 text-center text-xs leading-5 font-medium', levelClass(l.level)]}>{l.level === 'CRITICAL' ? 'CRASH' : l.level}</span>
					<span class="hidden w-28 shrink-0 truncate text-xs leading-5 text-muted-foreground md:inline">{areaOf(l.logger)}</span>
					<span class={['min-w-0 flex-1 basis-full pl-7 leading-5 md:basis-0 md:pl-0', opened ? 'break-words' : 'truncate']}>{l.message}</span>
					{#if g.count > 1}
						<Badge variant="outline" class="shrink-0" title="The same line (apart from numbers) {g.count} times, first {agoShort(g.first, pg.now)} ago">×{g.count}</Badge>
					{/if}
					{#if l.detail && !opened}<span class="shrink-0 text-xs text-muted-foreground">traceback</span>{/if}
				</button>
				{#if opened}
					<div class="space-y-2 bg-muted/30 px-3 pt-1 pb-3 pl-10 text-xs">
						<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-muted-foreground">
							<span>Logger <span class="font-mono text-foreground">{l.logger}</span></span>
							<span>From {SOURCES.find((s) => s.value === l.source)?.label}</span>
							{#if g.count > 1}<span>{g.count} times, from {time(g.first)} to {time(g.last)}</span>{/if}
							<Button size="xs" variant="outline" class="ml-auto" onclick={() => navigator.clipboard?.writeText(copyText(g))}><Copy /> Copy</Button>
						</div>
						{#if l.detail}
							<pre class="max-h-72 overflow-auto rounded border bg-background p-2 font-mono text-[11px] leading-4 whitespace-pre">{l.detail}</pre>
						{/if}
						{#if g.count > 1}
							<details>
								<summary class="cursor-pointer text-muted-foreground">Each time</summary>
								<ul class="mt-1 space-y-0.5 font-mono">
									{#each g.lines as each (each.id)}<li><span class="text-muted-foreground">{time(each.at)}</span> {each.message}</li>{/each}
								</ul>
							</details>
						{/if}
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
