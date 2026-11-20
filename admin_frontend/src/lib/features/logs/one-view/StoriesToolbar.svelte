<script lang="ts">
  // The Stories tab's toolbar (the logging plan's phase 6b), on one line in the page header's row under the title: search, the
  // Logs tab's time window, Kind, Source, With problems.
  // Built from: the UI kit's SearchInput (compact), PickSelect and MultiSelectFilter; shadcn-svelte's Button.
  import { TriangleAlert } from '@lucide/svelte';
  import SearchInput from '$kit/ui/search-input.svelte';
  import MultiSelectFilter, { type MultiSelectOption } from '$kit/ui/multi-select-filter.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { cn } from '$lib/utils';
  import { LOG_TIME_RANGES, type LogTimeRange } from '$lib/api/logs';
  import { STORY_KINDS } from './kinds';
  import { partLabel } from './parts';
  import type { StoriesFilters } from './stories-filters.svelte';

  let { filters: f }: { filters: StoriesFilters } = $props();

  // The Logs tab's own time window choices, so both read the same
  const RANGE_LABELS: Record<LogTimeRange, string> = { '1h': '1 hr', '2h': '2 hrs', '4h': '4 hrs', '1d': '1 day', '2d': '2 days', '3d': '3 days', all: 'All' };
  const windowOptions = [{ value: 'last', label: 'Last session' }, ...LOG_TIME_RANGES.map((r) => ({ value: r, label: RANGE_LABELS[r] }))];
  const kindOptions: MultiSelectOption[] = STORY_KINDS.map((k) => ({ value: k.kind, label: k.label }));
  const sourceOptions = $derived<MultiSelectOption[]>(f.parts.map((s) => ({ value: s, label: partLabel(s) })));
</script>
<div class="flex min-w-0 flex-wrap items-center gap-2">
    <SearchInput variant="compact" class="w-64" value={f.search} count={f.rows.length} onValueChange={(v: string) => (f.search = v)} placeholder="Search stories..." />
    <PickSelect class="h-8 w-auto min-w-[7rem] text-sm" value={f.window} options={windowOptions} onchange={(v: string) => {
      f.window = v as typeof f.window;
      void f.load();
    }} label="Story time window" />
    <MultiSelectFilter label="Kind" options={kindOptions} selected={f.kinds} searchPlaceholder="Search kinds…" onSelectedChange={(v: string[]) => (f.kinds = v)} />
    <MultiSelectFilter label="Source" options={sourceOptions} selected={f.sources} searchPlaceholder="Search sources…" onSelectedChange={(v: string[]) => (f.sources = v)} />
    <Button
      variant="outline"
      size="sm"
      class={cn('h-8 gap-1', f.withProblems && 'border-primary bg-primary/10')}
      aria-pressed={f.withProblems}
      onclick={() => (f.withProblems = !f.withProblems)}
    ><TriangleAlert size={14} />With problems</Button>
  </div>
