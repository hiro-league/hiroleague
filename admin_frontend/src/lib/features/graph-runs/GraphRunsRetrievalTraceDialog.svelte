<script lang="ts">
  import { Search, Settings2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { RetrievalTraceRecord } from '$lib/api/graph-runs';
  import ExpandCollapseButtons from './shared/ExpandCollapseButtons.svelte';
  import TraceAnswers from './shared/TraceAnswers.svelte';
  import TraceDialogShell from './shared/TraceDialogShell.svelte';
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

  const EXTRA_TAB = '__extra__';
  const hasExtraTab = $derived(!!extraTab && !!extraTabLabel);

  // Disclosure + sort state are owned here (reset on a new trace; `collapsed` also driven
  // by the header expand/collapse buttons) and passed down to RetrievalLaneStages.
  const collapsed = createToggleSet<number>();
  let strikeDropped = $state(true);
  let search = $state('');
  let settingsOpen = $state(false);
  let sortByStage = $state<Map<number, SortState>>(new Map());

  $effect(() => {
    void trace;
    collapsed.replace(trace ? trace.stages.map((_, i) => i) : []);
    strikeDropped = true;
    search = '';
    settingsOpen = false;
    sortByStage = new Map();
  });

  const laneMatchCounts = $derived.by(() => computeLaneMatchCounts(lanes, search));
  const searching = $derived(search.trim().length > 0);

  const embedStage = $derived(trace ? findEmbedStage(trace.stages) : null);
  const lanes = $derived<Lane[]>(trace ? buildLanes(trace.stages) : []);

  let activeTab = $state<string>('');

  $effect(() => {
    const keys = lanes.map((l) => l.lane);
    if (!keys.includes(activeTab) && !(hasExtraTab && activeTab === EXTRA_TAB)) {
      activeTab = keys[0] ?? '';
    }
  });

  const activeLane = $derived<Lane | null>(
    lanes.find((l) => l.lane === activeTab) ?? lanes[0] ?? null
  );

  const laneTabs = $derived<TraceTab[]>([
    ...lanes.map((l) => ({
      key: l.lane,
      label: l.title,
      count: searching ? `(${laneMatchCounts.get(l.lane) ?? 0})` : null
    })),
    ...(hasExtraTab ? [{ key: EXTRA_TAB, label: extraTabLabel, count: null }] : [])
  ]);

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
      <TraceAnswers question={trace.query} {llmAnswer} {idealAnswer} query={search} />
      {#if settingsOpen}
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

      {#if hasExtraTab && activeTab === EXTRA_TAB}
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
</style>
