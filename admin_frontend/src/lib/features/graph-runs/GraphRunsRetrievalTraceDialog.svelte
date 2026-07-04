<script lang="ts">
  import { Settings2 } from '@lucide/svelte';
  import SearchInput from '$lib/search/SearchInput.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Highlight from '$lib/search/Highlight.svelte';
  import type { RetrievalTraceRecord } from '$lib/api/graph-runs';
  import ExpandCollapseButtons from './shared/ExpandCollapseButtons.svelte';
  import TraceDialogShell from './shared/TraceDialogShell.svelte';
  import TraceOverviewAnswers from './shared/TraceOverviewAnswers.svelte';
  import TraceTabs, { type TraceTab } from './shared/TraceTabs.svelte';
  import RetrievalLaneStages from './view/RetrievalLaneStages.svelte';
  import { createToggleSet } from './shared/use-toggle-set.svelte';
  import {
    buildLanes,
    findEmbedStage,
    laneMatchCounts as computeLaneMatchCounts,
    type Lane,
    type SortState
  } from './shared/retrieval-trace-derive';

  let {
    trace,
    onClose,
    idealAnswer = '',
    llmAnswer = '',
    extraTabLabel = '',
    extraTab
  }: {
    trace: RetrievalTraceRecord | null;
    onClose: () => void;
    idealAnswer?: string;
    llmAnswer?: string;
    extraTabLabel?: string;
    extraTab?: import('svelte').Snippet<[string]>;
  } = $props();

  const OVERVIEW_TAB = '__overview__';
  const EXTRA_TAB = '__extra__';
  const hasExtraTab = $derived(!!extraTab && !!extraTabLabel);

  // Disclosure + sort state are owned here (reset on a new trace; `collapsed` also driven
  // by the header expand/collapse buttons) and passed down to RetrievalLaneStages.
  const collapsed = createToggleSet<number>();
  let strikeDropped = $state(true);
  let search = $state('');
  let settingsOpen = $state(false);
  let sortByStage = $state<Map<number, SortState>>(new Map());
  let activeTab = $state<string>(OVERVIEW_TAB);

  $effect(() => {
    void trace;
    collapsed.replace(trace ? trace.stages.map((_, i) => i) : []);
    strikeDropped = true;
    search = '';
    settingsOpen = false;
    sortByStage = new Map();
    activeTab = OVERVIEW_TAB;
  });

  const laneMatchCounts = $derived.by(() => computeLaneMatchCounts(lanes, search));
  const searching = $derived(search.trim().length > 0);

  const embedStage = $derived(trace ? findEmbedStage(trace.stages) : null);
  const lanes = $derived<Lane[]>(trace ? buildLanes(trace.stages) : []);

  $effect(() => {
    const keys = [OVERVIEW_TAB, ...lanes.map((l) => l.lane)];
    if (hasExtraTab) keys.push(EXTRA_TAB);
    if (!keys.includes(activeTab)) activeTab = OVERVIEW_TAB;
  });

  const activeLane = $derived<Lane | null>(
    lanes.find((l) => l.lane === activeTab) ?? lanes[0] ?? null
  );

  const laneTabs = $derived<TraceTab[]>([
    { key: OVERVIEW_TAB, label: 'Overview', count: null },
    ...lanes.map((l) => ({
      key: l.lane,
      label: l.title,
      count: searching ? `(${laneMatchCounts.get(l.lane) ?? 0})` : null
    })),
    ...(hasExtraTab ? [{ key: EXTRA_TAB, label: extraTabLabel, count: null }] : [])
  ]);

  const onLaneTab = $derived(activeTab !== OVERVIEW_TAB && activeTab !== EXTRA_TAB);

  const expandActive = (): void => {
    if (activeLane) collapsed.remove(activeLane.stages.map((s) => s.idx));
  };
  const collapseActive = (): void => {
    if (activeLane) collapsed.add(activeLane.stages.map((s) => s.idx));
  };

  function toggleSort(index: number, key: string): void {
    const next = new Map(sortByStage);
    const cur = next.get(index);
    if (!cur || cur.key !== key) next.set(index, { key, dir: 1 });
    else if (cur.dir === 1) next.set(index, { key, dir: -1 });
    else next.delete(index);
    sortByStage = next;
  }
