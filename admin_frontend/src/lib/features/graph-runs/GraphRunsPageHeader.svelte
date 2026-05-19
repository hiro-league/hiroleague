<script lang="ts">
  import { ChevronDown, ChevronUp, RefreshCw, X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { cn } from '$lib/utils';
  import {
    graphRunTabId,
    GRAPH_RUNS_PANEL_IDS,
    GRAPH_RUNS_PRIMARY_TAB_IDS,
    GRAPH_RUNS_PRIMARY_TABLIST_LABEL,
    GRAPH_RUNS_SUBTAB_IDS,
    GRAPH_RUNS_SUBTAB_TABLIST_LABEL,
    isRunDetailPane,
    MEMORIES_TAB,
    RUNS_TAB,
    type ActivePane
  } from './graph-runs-pure';
  import {
    GRAPH_RUNS_HEADER_INTRO,
    GRAPH_RUNS_HEADER_KICKER,
    GRAPH_RUNS_HEADER_TITLE,
    GRAPH_RUNS_TABLIST_SHELL,
    cnGraphRunsMainPaneTab
  } from './shared/graph-runs-ui';

  let {
    activePane,
    openRunIds,
    runDetailCardsExpanded,
    runTabDisplayLabel,
    runTabTooltip,
    onActivatePrimaryRunsWorkspace,
    onShowRunsOnly,
    onShowMemories,
    onOpenRunTab,
    onCloseRunTab,
    onToggleRunDetailCards,
    onRefresh
  }: {
    activePane: ActivePane;
    openRunIds: string[];
    runDetailCardsExpanded: boolean;
    runTabDisplayLabel: (runId: string) => string;
    runTabTooltip: (runId: string) => string;
    onActivatePrimaryRunsWorkspace: () => void;
    onShowRunsOnly: () => void;
    onShowMemories: () => void;
    onOpenRunTab: (runId: string) => void;
    onCloseRunTab: (runId: string) => void;
    onToggleRunDetailCards: () => void;
    onRefresh: () => void;
  } = $props();

  /** Underline-tab treatment for ledger / open inspectors (distinct from rounded primary pills above). */
  function cnBrowseSubtab(selected: boolean) {
    return cn(
      '-mb-px min-w-0 max-w-[min(22rem,calc(100vw-10rem))] shrink-0 items-center truncate border-b-2 border-transparent bg-transparent px-3 py-2 text-left font-sans text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
      selected ? 'border-primary font-semibold text-foreground' : undefined
    );
  }

  const primaryRunsSelected = $derived(activePane !== MEMORIES_TAB);
</script>

<div class="flex flex-col gap-4">
  <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <p class={GRAPH_RUNS_HEADER_KICKER}>Operations</p>
      <h2 class={GRAPH_RUNS_HEADER_TITLE}>
        {activePane === MEMORIES_TAB ? 'Memories' : 'Graph runs'}
      </h2>
      <p class={GRAPH_RUNS_HEADER_INTRO}>
        {#if activePane === MEMORIES_TAB}
          Mem0 long-term store for the selected workspace (read-only).
        {:else}
          Recent agent turns with aggregate cost, latency, and drill-down timelines.
        {/if}
      </p>
    </div>
    <div class="flex flex-wrap items-center justify-end gap-2">
      <div
        class={GRAPH_RUNS_TABLIST_SHELL}
        role="tablist"
        aria-label={GRAPH_RUNS_PRIMARY_TABLIST_LABEL}
      >
        <Button
          id={GRAPH_RUNS_PRIMARY_TAB_IDS.runsWorkspace}
          class={cnGraphRunsMainPaneTab(primaryRunsSelected)}
          variant={primaryRunsSelected ? 'secondary' : 'ghost'}
          role="tab"
          type="button"
          aria-controls="{GRAPH_RUNS_PANEL_IDS.runs} {GRAPH_RUNS_PANEL_IDS.detail}"
          aria-selected={primaryRunsSelected}
          onclick={onActivatePrimaryRunsWorkspace}
        >
          Graph runs
        </Button>
        <Button
          id={GRAPH_RUNS_PRIMARY_TAB_IDS.memories}
          class={cnGraphRunsMainPaneTab(activePane === MEMORIES_TAB)}
          variant={activePane === MEMORIES_TAB ? 'secondary' : 'ghost'}
          role="tab"
          type="button"
          aria-controls={GRAPH_RUNS_PANEL_IDS.memories}
          aria-selected={activePane === MEMORIES_TAB}
          onclick={onShowMemories}
        >
          Memories
        </Button>
      </div>
    </div>  </div>

  {#if activePane !== MEMORIES_TAB}
    <div
      class="-mb-px flex min-h-[2.5rem] min-w-0 items-end gap-3 border-b border-border"
    >
      <div
        class="flex min-w-0 min-h-9 flex-1 flex-wrap items-end gap-x-1 gap-y-0"
        role="tablist"
        aria-label={GRAPH_RUNS_SUBTAB_TABLIST_LABEL}
      >
        <button
          type="button"
          id={GRAPH_RUNS_SUBTAB_IDS.browse}
          class={cnBrowseSubtab(activePane === RUNS_TAB)}
          role="tab"
          aria-controls={GRAPH_RUNS_PANEL_IDS.runs}
          aria-selected={activePane === RUNS_TAB}
          tabindex={0}
          onclick={onShowRunsOnly}
        >
          Graph runs
        </button>
        {#each openRunIds as rid (rid)}
          <span class="flex min-w-0 max-w-[min(26rem,calc(100vw-8rem))] shrink-0 items-end gap-0" role="presentation">
            <button
              type="button"
              id={graphRunTabId(rid)}
              title={runTabTooltip(rid)}
              class={cnBrowseSubtab(activePane === rid)}
              role="tab"
              aria-controls={GRAPH_RUNS_PANEL_IDS.detail}
              aria-selected={activePane === rid}
              tabindex={0}
              onclick={() => onOpenRunTab(rid)}
            >
              {runTabDisplayLabel(rid)}
            </button>
            <button
              type="button"
              class="-mb-px flex size-9 shrink-0 items-center justify-center rounded-t-md text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
              aria-label="Close run inspector"
              title="Close (Esc)"
              onclick={(e) => {
                e.stopPropagation();
                onCloseRunTab(rid);
              }}
            >
              <X size={16} aria-hidden="true" />
            </button>
          </span>
        {/each}
      </div>
      <div class="flex shrink-0 items-end gap-1 pb-px">
        <Button
          variant="ghost"
          size="icon"
          class="text-muted-foreground hover:text-foreground"
          id="graph-runs-toolbar-refresh"
          type="button"
          aria-label="Refresh ledger list"
          title="Refresh ledger list"
          onclick={onRefresh}
        >
          <RefreshCw size={17} strokeWidth={2} aria-hidden="true" />
        </Button>
        {#if isRunDetailPane(activePane)}
          <Button
            variant="ghost"
            size="icon"
            class="graph-runs-cards-toggle text-muted-foreground hover:text-foreground"
            id="run-detail-cards-toggle"
            type="button"
            aria-expanded={runDetailCardsExpanded}
            aria-controls="run-detail-cards-flow"
            aria-label={runDetailCardsExpanded
              ? 'Collapse detailed metrics and ledger fields'
              : 'Expand detailed metrics and ledger fields'}
            title={runDetailCardsExpanded
              ? 'Collapse detailed metrics and ledger fields'
              : 'Expand detailed metrics and ledger fields'}
            onclick={onToggleRunDetailCards}
          >
            {#if runDetailCardsExpanded}
              <ChevronUp size={18} strokeWidth={2} aria-hidden="true" />
            {:else}
              <ChevronDown size={18} strokeWidth={2} aria-hidden="true" />
            {/if}
          </Button>
        {/if}
      </div>    </div>
  {/if}
</div>
