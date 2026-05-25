<script lang="ts">
  /**
   * Graph Runs second-level strip: ledger list + dynamic run inspectors + toolbar.
   * Primary pill tabs live in `<AdminPageHeader tabs>`.
   */
  import { ChevronDown, ChevronUp, RefreshCw, X } from '@lucide/svelte';
  import AdminSubtabButton from '$lib/components/page/AdminSubtabButton.svelte';
  import AdminSubtabStrip from '$lib/components/page/AdminSubtabStrip.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import {
    graphRunTabId,
    GRAPH_RUNS_PANEL_IDS,
    GRAPH_RUNS_SUBTAB_IDS,
    GRAPH_RUNS_SUBTAB_TABLIST_LABEL,
    isRunDetailPane,
    RUNS_TAB,
    type ActivePane
  } from './graph-runs-pure';

  let {
    activePane,
    openRunIds,
    runDetailCardsExpanded,
    runTabDisplayLabel,
    runTabTooltip,
    onShowRunsOnly,
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
    onShowRunsOnly: () => void;
    onOpenRunTab: (runId: string) => void;
    onCloseRunTab: (runId: string) => void;
    onToggleRunDetailCards: () => void;
    onRefresh: () => void;
  } = $props();

  const browseTab = [
    {
      id: RUNS_TAB,
      label: 'Graph runs',
      htmlId: GRAPH_RUNS_SUBTAB_IDS.browse,
      ariaControls: GRAPH_RUNS_PANEL_IDS.runs
    }
  ] as const;
</script>

<AdminSubtabStrip
  ariaLabel={GRAPH_RUNS_SUBTAB_TABLIST_LABEL}
  tabs={browseTab}
  active={activePane}
  onSelect={(id) => {
    if (id === RUNS_TAB) onShowRunsOnly();
  }}
>
  {#snippet extraTabs()}
    {#each openRunIds as rid (rid)}
      <span
        class="flex min-w-0 max-w-[min(26rem,calc(100vw-8rem))] shrink-0 items-end gap-0"
        role="presentation"
      >
        <AdminSubtabButton
          label={runTabDisplayLabel(rid)}
          title={runTabTooltip(rid)}
          class="max-w-[min(22rem,calc(100vw-10rem))]"
          active={activePane === rid}
          htmlId={graphRunTabId(rid)}
          ariaControls={GRAPH_RUNS_PANEL_IDS.detail}
          onclick={() => onOpenRunTab(rid)}
        />
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
  {/snippet}

  {#snippet toolbar()}
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
  {/snippet}
</AdminSubtabStrip>
