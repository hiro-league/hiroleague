<script lang="ts">
  // The Stories tab's list (Logging and tracing plan, phase 6b): one row per story, newest first, with its kind, the
  // name its feature declares, its title, the parts it went through, how long it took and its problems. A row opens
  // the story over the page, drawn by its kind. Its toolbar is StoriesToolbar, in the page header.
  //
  // Built from: the UI kit's TableShell and EmptyState; shadcn-svelte's Table.
  import { onMount } from 'svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import Loading from '$kit/ui/loading.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import * as Table from '$kit/components/ui/table/index.js';
  import { clock, dateTime, shortDate } from '$kit/format/time';
  import { cn } from '$lib/utils';
  import KindIcon from './KindIcon.svelte';
  import PartIcon from './PartIcon.svelte';
  import { kindLabel } from './kinds';
  import { partLabel } from './parts';
  import { duration } from './story-format';
  import type { StoriesFilters } from './stories-filters.svelte';

  let { filters, onOpenStory }: { filters: StoriesFilters; onOpenStory: (storyId: string) => void } = $props();
  const rows = $derived(filters.rows);
  onMount(() => void filters.load());
</script>



<div>
  {#if filters.loading && !filters.data}
    <div class="grid min-h-40 place-items-center"><Loading label="Reading the stories…" /></div>
  {:else if filters.error}
    <Notice message={filters.error} class="px-3 py-2 text-sm" />
  {:else if rows.length === 0}
    <EmptyState message="No stories match" hint="Try another kind, source or time window." />
  {:else}
    <TableShell>
      <Table.Header>
        <Table.Row>
          <Table.Head class="w-16 text-center">Date</Table.Head>
          <Table.Head class="w-24 text-center">Time</Table.Head>
          <Table.Head class="w-32">Kind</Table.Head>
          <Table.Head>Name</Table.Head>
          <Table.Head>Title</Table.Head>
          <Table.Head>Parts</Table.Head>
          <Table.Head class="text-right">Took</Table.Head>
          <Table.Head class="text-right">Problems</Table.Head>
        </Table.Row>
      </Table.Header>
      <Table.Body>
        {#each rows as s (s.story_id)}
          <Table.Row class="cursor-pointer text-xs" onclick={() => onOpenStory(s.story_id)} title={dateTime(s.timestamp * 1000, { seconds: true })}>
            <Table.Cell class="text-center text-muted-foreground">{shortDate(s.timestamp * 1000)}</Table.Cell>
            <Table.Cell class="text-center tabular-nums text-muted-foreground">{clock(s.timestamp * 1000, true)}</Table.Cell>
            <Table.Cell><span class="inline-flex items-center gap-1.5"><KindIcon kind={s.kind} class="text-primary" />{kindLabel(s.kind)}</span></Table.Cell>
            <Table.Cell class="whitespace-nowrap" title={s.name}>{partLabel(s.source)} · {s.label}</Table.Cell>
            <Table.Cell class="max-w-[22rem] truncate text-foreground" title={s.title}>{s.title}</Table.Cell>
            <Table.Cell>
              <span class="inline-flex items-center gap-1.5 text-muted-foreground">
                {#each s.sources as p (p)}<span title={partLabel(p)}><PartIcon source={p} size={13} /></span>{/each}
              </span>
            </Table.Cell>
            <Table.Cell class="text-right tabular-nums">{duration(s.took_ms)}</Table.Cell>
            <Table.Cell class={cn('text-right tabular-nums', s.problems ? 'text-warning' : 'text-muted-foreground', s.outcome === 'error' && 'text-destructive')}>{s.problems || '—'}</Table.Cell>
          </Table.Row>
        {/each}
      </Table.Body>
    </TableShell>
  {/if}
</div>
