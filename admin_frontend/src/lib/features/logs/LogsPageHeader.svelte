<script lang="ts">
  import {
    ArrowDownUp,
    ChevronDown,
    ChevronUp,
    PanelRightClose,
    PanelRightOpen,
    Pause,
    Play,
    Search,
    X
  } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { LOG_TIME_RANGES, type LogSortOrder, type LogTimeRange } from '$lib/api/logs';
  import { isLogTimeRange } from './shared/logs-ui';
  import { LOGS_DETAIL_PANEL_ID } from './shared/logs-a11y';

  type Props = {
    searchText: string;
    onSearchInput: (event: Event) => void;
    onClearSearch: () => void;
    sortOrder: LogSortOrder;
    onToggleSort: () => void;
    paused: boolean;
    onTogglePause: () => void;
    blocksLiveTail: boolean;
    onClearAllFilters: () => void;
    autoScroll: boolean;
    onToggleAutoScroll: () => void;
    lastSessionOnly: boolean;
    onToggleLastSessionOnly: () => void;
    logTimeRange: LogTimeRange;
    onLogTimeRangeChange: (value: LogTimeRange) => void;
    detailPanelOpen: boolean;
    onToggleDetailPanel: () => void;
    controlsCollapsed: boolean;
    onToggleControlsCollapsed: () => void;
    /** Targets the filters ``role="region"`` (``aria-controls``). */
    filtersRegionId: string;
    visibleCount: number;
    loadedCount: number;
    searchBusy: boolean;
    /** True when server search or local scope filters narrow the result set. */
    filtered: boolean;
  };

  let {
    searchText,
    onSearchInput,
    onClearSearch,
    sortOrder,
    onToggleSort,
    paused,
    onTogglePause,
    blocksLiveTail,
    onClearAllFilters,
    autoScroll,
    onToggleAutoScroll,
    lastSessionOnly,
    onToggleLastSessionOnly,
    logTimeRange,
    onLogTimeRangeChange,
    detailPanelOpen,
    onToggleDetailPanel,
    controlsCollapsed,
    onToggleControlsCollapsed,
    filtersRegionId,
    visibleCount,
    loadedCount,
    searchBusy,
    filtered
  }: Props = $props();

  const timeRangeLabels: Record<LogTimeRange, string> = {
    '1h': '1 hr',
    '2h': '2 hrs',
    '4h': '4 hrs',
    '1d': '1 day',
    '2d': '2 days',
    '3d': '3 days',
    all: 'All'
  };
</script>

<div class="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
  <div class="flex min-w-0 flex-wrap items-end gap-x-4 gap-y-1">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Operations</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Logs</h2>
    </div>
    <p class="pb-1 font-sans text-xs text-muted-foreground">
      {visibleCount} visible / {loadedCount} loaded
      {#if searchBusy}
        <span class="ml-2 text-primary">Searching...</span>
      {:else if filtered}
        <span class="ml-2 text-primary">Filtered</span>
      {/if}
    </p>
  </div>
  <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2 xl:justify-end">
    <label
      class="flex h-9 min-w-72 items-center gap-2 rounded-md border border-input bg-background px-3 font-sans text-sm shadow-xs focus-within:ring-2 focus-within:ring-ring"
    >
      <Search size={15} class="text-muted-foreground" />
      <input
        class="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
        placeholder="Search logs..."
        value={searchText}
        oninput={onSearchInput}
      />
      {#if searchText}
        <button
          class="grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
          type="button"
          aria-label="Clear search"
          onclick={onClearSearch}
        >
          <X size={14} />
        </button>
      {/if}
    </label>
    <Button variant="outline" size="sm" onclick={onToggleSort}>
      <ArrowDownUp size={15} />
      {sortOrder === 'newest' ? 'Newest first' : 'Oldest first'}
    </Button>
    <Button variant="outline" size="sm" onclick={onTogglePause}>
      {#if paused}
        <Play size={15} />
        Resume
      {:else}
        <Pause size={15} />
        Pause
      {/if}
    </Button>
    {#if blocksLiveTail}
      <Button variant="outline" size="sm" onclick={onClearAllFilters}>
        Clear filters
      </Button>
    {/if}
    <Button
      variant={autoScroll ? 'secondary' : 'outline'}
      size="sm"
      onclick={onToggleAutoScroll}
    >
      {#if sortOrder === 'newest'}
        <ChevronUp size={15} />
      {:else}
        <ChevronDown size={15} />
      {/if}
      Auto-scroll {autoScroll ? 'on' : 'off'}
    </Button>
    <Button
      variant={lastSessionOnly ? 'secondary' : 'outline'}
      size="sm"
      onclick={onToggleLastSessionOnly}
    >
      Last session {lastSessionOnly ? 'on' : 'off'}
    </Button>
    <label class="flex items-center gap-1.5 font-sans text-sm text-muted-foreground">
      <span class="sr-only">Time range</span>
      <select
        class="h-9 min-w-[5.5rem] rounded-md border border-input bg-background px-2 text-sm text-foreground shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        disabled={lastSessionOnly}
        value={logTimeRange}
        onchange={(event) => {
          const v = (event.currentTarget as HTMLSelectElement).value;
          if (isLogTimeRange(v)) onLogTimeRangeChange(v);
        }}
        aria-label="Log time range"
        title={lastSessionOnly ? 'Disabled while Last session is on' : 'Show logs from this window'}
      >
        {#each LOG_TIME_RANGES as r (r)}
          <option value={r}>{timeRangeLabels[r]}</option>
        {/each}
      </select>
    </label>
    <span class="hidden h-6 w-px bg-border md:block"></span>
    <Button
      class="xl:ml-2"
      variant={detailPanelOpen ? 'secondary' : 'outline'}
      size="sm"
      onclick={onToggleDetailPanel}
      aria-expanded={detailPanelOpen}
      aria-controls={detailPanelOpen ? LOGS_DETAIL_PANEL_ID : undefined}
    >
      {#if detailPanelOpen}
        <PanelRightClose size={15} />
      {:else}
        <PanelRightOpen size={15} />
      {/if}
      Log details
    </Button>
    <Button
      variant="outline"
      size="icon"
      class="size-8"
      aria-expanded={!controlsCollapsed}
      aria-controls={filtersRegionId}
      aria-label={controlsCollapsed ? 'Expand log controls' : 'Collapse log controls'}
      title={controlsCollapsed ? 'Expand log controls' : 'Collapse log controls'}
      onclick={onToggleControlsCollapsed}
    >
      {#if controlsCollapsed}
        <ChevronDown size={16} />
      {:else}
        <ChevronUp size={16} />
      {/if}
    </Button>
  </div>
</div>
