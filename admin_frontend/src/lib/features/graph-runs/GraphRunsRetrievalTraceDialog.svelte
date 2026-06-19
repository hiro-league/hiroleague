<script lang="ts">
  import { ChevronsDownUp, ChevronsUpDown, Search, Settings2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type {
    RetrievalTraceItem,
    RetrievalTraceRecord,
    RetrievalTraceStage
  } from '$lib/api/graph-runs';
  import { shortGraphId } from '$lib/format/short-graph-id';
  import ClampCell from './shared/ClampCell.svelte';
  import FlowNav from './shared/FlowNav.svelte';
  import HighlightText from './shared/HighlightText.svelte';
  import StageCard from './shared/StageCard.svelte';
  import TraceAnswers from './shared/TraceAnswers.svelte';
  import TraceTable from './shared/TraceTable.svelte';
  import TraceTabs, { type TraceTab } from './shared/TraceTabs.svelte';
  import ValidityPill from './shared/ValidityPill.svelte';
  import { createToggleSet } from './shared/use-toggle-set.svelte';
  import {
    episodeSourceLabel,
    formatScore,
    isCurrent,
    shortDate,
    temporalTitle
  } from './shared/trace-format';
  import {
    ariaSortValue,
    buildLanes,
    findEmbedStage,
    hasItems,
    isExplicitBfsLeg,
    isRankStage,
    laneMatchCounts as computeLaneMatchCounts,
    provenance,
    resolveEffectiveSort,
    sortArrowGlyph,
    sortItems,
    stageHeadLabel,
    stageMatchCount as computeStageMatchCount,
    stageMetaSummary,
    type Lane,
    type SortState
  } from './shared/retrieval-trace-derive';

  let {
    trace,
    onClose,
    // Optional eval context — when this dialog is opened from the knowledge eval (per-leg
    // retrieval trace), the question's ideal answer and the model's answer are surfaced in the
    // header so the recalled facts can be read against the expected/produced answer. Absent on
    // the plain Graph-Runs path (a bare pipeline trace with no eval to compare against).
    idealAnswer = '',
    llmAnswer = '',
    // Optional extra tab (eval: the source corpus, searchable) rendered after the lane tabs.
    // Decoupled via a snippet so this Graph-Runs component stays generic — the caller owns the
    // content. Both props must be set for the tab to appear.
    extraTabLabel = '',
    extraTab
  }: {
    trace: RetrievalTraceRecord | null;
    onClose: () => void;
    idealAnswer?: string;
    llmAnswer?: string;
    extraTabLabel?: string;
    // Receives the dialog's top-search text so the extra (corpus) tab filters off the same input
    // instead of carrying its own search box.
    extraTab?: import('svelte').Snippet<[string]>;
  } = $props();

  // Sentinel lane key for the optional extra (caller-provided) tab.
  const EXTRA_TAB = '__extra__';
  const hasExtraTab = $derived(!!extraTab && !!extraTabLabel);

  // Per-stage collapse state, keyed by the stage's index in `trace.stages` (stable across
  // the lane grouping). Every stage starts COLLAPSED (all tables in all tabs folded by default);
  // re-seeded whenever a different trace opens.
  const collapsed = createToggleSet<number>();

  // When on, rows NOT in their lane's final result set (the last stage) are struck through —
  // so candidate/hop/rank rows that didn't survive to the result are visually demoted. On by
  // default so dropped rows read as dropped without first toggling.
  let strikeDropped = $state(true);

  // Free-text filter highlight: typed text is <mark>-ed wherever it appears in a stage table
  // (and the stage labels), and each tab shows how many distinct items in its lane match.
  let search = $state('');

  // The config/settings line (recipe · temporal · top_k …) is collapsed by default to save
  // header space; the disclosure below it expands the line on demand.
  let settingsOpen = $state(false);

  $effect(() => {
    void trace;
    // Seed every stage index as collapsed → all tables fold by default on open.
    collapsed.replace(trace ? trace.stages.map((_, i) => i) : []);
    strikeDropped = true;
    search = '';
    settingsOpen = false;
    sortByStage = new Map();
  });

  // ── Text-search highlight ───────────────────────────────────────────────────────────────
  // Matching / lane-model / sort logic is pure and lives in `shared/retrieval-trace-derive`;
  // <HighlightText> renders the <mark>ed segments. Thin wrappers below inject `search`.

  // `.by` defers the `lanes` reference into a closure — `lanes` is declared below in the lane model.
  const laneMatchCounts = $derived.by(() => computeLaneMatchCounts(lanes, search));

  const searching = $derived(search.trim().length > 0);

  const stageMatchCount = (stage: RetrievalTraceStage, laneKey: string): number =>
    computeStageMatchCount(stage, laneKey, search);

  const toggleStage = (index: number): void => collapsed.toggle(index);
  const isCollapsed = (index: number): boolean => collapsed.has(index);

  // ── Lane model ────────────────────────────────────────────────────────────────────────
  // The lane grouping (candidates → fuse/rank → temporal → kept, per entity type) is pure and
  // lives in `shared/retrieval-trace-derive`; here we just feed it the trace's stages.
  const embedStage = $derived(trace ? findEmbedStage(trace.stages) : null);
  const lanes = $derived<Lane[]>(trace ? buildLanes(trace.stages) : []);

  // ── Active tab ──────────────────────────────────────────────────────────────────────────
  // One tab per present lane (Facts / Entities / Episodes). Kept valid as lanes change.
  let activeTab = $state<string>('');

  $effect(() => {
    const keys = lanes.map((l) => l.lane);
    // Keep the active tab valid as lanes change — but allow the caller's extra tab to stay
    // selected (it isn't a lane). Only snap back to the first lane on a genuinely stale key.
    if (!keys.includes(activeTab) && !(hasExtraTab && activeTab === EXTRA_TAB)) {
      activeTab = keys[0] ?? '';
    }
  });

  const activeLane = $derived<Lane | null>(
    lanes.find((l) => l.lane === activeTab) ?? lanes[0] ?? null
  );

  // Tab strip model for <TraceTabs>: a tab per lane (count = distinct search matches, shown only
  // while searching), then the optional caller tab.
  const laneTabs = $derived<TraceTab[]>([
    ...lanes.map((l) => ({
      key: l.lane,
      label: l.title,
      count: searching ? `(${laneMatchCounts.get(l.lane) ?? 0})` : null
    })),
    ...(hasExtraTab ? [{ key: EXTRA_TAB, label: extraTabLabel, count: null }] : [])
  ]);

  /** Expand/Collapse apply to the ACTIVE tab's stages only (per-tab, not global). */
  const expandActive = (): void => {
    if (activeLane) collapsed.remove(activeLane.stages.map((s) => s.idx));
  };
  const collapseActive = (): void => {
    if (activeLane) collapsed.add(activeLane.stages.map((s) => s.idx));
  };

  const stageDomId = (idx: number): string => `trace-stage-${idx}`;

  /** Pill click → ensure the stage is expanded, then smooth-scroll it into view. */
  function jumpToStage(idx: number): void {
    if (collapsed.has(idx)) collapsed.remove([idx]);
    requestAnimationFrame(() => {
      document
        .getElementById(stageDomId(idx))
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  // ── Cell formatting ─────────────────────────────────────────────────────────────────────
  // Item-shaped wrappers around the pure formatters so markup call sites stay unchanged;
  // provenance / predicates / temporal helpers (isCurrent, temporalTitle, shortDate,
  // stageMetaSummary, hasItems, isExplicitBfsLeg, isRankStage) are imported directly.
  const scoreCell = (item: RetrievalTraceItem): string => formatScore(item.score);
  const episodeSource = (item: RetrievalTraceItem): string => episodeSourceLabel(item.source);

  // ── Per-column sort ─────────────────────────────────────────────────────────────────────
  // Click a column header to sort that stage's rows: asc → desc → original (tri-state). Keyed
  // by the stage's idx so each table sorts independently. Reset when a new trace opens. The
  // temporal lane arrives pre-sorted by valid_at from the backend; this lets the user override
  // that (or any other table) per column.
  let sortByStage = $state<Map<number, SortState>>(new Map());

  function toggleSort(index: number, key: string): void {
    const next = new Map(sortByStage);
    const cur = next.get(index);
    if (!cur || cur.key !== key) next.set(index, { key, dir: 1 });
    else if (cur.dir === 1) next.set(index, { key, dir: -1 });
    else next.delete(index); // third click restores the stage's original (backend) order
    sortByStage = next;
  }

  // Header-arrow / aria-sort / row-order wrappers inject the component's `sortByStage` overrides
  // and the stage kind (for the temporal lens default) into the pure sort helpers; the comparator
  // and the tri-state resolution live in `shared/retrieval-trace-derive`.
  const effectiveSort = (index: number): SortState | null =>
    resolveEffectiveSort(sortByStage.get(index), trace?.stages[index]?.kind);
  const sortArrow = (index: number, key: string): string => sortArrowGlyph(effectiveSort(index), key);
  const ariaSort = (index: number, key: string) => ariaSortValue(effectiveSort(index), key);
  const displayItems = (stage: RetrievalTraceStage, index: number): RetrievalTraceItem[] =>
    sortItems(stage.items, sortByStage.get(index));
</script>

<!-- Highlight the active search text in a cell — a thin wrapper over <HighlightText> so the many
     `{@render hl(...)}` call sites stay unchanged. -->
{#snippet hl(text: string | null | undefined)}<HighlightText {text} query={search} />{/snippet}

<!-- Sortable column header: click to cycle asc → desc → original order (per stage). Declared at
     the top level so it's a local snippet, not a prop of <Dialog.Content>. -->
{#snippet sortTh(index: number, key: string, label: string, cls: string, title: string)}
  <th
    class={cls ? `${cls} sortable` : 'sortable'}
    {title}
    aria-sort={ariaSort(index, key)}
    onclick={() => toggleSort(index, key)}
  >
    {label}<span class="th-arrow">{sortArrow(index, key)}</span>
  </th>
{/snippet}

<Dialog.Root open={trace !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content
    class="retrieval-trace-content sm:max-w-[min(96vw,1200px)] flex flex-col h-[90vh]"
  >
    <Dialog.Header>
      <!-- Title · search · actions all share one line to keep the header compact. -->
      <div class="trace-head-row">
        <Dialog.Title>Retrieval pipeline trace</Dialog.Title>
        {#if trace}
          <div class="trace-search">
            <Search size={14} aria-hidden="true" class="trace-search__icon" />
            <input
              type="search"
              class="trace-search__input"
              placeholder="Search facts, entities, episodes…"
              bind:value={search}
            />
          </div>
        {/if}
        {#if trace && activeLane}
          <div class="trace-head-actions">
            <Button
              variant="outline"
              size="sm"
              title="Strike through rows not in the final result set (per tab)"
              aria-pressed={strikeDropped}
              onclick={() => (strikeDropped = !strikeDropped)}
            >
              <span class="dropped-label" class:dropped-label--on={strikeDropped}>Dropped</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              title="Expand all sections"
              aria-label="Expand all sections"
              onclick={expandActive}
            >
              <ChevronsUpDown size={14} aria-hidden="true" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              title="Collapse all sections"
              aria-label="Collapse all sections"
              onclick={collapseActive}
            >
              <ChevronsDownUp size={14} aria-hidden="true" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              title={settingsOpen ? 'Hide settings' : 'Show settings'}
              aria-label="Settings"
              aria-pressed={settingsOpen}
              onclick={() => (settingsOpen = !settingsOpen)}
            >
              <Settings2 size={14} aria-hidden="true" />
            </Button>
          </div>
        {/if}
      </div>
      {#if trace}
        <!-- Question → Answer → Ideal (the eval context); only the question is always present. -->
        <TraceAnswers question={trace.query} {llmAnswer} {idealAnswer} query={search} />
        <!-- Config line — toggled by the Settings (gear) button in the header actions; only takes
             a line when expanded, so the collapsed state costs no header height. -->
        {#if settingsOpen}
          <span class="trace-config">
            recipe={trace.recipe} · temporal={trace.temporal} · top_k={trace.num_results} ·
            candidate_limit=2×top_k={2 * trace.num_results} · sim_min_score={trace.sim_min_score} ·
            k_hop={trace.k_hop} · group={trace.group_id}
            {#if embedStage}· embed {embedStage.elapsed_ms.toFixed(1)}ms{/if}
          </span>
        {/if}
      {/if}
    </Dialog.Header>

    {#if trace}
      <!-- One tab per present lane; the workflow pills + stage tables render the active lane. -->
      <TraceTabs
        tabs={laneTabs}
        active={activeTab}
        onSelect={(key) => (activeTab = key)}
        ariaLabel="Retrieval lanes"
        variant="lanes"
        countTone="primary"
      />

      {#if hasExtraTab && activeTab === EXTRA_TAB}
        <!-- Caller-provided tab (eval: the source corpus) — driven by the dialog's top search. -->
        <div class="trace-lanes">
          <div class="p-4">{@render extraTab?.(search)}</div>
        </div>
      {:else if activeLane}
        {@const lane = activeLane}
        <div class="trace-lanes">
          <section class="lane" data-lane={lane.lane}>
            <p class="lane__hint">{lane.hint}</p>

            <!-- Workflow pills: parallel legs → rank → temporal lens. Click to jump to a stage. -->
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
        </div>
      {/if}
    {/if}

    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<style>
  .trace-config {
    display: block;
    margin-top: 6px;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    color: var(--muted-foreground);
  }

  /* Single scroll region for the whole lane list. It flex-grows to fill the fixed-height
     dialog (`h-[90vh]` on Dialog.Content), so the outer height stays constant regardless of
     which tab is active — only this region scrolls. `min-height: 0` lets it shrink below its
     content so the overflow actually scrolls. Children must NOT shrink (flex: none), otherwise
     the bounded-height flex column squishes each stage to ~1 row (the old double-scroll). */
  .trace-lanes {
    display: flex;
    flex-direction: column;
    gap: 20px;
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding-right: 4px;
  }

  .lane {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* Tab bar moved to <TraceTabs>. */

  .lane__hint {
    margin: 0 0 2px;
    font-size: 12px;
    color: var(--muted-foreground);
  }

  /* `.flow*` (lane funnel strip) moved to <FlowNav>. */

  /* `.trace-stage` (card shell + head/pills/meta) moved to <StageCard>. */

  /* Title row carries the expand/collapse-all actions on the right; pad past the absolute
     close (X) button so they never overlap it. */
  .trace-head-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-right: 2.25rem;
  }

  .trace-head-actions {
    display: flex;
    gap: 6px;
    flex: none;
  }

  /* "Dropped" toggle: when on, the label itself reads as struck-through (the action it applies to
     dropped rows) and tints to primary — replacing the old filled-button highlight. */
  .dropped-label--on {
    text-decoration: line-through;
    text-decoration-thickness: 2px;
    color: var(--primary);
  }

  /* Header search box — shares the title line (flex-grows in the middle) to save header space;
     highlights matches in the tables and drives the per-tab / per-stage hit counts. */
  .trace-search {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1 1 auto;
    min-width: 120px;
    max-width: 380px;
    padding: 4px 8px;
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 25%, transparent);
    border-radius: 6px;
    background: color-mix(in srgb, var(--muted-foreground) 6%, transparent);
  }

  .trace-search :global(.trace-search__icon) {
    flex: none;
    color: var(--muted-foreground);
  }

  .trace-search__input {
    flex: 1;
    min-width: 0;
    appearance: none;
    border: none;
    background: transparent;
    outline: none;
    font-size: 12px;
    color: var(--foreground);
  }

  /* `.search-hit` moved to <HighlightText>. */

  /* `.trace-answers*` (Question/Answer/Ideal header) moved to <TraceAnswers>. */

  /* `.trace-stage__head`/titlebtn/caret/label/pill/meta moved to <StageCard>. */

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

  /* `.trace-table*` shell + cell styling moved to <TraceTable>. The sort-arrow span stays here
     (rendered by this dialog's sortTh snippet). */
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
