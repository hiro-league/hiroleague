<script lang="ts">
	// The span at a glance: how many errors and warnings, and what went wrong most often (a click shows
	// only that kind of line).
	import * as Card from '$kit/components/ui/card/index.js';
	import { ago } from '$kit/format/time';
	import { areaOf, isError } from './lines';
	import type { LogsPage } from './logs-state.svelte';

	let { pg }: { pg: LogsPage } = $props();
	const spanWords = $derived({ '1h': 'the last hour', '24h': 'the last 24 h', '7d': 'the last 7 days' }[pg.span]);
</script>

<div class="grid grid-cols-2 gap-3 md:grid-cols-[repeat(2,minmax(9rem,12rem))_minmax(0,1fr)]">
	<Card.Root size="sm">
		<Card.Header>
			<Card.Description>Errors</Card.Description>
			<Card.Title class={['text-3xl', pg.errors ? 'text-destructive' : '']}>{pg.errors}</Card.Title>
			<p class="text-xs text-muted-foreground">in {spanWords}</p>
		</Card.Header>
	</Card.Root>
	<Card.Root size="sm">
		<Card.Header>
			<Card.Description>Warnings</Card.Description>
			<Card.Title class={['text-3xl', pg.warnings ? 'text-warning' : '']}>{pg.warnings}</Card.Title>
			<p class="text-xs text-muted-foreground">in {spanWords}</p>
		</Card.Header>
	</Card.Root>
	<Card.Root size="sm" class="col-span-2 md:col-span-1">
		<Card.Header>
			<Card.Description>Most often</Card.Description>
		</Card.Header>
		<Card.Content>
			{#if pg.top.length}
				<ul class="space-y-1.5 text-sm">
					{#each pg.top as g (g.key)}
						<li>
							<button class="flex w-full min-w-0 items-baseline gap-2 text-left hover:underline" onclick={() => pg.focus(g)} title="Show only these lines">
								<span class={['shrink-0 tabular-nums', isError(g.line.level) ? 'text-destructive' : 'text-warning']}>×{g.count}</span>
								<span class="shrink-0 text-xs text-muted-foreground">{areaOf(g.line.logger)}</span>
								<span class="truncate">{g.line.message}</span>
								<span class="ml-auto shrink-0 text-xs text-muted-foreground">last {ago(g.last, pg.now)}</span>
							</button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="text-sm text-muted-foreground">Nothing went wrong in {spanWords}.</p>
			{/if}
		</Card.Content>
	</Card.Root>
</div>
