<script lang="ts">
  import { ChevronLeft, ChevronRight, Settings2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { IngestTraceRecord } from '$lib/api/graph-runs';
  import { shortGraphId } from '$lib/format/short-graph-id';
  import ExpandCollapseButtons from './shared/ExpandCollapseButtons.svelte';
  import TraceDialogShell from './shared/TraceDialogShell.svelte';
  import TraceTabs, { type TraceTab } from './shared/TraceTabs.svelte';
  import { createToggleSet } from './shared/use-toggle-set.svelte';
  import { fmtDate } from './shared/trace-format';
  import {
    buildEntityTypeMap,
    buildPhases,
    groupStages,
    type Phase
  } from './shared/ingest-trace-derive';
  import IngestPhaseStages from './view/IngestPhaseStages.svelte';
  import IngestResultTab from './view/IngestResultTab.svelte';

  let {
    trace,
    onClose,
    // Prev/next episode navigation (header arrows + ←/→ keys). Optional so the generic
    // graph-runs caller can omit them; disabled at the ends via hasPrev/hasNext.
    hasPrev = false,
    hasNext = false,
    onPrev,
    onNext,
    // Position of the current trace within the run's episode list (1-based) — shown between the
    // arrows. The per-trace episode_index/total is 1/1 for the eval's single-episode ingests, so
    // the caller supplies the real run position here; falls back to episode_index/total when unset.
    navIndex = 0,
    navTotal = 0,
    // Optional extra tab (eval: the searchable source corpus) — decoupled via a snippet so this
    // Graph-Runs component stays generic. Both props must be set for the tab to appear.
    extraTabLabel = '',
    extraTab
  }: {
    trace: IngestTraceRecord | null;
    onClose: () => void;
    hasPrev?: boolean;
    hasNext?: boolean;
    onPrev?: () => void;
    onNext?: () => void;
    navIndex?: number;
    navTotal?: number;
    extraTabLabel?: string;
    extraTab?: import('svelte').Snippet;
  } = $props();

  const hasExtraTab = $derived(!!extraTab && !!extraTabLabel);

  // ── Tabs ────────────────────────────────────────────────────────────────────────────────
  // One flat tab row: a tab per pipeline phase (Entities / Attributes / Facts / Other) — the
  // per-stage journey — then Result (what landed in the graph: persisted nodes + edges), then
  // the caller's optional Corpus tab. Sentinels keep the last two distinct from phase keys.
  const RESULT_TAB = '__result__';
  const EXTRA_TAB = '__extra__';
  let activeTab = $state<string>('');

  // Per-stage collapse, keyed by the stage's index in `trace.stages`. Separate disclosures for
  // the (large, repetitive) prompt and the raw-JSON fallback — both collapsed by default since
  // the structured table is the primary view. All reset on a new trace.
  const collapsed = createToggleSet<number>();
  const promptOpen = createToggleSet<number>();
  const jsonOpen = createToggleSet<number>();

  // The config/stats line (episode · chunk · tokens …) is collapsed by default behind the
  // header gear so the header stays compact — mirrors the recall (retrieval) trace dialog.
  let settingsOpen = $state(false);

  // Reset transient view state on a new trace, but PRESERVE the active tab so arrow-nav between
  // episodes keeps you on the same tab (the tabKeys effect below re-validates / initialises it).
  $effect(() => {
    void trace;
    collapsed.clear();
    promptOpen.clear();
    jsonOpen.clear();
    settingsOpen = false;
  });

  // ←/→ navigate to the prev/next episode trace (mirrors the header arrows). Guarded so it never
  // fires while typing in an input/textarea, when a modifier is held, or when the dialog is closed.
  function onArrowNavKey(ev: KeyboardEvent): void {
    if (trace === null) return;
    if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    const t = ev.target as HTMLElement | null;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (ev.key === 'ArrowLeft' && hasPrev) {
      ev.preventDefault();
      onPrev?.();
    } else if (ev.key === 'ArrowRight' && hasNext) {
      ev.preventDefault();
      onNext?.();
    }
  }

  const toggleStage = (index: number): void => collapsed.toggle(index);
  const togglePrompt = (index: number): void => promptOpen.toggle(index);
  const toggleJson = (index: number): void => jsonOpen.toggle(index);

  const isCollapsed = (index: number): boolean => collapsed.has(index);
  const isPromptOpen = (index: number): boolean => promptOpen.has(index);
  const isJsonOpen = (index: number): boolean => jsonOpen.has(index);

  // ── Stage grouping + pipeline phases (sub-tabs) ───────────────────────────────────────────
  const groups = $derived(trace ? groupStages(trace.stages) : []);
  const phases = $derived<Phase[]>(buildPhases(groups));

  const tabKeys = $derived<string[]>([
    ...phases.map((p) => p.phase),
    RESULT_TAB,
    ...(hasExtraTab ? [EXTRA_TAB] : [])
  ]);

  $effect(() => {
    if (!tabKeys.includes(activeTab)) activeTab = tabKeys[0] ?? RESULT_TAB;
  });

  const activePhaseObj = $derived<Phase | null>(
    phases.find((p) => p.phase === activeTab) ?? null
  );

  const entityTypeById = $derived(buildEntityTypeMap(trace?.entity_types ?? []));
  const nodes = $derived(trace?.persisted_nodes ?? []);
  const edges = $derived(trace?.persisted_edges ?? []);

  const ingestTabs = $derived.by<TraceTab[]>(() => [
    ...phases.map((p) => ({ key: p.phase, label: p.title, count: String(p.idxs.length) })),
    { key: RESULT_TAB, label: 'Result', count: String(nodes.length + edges.length) },
    ...(hasExtraTab ? [{ key: EXTRA_TAB, label: extraTabLabel, count: null }] : [])
  ]);

  const expandActive = (): void => {
    if (activePhaseObj) collapsed.remove(activePhaseObj.idxs);
  };
  const collapseActive = (): void => {
    if (activePhaseObj) collapsed.add(activePhaseObj.idxs);
  };

  const totals = $derived.by(() => {
    let inTok = 0;
    let outTok = 0;
    let ms = 0;
    for (const s of trace?.stages ?? []) {
      inTok += s.input_tokens ?? 0;
      outTok += s.output_tokens ?? 0;
      ms += s.elapsed_ms ?? 0;
    }
    return { inTok, outTok, ms, calls: trace?.stages.length ?? 0 };
  });
</script>

<svelte:window onkeydown={onArrowNavKey} />

<TraceDialogShell
  open={trace !== null}
  {onClose}
  title="Ingest pipeline trace"
  contentClass="ingest-trace-content"
>
  {#snippet headActions()}
    {#if trace}
      <div class="trace-head-actions">
        <Button
          variant="outline"
          size="sm"
          title="Previous episode (Left arrow)"
          aria-label="Previous episode"
          disabled={!hasPrev}
          onclick={() => onPrev?.()}
        >
          <ChevronLeft size={14} aria-hidden="true" />
        </Button>
        <span class="trace-nav-pos" title="Episode position in this run">
          {navTotal > 0 ? `${navIndex}/${navTotal}` : `${trace.episode_index}/${trace.total}`}
        </span>
        <Button
          variant="outline"
          size="sm"
          title="Next episode (Right arrow)"
          aria-label="Next episode"
          disabled={!hasNext}
          onclick={() => onNext?.()}
        >
          <ChevronRight size={14} aria-hidden="true" />
        </Button>
        {#if activePhaseObj}
          <ExpandCollapseButtons onExpand={expandActive} onCollapse={collapseActive} />
        {/if}
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
      <Dialog.Description>
        <span class="trace-query">{trace.name || trace.chunk_id}</span>
        {#if trace.text}
          <span class="trace-ingested">
            <span class="trace-ingested__label">Ingested text:</span>
            {trace.text}
          </span>
        {/if}
        {#if settingsOpen}
          <span class="trace-config">
            episode {trace.episode_index}/{trace.total} · chunk {shortGraphId(trace.chunk_id)} ·
            group={trace.group_id}
            {#if trace.reference_time}· <span title={trace.reference_time}>t={fmtDate(trace.reference_time, false)}</span>{/if}
            · stages={totals.calls} · {totals.inTok}i/{totals.outTok}o · {totals.ms.toFixed(0)}ms
            · persisted {nodes.length} entities / {edges.length} facts
            {#if trace.invalidated_count}· invalidated={trace.invalidated_count}{/if}
          </span>
        {/if}
      </Dialog.Description>
    {/if}
  {/snippet}

  {#snippet children()}
    {#if trace}
      <div class="trace-body">
        <TraceTabs
          tabs={ingestTabs}
          active={activeTab}
          onSelect={(key) => (activeTab = key)}
          ariaLabel="Ingest trace views"
          variant="subtabs"
          countTone="muted"
        />

        {#if activePhaseObj}
          <IngestPhaseStages
            phase={activePhaseObj}
            {entityTypeById}
            {isCollapsed}
            {isPromptOpen}
            {isJsonOpen}
            onToggleStage={toggleStage}
            onTogglePrompt={togglePrompt}
            onToggleJson={toggleJson}
          />
        {:else if activeTab === RESULT_TAB}
          <IngestResultTab {nodes} {edges} />
        {:else if activeTab === EXTRA_TAB && extraTab}
          <section class="result-section">
            {@render extraTab()}
          </section>
        {/if}
      </div>
    {/if}
  {/snippet}
</TraceDialogShell>

<style>
  .trace-query {
    display: block;
    font-weight: 600;
    color: var(--foreground);
    margin-bottom: 2px;
  }

  .trace-config {
    display: block;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    color: var(--muted-foreground);
  }

  .trace-head-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: none;
  }

  .trace-nav-pos {
    font-size: 11px;
    font-weight: 600;
    color: var(--muted-foreground);
    font-variant-numeric: tabular-nums;
    min-width: 2.75rem;
    text-align: center;
    white-space: nowrap;
  }

  .trace-body {
    display: flex;
    flex-direction: column;
    gap: 16px;
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding-right: 4px;
  }

  .trace-ingested {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
    margin-top: 2px;
    font-size: 12px;
    color: var(--foreground);
    white-space: pre-wrap;
    word-break: break-word;
  }

  .trace-ingested__label {
    font-weight: 600;
    color: var(--muted-foreground);
  }

  .result-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
</style>
