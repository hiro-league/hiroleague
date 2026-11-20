<script lang="ts">
  // The Logs tab's "Group repeats" view (Logging and tracing plan, phase 6b): the warnings and errors of every part
  // (the core, each app, the apps' pages, the phone) grouped by part, level and area, so a problem that repeats a
  // thousand times is one row with its count. It reads the core's log tools (`/logs/problems`) for the Logs toolbar's
  // time window, and follows its Source, Level and search. A group opens to its newest lines; a line that belongs to a
  // story carries the story icon, as on the Logs table, and opens it over the page.
  //
  // Built from: the UI kit's TableShell with shadcn-svelte's Table, Loading, Notice and EmptyState; shadcn-svelte's
  // Badge; the Logs tab's level icon and colours. New: the group row that opens to its lines.
  import { ChevronDown, ChevronRight, Globe } from '@lucide/svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import * as Table from '$kit/components/ui/table/index.js';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { errorMessage } from '$kit/api/client';
  import { clock, dateTime } from '$kit/format/time';
  import { cn } from '$lib/utils';
  import { getLogProblems, type LogProblems, type LogSourceFilter, type ProblemGroup } from '$lib/api/logs';
  import LogLevelIcon from '../shared/LogLevelIcon.svelte';
  import { logLevelAccentClass, logLevelTextClass } from '../shared/logs-classes';
  import { logRowSourceFilter } from '../shared/logs-ui';
  import PartIcon from './PartIcon.svelte';
  import KindIcon from './KindIcon.svelte';
  import { isCore, isPageArea, partLabel } from './parts';

  type Props = {
    span: string; // the Logs toolbar's time window ("60m", "1d")
    activeSources: LogSourceFilter[];
    levels: string[]; // the Logs toolbar's levels shown (none: all)
    search: string;
    onOpenStory: (storyId: string) => void;
  };
  let { span, activeSources, levels, search, onOpenStory }: Props = $props();

  let data = $state<LogProblems | null>(null);
  let loading = $state(true);
  let failure = $state<string | null>(null);
  let open = $state<Record<string, boolean>>({});

  $effect(() => {
    const asked = span;
    loading = true;
    failure = null;
    getLogProblems(asked)
      .then((d) => {
        if (asked === span) data = d;
      })
      .catch((e) => (failure = errorMessage(e)))
      .finally(() => (loading = false));
  });

  const key = (g: ProblemGroup) => `${g.source}|${g.level}|${g.area}`;
  const shown = $derived(
    (data?.groups ?? []).filter((g) => {
      const src = logRowSourceFilter(g.source);
      if (src && !activeSources.includes(src)) return false;
      if (levels.length > 0 && !levels.includes(g.level)) return false;
      const q = search.trim().toLowerCase();
      return !q || g.messages.some((m) => m.toLowerCase().includes(q)) || g.area.toLowerCase().includes(q);
    })
  );
  const total = $derived(shown.reduce((n, g) => n + g.count, 0));
  const parts = $derived(new Set(shown.map((g) => g.source)).size);
  const linesOf = (g: ProblemGroup) =>
    (data?.rows ?? [])
      .filter((r) => r.source === g.source && r.level === g.level && r.area === g.area)
      .sort((a, b) => b.timestamp - a.timestamp);
</script>

<div class="space-y-2">
  {#if loading && !data}
    <div class="grid min-h-40 place-items-center"><Loading label="Grouping the problems…" /></div>
  {:else if failure}
    <Notice message={failure} class="px-3 py-2 text-sm" />
  {:else if shown.length === 0}
    <EmptyState message="No warnings or errors" hint={`Nothing in this span from the sources and levels picked (${data?.span ?? ''}).`} />
  {:else}
    <p class="font-sans text-xs text-muted-foreground">
      {total} warnings and errors from {parts} parts, {data?.span}: errors first, then the most frequent.
    </p>
    <TableShell>
      <Table.Header>
        <Table.Row>
          <Table.Head class="w-8"></Table.Head>
          <Table.Head class="w-8"><span class="sr-only">Level</span></Table.Head>
          <Table.Head>Source</Table.Head>
          <Table.Head>Module</Table.Head>
          <Table.Head>Latest message</Table.Head>
          <Table.Head class="text-right">Count</Table.Head>
          <Table.Head>Last</Table.Head>
        </Table.Row>
      </Table.Header>
      <Table.Body>
        {#each shown as g (key(g))}
          {@const isOpen = !!open[key(g)]}
          <Table.Row class="cursor-pointer align-top" aria-expanded={isOpen} onclick={() => (open = { ...open, [key(g)]: !isOpen })}>
            <Table.Cell class="text-muted-foreground">{#if isOpen}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}</Table.Cell>
            <Table.Cell title={g.level}><LogLevelIcon level={g.level} size={15} class={logLevelAccentClass(g.level)} /></Table.Cell>
            <Table.Cell class="whitespace-nowrap text-xs">
              <span class="inline-flex items-center gap-1.5">
                <PartIcon source={g.source} class="text-muted-foreground" />
                {partLabel(g.source)}
                {#if !isCore(g.source)}<Badge variant="outline" class="h-4 px-1 text-[10px] font-normal text-muted-foreground">{g.source === 'device' ? 'device' : 'app'}</Badge>{/if}
              </span>
            </Table.Cell>
            <Table.Cell class="whitespace-nowrap font-mono text-xs">
              <span class="inline-flex items-center gap-1">{#if isPageArea(g.area)}<Globe size={12} class="text-muted-foreground" aria-label="A page's problem" />{/if}{g.area}</span>
            </Table.Cell>
            <Table.Cell class="min-w-0 max-w-[30rem] text-xs">
              <p class={cn('truncate', logLevelTextClass(g.level))} title={g.messages[0]}>{g.messages[0]}</p>
              {#if g.kinds > 1}<p class="text-muted-foreground">{g.kinds} kinds of message</p>{/if}
            </Table.Cell>
            <Table.Cell class="text-right tabular-nums">{g.count}</Table.Cell>
            <Table.Cell class="whitespace-nowrap text-xs text-muted-foreground">{g.last}</Table.Cell>
          </Table.Row>
          {#if isOpen}
            {@const ls = linesOf(g)}
            <Table.Row class="bg-muted/30 hover:bg-muted/30">
              <Table.Cell></Table.Cell>
              <Table.Cell colspan={6} class="py-2">
                <ul class="space-y-1.5">
                  {#each ls as l, i (i)}
                    <li class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
                      <span class="inline-flex w-5 justify-center">
                        {#if l.story_id}
                          <button type="button" class="inline-grid place-items-center rounded-md p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground" title="Open its story" onclick={() => onOpenStory(l.story_id!)}>
                            <KindIcon kind="unknown" size={14} />
                          </button>
                        {/if}
                      </span>
                      <span class="w-24 shrink-0 tabular-nums text-muted-foreground" title={dateTime(l.timestamp * 1000, { seconds: true })}>{clock(l.timestamp * 1000, true)}</span>
                      <span class="min-w-0 flex-1">{l.message}</span>
                      {#if l.fields}
                        <span class="max-w-[40rem] truncate font-mono text-[11px] text-muted-foreground">{Object.entries(l.fields).map(([k, v]) => `${k}=${v}`).join(' · ')}</span>
                      {/if}
                    </li>
                  {/each}
                  {#if g.count > ls.length}
                    <li class="text-xs text-muted-foreground">and {g.count - ls.length} more, from {g.first}</li>
                  {/if}
                </ul>
              </Table.Cell>
            </Table.Row>
          {/if}
        {/each}
      </Table.Body>
    </TableShell>
  {/if}
</div>
