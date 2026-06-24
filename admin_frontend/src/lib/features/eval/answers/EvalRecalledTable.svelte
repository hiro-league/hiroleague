<!--
  One recalled-kind table (facts / entities / episodes) for the eval detail dialog. Renders the
  items the way the answerer saw them: ordered by score (default), each item's text trimmed to the
  eval cap (toggleable), and the items that were CAPPED OUT (beyond the top-K per kind by score)
  struck through — they were recalled but never sent to eval. Sticky header + click-to-sort columns.
  Cap/trim mechanics live in eval-recall-render.ts (kept in lockstep with services/eval/judge.py).
-->
<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import Highlight from '$lib/search/Highlight.svelte';
  import { fmtEpisodeDate } from '$lib/features/eval/shared/eval-format';
  import type { EvalRecallRender, RecalledFact } from '$lib/features/eval/shared/eval-events';
  import {
    ariaSort,
    entityName,
    itemText,
    nextSort,
    recalledMatches,
    scoreOf,
    sentSet,
    sortArrow,
    sortRows,
    textCapFor,
    type SortState
  } from '$lib/features/eval/shared/eval-recall-render';

  interface Props {
    /** All rows of this kind for the leg (unfiltered — the sent/capped split is computed here). */
    rows: RecalledFact[];
    kind: 'fact' | 'entity' | 'episode';
    /** Render caps the run used (drives the cap-strike + trim). */
    render: EvalRecallRender;
    /** Trim each item's text to the eval cap (one sanitized line) vs. show the full text. */
    trimmed: boolean;
    /** Highlight + filter term ('' = show all, no highlight). */
    search: string;
    /** Facts only: dim rows whose search_id ≠ the trajectory-selected one (null = no dimming). */
    dimSearchId?: number | null;
  }
  let { rows, kind, render, trimmed, search, dimSearchId = null }: Props = $props();

  type Col = { key: string; label: string; align: 'left' | 'right'; title?: string };
  const COLUMNS: Record<Props['kind'], Col[]> = {
    fact: [
      { key: 'fact', label: 'Fact', align: 'left' },
      { key: 'rel', label: 'Relationship', align: 'left' },
      { key: 'valid', label: 'Valid from', align: 'left' },
      { key: 'invalid', label: 'Invalid at', align: 'left' },
      { key: 'status', label: 'Status', align: 'left' },
      { key: 'score', label: 'Score', align: 'right' }
    ],
    entity: [
      { key: 'entity', label: 'Entity', align: 'left' },
      { key: 'type', label: 'Type', align: 'left' },
      { key: 'score', label: 'Score', align: 'right' }
    ],
    episode: [
      { key: 'episode', label: 'Episode', align: 'left' },
      { key: 'when', label: 'When', align: 'left' },
      { key: 'score', label: 'Score', align: 'right' }
    ]
  };
  const columns = $derived(COLUMNS[kind]);

  function accessor(row: RecalledFact, key: string): string | number {
    switch (key) {
      case 'score':
        return scoreOf(row);
      case 'fact':
        return row.fact || row.memory || '';
      case 'rel':
        return row.name || '';
      case 'valid':
        return row.valid_at || '';
      case 'invalid':
        return row.invalid_at || '';
      case 'status':
        return row.superseded ? 1 : 0;
      case 'entity':
        return row.name || '';
      case 'type':
        return row.entity_type || '';
      case 'episode':
        return row.memory || '';
      case 'when':
        return row.valid_at || '';
      default:
        return '';
    }
  }

  // Default order: score desc — the same ranking the answerer's top-K cap uses.
  const DEFAULT_SORT: SortState = { key: 'score', dir: -1 };
  let sort = $state<SortState>({ ...DEFAULT_SORT });
  // Reset the sort when the kind changes (the table is reused across tabs).
  $effect(() => {
    void kind;
    sort = { ...DEFAULT_SORT };
  });

  // The sent/capped split is from the FULL set (independent of the display filter/sort) so striking
  // reflects what eval actually received, not what the search happens to show.
  const sent = $derived(sentSet(rows, render.max_elements_per_kind));
  const cap = $derived(textCapFor(kind, render));
  const visible = $derived(
    sortRows(
      rows.filter((r) => recalledMatches(r, search)),
      sort,
      accessor
    )
  );

  function toggle(key: string): void {
    sort = nextSort(sort, key, DEFAULT_SORT);
  }
  const dimmed = (row: RecalledFact): boolean =>
    dimSearchId != null && row.search_id != null && row.search_id !== dimSearchId;