</script>

<TraceDialogShell
  open={trace !== null}
  {onClose}
  title="Retrieval pipeline trace"
  contentClass="retrieval-trace-content"
>
  {#snippet headActions()}
    {#if trace}
      <!-- Question sits inline with the search box + action buttons (all on one header row). -->
      <div class="trace-question" title={trace.query}>
        <span class="trace-question__label">Q</span>
        <span class="trace-question__text"><Highlight text={trace.query} query={search} /></span>
      </div>
      <div class="trace-search">
        <SearchInput
          variant="inline"
          class="trace-search__shell min-w-0 flex-1 border-0 bg-transparent p-0 shadow-none"
          inputClass="trace-search__input"
          bind:value={search}
          placeholder="Search facts, entities, episodes…"
        />
      </div>
    {/if}
    {#if trace && activeLane && onLaneTab}
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
        <ExpandCollapseButtons onExpand={expandActive} onCollapse={collapseActive} />
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
  {/snippet}

  {#snippet headerDetail()}
    {#if trace}
      {#if settingsOpen && onLaneTab}
        <span class="trace-config">
          recipe={trace.recipe} · temporal={trace.temporal} · top_k={trace.num_results} ·
          candidate_limit=2×top_k={2 * trace.num_results} · sim_min_score={trace.sim_min_score} ·
          k_hop={trace.k_hop} · group={trace.group_id}
          {#if embedStage}· embed {embedStage.elapsed_ms.toFixed(1)}ms{/if}
        </span>
      {/if}
    {/if}
  {/snippet}

  {#snippet children()}
    {#if trace}
      <TraceTabs
        tabs={laneTabs}
        active={activeTab}
        onSelect={(key) => (activeTab = key)}
        ariaLabel="Retrieval lanes"
        variant="lanes"
        countTone="primary"
      />

      {#if activeTab === OVERVIEW_TAB}
        <div class="trace-lanes">
          <div class="p-4">
            <TraceOverviewAnswers {idealAnswer} {llmAnswer} />
          </div>
        </div>
      {:else if hasExtraTab && activeTab === EXTRA_TAB}
        <div class="trace-lanes">
          <div class="p-4">{@render extraTab?.(search)}</div>
        </div>
      {:else if activeLane}
        <div class="trace-lanes">
          <RetrievalLaneStages
            {trace}
            lane={activeLane}
            {search}
            {strikeDropped}
            {collapsed}
            {sortByStage}
            onToggleSort={toggleSort}
          />
        </div>
      {/if}
    {/if}
  {/snippet}
</TraceDialogShell>

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

  .trace-lanes {
    display: flex;
    flex-direction: column;
    gap: 20px;
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding-right: 4px;
  }

  .trace-head-actions {
    display: flex;
    gap: 6px;
    flex: none;
  }

  .dropped-label--on {
    text-decoration: line-through;
    text-decoration-thickness: 2px;
    color: var(--primary);
  }

  /* Question line, inline in the header row: takes the free space, truncates with an ellipsis so
     the search box + action buttons stay put on the same line. */
  .trace-question {
    display: flex;
    align-items: baseline;
    gap: 6px;
    flex: 1 1 auto;
    min-width: 0;
    font-size: 12px;
  }

  .trace-question__label {
    flex: none;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground);
  }

  .trace-question__text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--foreground);
  }

  .trace-search {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 0 1 300px;
    min-width: 120px;
    padding: 4px 8px;
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 25%, transparent);
    border-radius: 6px;
    background: color-mix(in srgb, var(--muted-foreground) 6%, transparent);
  }

  .trace-search :global(.trace-search__shell) {
    flex: 1;
    min-width: 0;
  }

  .trace-search :global(input) {
    flex: 1;
    min-width: 0;
    appearance: none;
    border: none;
    background: transparent;
    outline: none;
    font-size: 12px;
    color: var(--foreground);
  }
</style>
