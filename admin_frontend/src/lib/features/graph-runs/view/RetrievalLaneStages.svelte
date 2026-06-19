<script lang="ts">
  // Extracted (admin-ui refactor): the per-lane stage list + result table for the
  // retrieval trace dialog. This is the retrieval analog of IngestPhaseStages and was
  // the bulk left inline in GraphRunsRetrievalTraceDialog. Disclosure (`collapsed`) and
  // per-column sort (`sortByStage`) state stay OWNED by the parent dialog — they are
  // reset on a new trace and `collapsed` is also driven by the header's expand/collapse
  // buttons — so they are passed in; this component only renders and mutates the shared
  // toggle set / calls back to toggle sort.
  import type {
    RetrievalTraceItem,
    RetrievalTraceRecord,
    RetrievalTraceStage
  } from '$lib/api/graph-runs';
  import { shortGraphId } from '$lib/format/short-graph-id';
  import ClampCell from '../shared/ClampCell.svelte';
  import FlowNav from '../shared/FlowNav.svelte';
  import HighlightText from '../shared/HighlightText.svelte';
  import StageCard from '../shared/StageCard.svelte';
  import TraceTable from '../shared/TraceTable.svelte';
  import ValidityPill from '../shared/ValidityPill.svelte';
  import type { ToggleSet } from '../shared/use-toggle-set.svelte';
  import {
    episodeSourceLabel,
    formatScore,
    isCurrent,
    shortDate,
    temporalTitle
  } from '../shared/trace-format';
  import {
    ariaSortValue,
    hasItems,
    isExplicitBfsLeg,
    isRankStage,
    provenance,
    resolveEffectiveSort,
    sortArrowGlyph,
    sortItems,
    stageHeadLabel,
    stageMatchCount as computeStageMatchCount,
    stageMetaSummary,
    type Lane,
    type SortState
  } from '../shared/retrieval-trace-derive';

  let {
    trace,
    lane,
    search,
    strikeDropped,
    collapsed,
    sortByStage,
    onToggleSort
  }: {
    trace: RetrievalTraceRecord;
    lane: Lane;
    search: string;
    strikeDropped: boolean;
    collapsed: ToggleSet<number>;
    sortByStage: Map<number, SortState>;
    onToggleSort: (index: number, key: string) => void;
  } = $props();

  const searching = $derived(search.trim().length > 0);

  const stageMatchCount = (stage: RetrievalTraceStage, laneKey: string): number =>
    computeStageMatchCount(stage, laneKey, search);

  const toggleStage = (index: number): void => collapsed.toggle(index);
  const isCollapsed = (index: number): boolean => collapsed.has(index);

  const stageDomId = (idx: number): string => `trace-stage-${idx}`;

  function jumpToStage(idx: number): void {
    if (collapsed.has(idx)) collapsed.remove([idx]);
    requestAnimationFrame(() => {
      document
        .getElementById(stageDomId(idx))
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  const scoreCell = (item: RetrievalTraceItem): string => formatScore(item.score);
  const episodeSource = (item: RetrievalTraceItem): string => episodeSourceLabel(item.source);

  const effectiveSort = (index: number): SortState | null =>
    resolveEffectiveSort(sortByStage.get(index), trace.stages[index]?.kind);
  const sortArrow = (index: number, key: string): string => sortArrowGlyph(effectiveSort(index), key);
  const ariaSort = (index: number, key: string) => ariaSortValue(effectiveSort(index), key);
  const displayItems = (stage: RetrievalTraceStage, index: number): RetrievalTraceItem[] =>
    sortItems(stage.items, sortByStage.get(index));
</script>

{#snippet hl(text: string | null | undefined)}<HighlightText {text} query={search} />{/snippet}

{#snippet sortTh(index: number, key: string, label: string, cls: string, title: string)}
  <th
    class={cls ? `${cls} sortable` : 'sortable'}
    {title}
    aria-sort={ariaSort(index, key)}
    onclick={() => onToggleSort(index, key)}
  >
    {label}<span class="th-arrow">{sortArrow(index, key)}</span>
  </th>
{/snippet}

<section class="lane" data-lane={lane.lane}>
  <p class="lane__hint">{lane.hint}</p>

  <FlowNav flow={lane.flow} title={lane.title} onJump={jumpToStage} />

  {#each lane.stages as { stage, idx } (idx)}
    {@const mc = searching ? stageMatchCount(stage, lane.lane) : 0}
    <StageCard
      collapsed={isCollapsed(idx)}
      onToggle={() => toggleStage(idx)}
      id={stageDomId(idx)}
      dataKind={stage.kind}
      pills={[
        { value: stage.items.length, title: 'Rows returned by this stage' },
        ...(mc > 0
          ? [{ value: mc, title: 'Search matches in this stage', tone: 'hit' as const }]
          : [])
      ]}
    >
      {#snippet label()}{@render hl(stageHeadLabel(stage))}{/snippet}
      {#snippet meta()}{stageMetaSummary(stage)}{/snippet}

      {#if isExplicitBfsLeg(stage)}
        <p class="trace-stage__note">
          Origins for this leg are supplied by the search caller; with none passed (a
          plain query), it stays empty and graph expansion falls back to the hop BFS
          below.
        </p>
      {/if}
      {#if stage.kind === 'temporal'}
        <p class="trace-stage__note">
          Echo of the rerank result — this stage applies no further filtering or
          ranking. Rows are re-sorted by <strong>Valid</strong> (the date the fact
          became true) so the set reads as a timeline; the answer itself uses the
          rerank order above. Click any column header to re-sort.
        </p>
      {/if}
      {#if hasItems(stage)}
        <TraceTable>
          <thead>
            {#if lane.lane === 'edge'}
              <tr>
                <th class="num">#</th>
                {@render sortTh(idx, 'score', 'Score', 'num', '')}
                {@render sortTh(idx, 'v', 'v', 'vstate', 'Validity: current (✓) vs superseded (✗)')}
                {@render sortTh(idx, 'fact', 'Fact', '', '')}
                {@render sortTh(idx, 'rel', 'Relation', '', '')}
                {@render sortTh(idx, 'valid', 'Valid', '', '')}
                {@render sortTh(idx, 'invalid', 'Invalid', '', '')}
                {@render sortTh(idx, 'eps', 'Eps', 'num', 'Supporting episodes (chunk_ids the fact was extracted from)')}
                {#if isRankStage(stage)}<th>From</th>{/if}
                {@render sortTh(idx, 'uuid', 'UUID', '', '')}
              </tr>
            {:else if lane.lane === 'node'}
              <tr>
                <th class="num">#</th>
                {@render sortTh(idx, 'score', 'Score', 'num', '')}
                {@render sortTh(idx, 'entity', 'Entity', '', '')}
                {@render sortTh(idx, 'type', 'Type', '', '')}
                {@render sortTh(idx, 'summary', 'Summary', '', '')}
                {#if isRankStage(stage)}<th>From</th>{/if}
                {@render sortTh(idx, 'uuid', 'UUID', '', '')}
              </tr>
            {:else}
              <tr>
                <th class="num">#</th>
                {@render sortTh(idx, 'score', 'Score', 'num', '')}
                {@render sortTh(idx, 'content', 'Content', '', '')}
                {@render sortTh(idx, 'when', 'When', '', '')}
                {@render sortTh(idx, 'source', 'Source', '', '')}
                {#if isRankStage(stage)}<th>From</th>{/if}
                {@render sortTh(idx, 'uuid', 'UUID', '', '')}
              </tr>
            {/if}
          </thead>
          <tbody>
            {#each displayItems(stage, idx) as item, ii (item.uuid + ':' + ii)}
              <tr class:struck={strikeDropped && !lane.finalUuids.has(item.uuid)}>
                <td class="num">{ii + 1}</td>
                <td class="num">{scoreCell(item)}</td>
                {#if lane.lane === 'edge'}
                  <td class="vstate">
                    <ValidityPill current={isCurrent(item)} title={temporalTitle(item)} />
                  </td>
                  <td class="fact">{@render hl(item.fact)}</td>
                  <td class="rel">{#if item.name}{@render hl(item.name)}{:else}—{/if}</td>
                  <td class="temporal">{shortDate(item.valid_at) || '—'}</td>
                  <td class="temporal">{shortDate(item.invalid_at) || '—'}</td>
                  <td class="num">{item.episodes?.length ?? 0}</td>
                {:else if lane.lane === 'node'}
                  <td class="entity">{#if item.name}{@render hl(item.name)}{:else}—{/if}</td>
                  <td class="rel">{#if item.entity_type}{@render hl(item.entity_type)}{:else}—{/if}</td>
                  <td class="fact">{#if item.summary}<ClampCell text={item.summary} query={search} />{:else}—{/if}</td>
                {:else}
                  <td class="fact">{#if item.content}<ClampCell text={item.content} query={search} />{:else}—{/if}</td>
                  <td class="temporal">{shortDate(item.valid_at) || '—'}</td>
                  <td class="rel">{@render hl(episodeSource(item))}</td>
                {/if}
                {#if isRankStage(stage)}
                  <td class="from">
                    {#each provenance(item, lane) as leg (leg.tag)}
                      <span class="leg-badge leg-badge--{leg.cls}">{leg.tag}</span>
                    {/each}
                  </td>
                {/if}
                <td class="uuid" title={item.uuid}>{@render hl(shortGraphId(item.uuid))}</td>
              </tr>
            {/each}
          </tbody>
        </TraceTable>
      {:else}
        <p class="trace-stage__empty">No items at this stage.</p>
      {/if}
    </StageCard>
  {/each}
</section>

<style>
  .lane {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .lane__hint {
    margin: 0 0 2px;
    font-size: 12px;
    color: var(--muted-foreground);
  }

  .trace-stage__empty {
    margin: 0;
    padding: 8px 10px;
    font-size: 12px;
    color: var(--muted-foreground);
  }

  .trace-stage__note {
    margin: 0;
    padding: 8px 10px;
    font-size: 11px;
    font-style: italic;
    color: var(--muted-foreground);
    border-bottom: 1px solid color-mix(in srgb, var(--muted-foreground) 12%, transparent);
  }

  .th-arrow {
    margin-left: 3px;
    font-size: 9px;
    color: var(--primary);
  }

  .leg-badge {
    display: inline-block;
    padding: 0 5px;
    margin-right: 3px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    line-height: 16px;
    border: 1px solid transparent;
  }

  .leg-badge--kw {
    background: color-mix(in srgb, #3b82f6 18%, transparent);
    border-color: color-mix(in srgb, #3b82f6 45%, transparent);
  }

  .leg-badge--mean {
    background: color-mix(in srgb, #a855f7 18%, transparent);
    border-color: color-mix(in srgb, #a855f7 45%, transparent);
  }

  .leg-badge--hop {
    background: color-mix(in srgb, #f59e0b 20%, transparent);
    border-color: color-mix(in srgb, #f59e0b 50%, transparent);
  }
</style>