</script>

<div class="max-h-[60vh] overflow-auto rounded-md border">
  <table class="w-full border-collapse font-sans text-xs">
    <thead>
      <tr>
        {#each columns as col (col.key)}
          <th
            class="sticky top-0 z-10 cursor-pointer select-none bg-muted px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground {col.align ===
            'right'
              ? 'text-right'
              : 'text-left'}"
            aria-sort={ariaSort(sort, col.key)}
            title={col.title ?? 'Click to sort'}
            onclick={() => toggle(col.key)}
          >
            {col.label}<span class="ml-1 text-[9px] text-primary">{sortArrow(sort, col.key)}</span>
          </th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each visible as row, i (i)}
        {@const struck = !sent.has(row)}
        <tr
          class="border-t align-top {dimmed(row) ? 'opacity-35' : ''} {struck
            ? '[&>td]:text-muted-foreground [&>td]:line-through'
            : ''}"
          title={struck ? 'Capped out — recalled but not sent to the eval answer' : undefined}
        >
          {#if kind === 'fact'}
            <td class="max-w-[24rem] px-2 py-1">
              <span class={trimmed ? '' : 'whitespace-pre-wrap'} title={row.fact || row.memory}>
                <Highlight text={itemText(row.fact || row.memory, cap, trimmed)} query={search} />
              </span>
            </td>
            <td class="px-2 py-1 font-mono text-[11px] text-muted-foreground">
              {#if row.name}<Highlight text={row.name} query={search} />{:else}—{/if}
            </td>
            <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{row.valid_at || '—'}</td>
            <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{row.invalid_at || '—'}</td>
            <td class="px-2 py-1">
              {#if row.superseded}<Badge variant="warning">superseded</Badge>{:else}<Badge
                  variant="success">active</Badge
                >{/if}
            </td>
          {:else if kind === 'entity'}
            <td class="max-w-[28rem] px-2 py-1">
              {#if row.name}<span class="font-semibold"
                  ><Highlight text={entityName(row.name, trimmed)} query={search} /></span
                >{/if}
              <span
                class="block text-muted-foreground {trimmed ? '' : 'whitespace-pre-wrap'}"
                title={row.summary || row.memory}
              >
                <Highlight text={itemText(row.summary || row.memory, cap, trimmed)} query={search} />
              </span>
            </td>
            <td class="px-2 py-1">
              {#if row.entity_type}<Badge variant="outline" class="font-sans normal-case"
                  >{row.entity_type}</Badge
                >{:else}<span class="text-muted-foreground">—</span>{/if}
            </td>
          {:else}
            <td class="max-w-[32rem] px-2 py-1">
              <span class={trimmed ? '' : 'whitespace-pre-wrap'} title={row.memory}>
                <Highlight text={itemText(row.memory, cap, trimmed)} query={search} />
              </span>
            </td>
            <td class="px-2 py-1 font-mono text-[11px] tabular-nums"
              >{row.valid_at ? fmtEpisodeDate(row.valid_at) : '—'}</td
            >
          {/if}
          <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
            {row.score != null ? row.score.toFixed(3) : '—'}
          </td>
        </tr>
      {/each}
      {#if visible.length === 0}
        <tr>
          <td class="px-2 py-3 text-center text-muted-foreground" colspan={columns.length}>
            No items match “{search}”.
          </td>
        </tr>
      {/if}
    </tbody>
  </table>
</div>
