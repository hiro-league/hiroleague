<script lang="ts">
	// What the list shows: problems or everything, how far back, which source and area, and a search.
	import { Button } from '$kit/components/ui/button/index.js';
	import { Switch } from '$kit/components/ui/switch/index.js';
	import PickSelect from '$kit/ui/pick-select.svelte';
	import SearchInput from '$kit/ui/search-input.svelte';
	import Segmented from '$kit/ui/segmented.svelte';
	import type { Span, View } from './api';
	import type { LogsPage } from './logs-state.svelte';
	import { SOURCES } from './lines';

	let { pg }: { pg: LogsPage } = $props();

	const views: { value: View; label: string; title: string }[] = [
		{ value: 'problems', label: 'Problems', title: 'Warnings and errors (the *-errors.log files)' },
		{ value: 'all', label: 'Everything', title: 'Every line, INFO and up' }
	];
	const areaOptions = $derived([{ value: 'all', label: 'All areas' }, ...pg.areas.map((a) => ({ value: a, label: a }))]);
	const spans: { value: Span; label: string }[] = [
		{ value: '1h', label: '1 h' },
		{ value: '24h', label: '24 h' },
		{ value: '7d', label: '7 days' }
	];
</script>

<div class="flex flex-wrap items-center gap-2">
	<Segmented options={views} value={pg.view} onchange={(v) => (pg.view = v)} size="sm" label="What to show" />
	<Segmented options={spans} value={pg.span} onchange={(v) => (pg.span = v)} size="sm" label="How far back" />
	<PickSelect value={pg.source} options={SOURCES} onchange={(v) => (pg.source = v as typeof pg.source)} label="Source" class="h-9 w-44 text-sm" />
	<PickSelect value={pg.area} options={areaOptions} onchange={(v) => (pg.area = v)} label="Area" class="h-9 w-44 text-sm" />
	<SearchInput bind:value={pg.search} placeholder="Search the lines and tracebacks…" class="min-w-56 flex-1" />
	{#if pg.search || pg.area !== 'all' || pg.source !== 'all'}
		<Button variant="link" size="sm" onclick={() => pg.clear()}>Clear filters</Button>
	{/if}
	<label class="flex items-center gap-2 text-sm text-muted-foreground" title="Lines that say the same thing (apart from numbers) are shown once, with how often">
		<Switch checked={pg.grouped} onCheckedChange={(v) => (pg.grouped = v)} /> Group repeats
	</label>
</div>
