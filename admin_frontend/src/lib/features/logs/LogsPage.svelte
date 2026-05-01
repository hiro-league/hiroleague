<script lang="ts">
  import { onMount, tick } from 'svelte';
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
  import { createCoreRowModel, createTable, type ColumnDef } from '@tanstack/svelte-table';
  import Button from '$lib/components/ui/button.svelte';
  import {
    getLogsLayout,
    LOG_LEVELS,
    searchLogs,
    tailLogs,
    type LogLevel,
    type LogRow,
    type LogSortOrder,
    type LogSourceFilter,
    type LogsLayout
  } from '$lib/api/logs';
  import { cn } from '$lib/utils';

  const PREF_KEY = 'hiro.admin.logs';
  const POLL_INTERVAL_MS = 500;
  const INITIAL_TAIL_LINES = 500;

  const sourceLabels: Record<LogSourceFilter, string> = {
    server: 'Server',
    channels: 'Channels',
    gateway: 'Gateway',
    cli: 'CLI'
  };

  type LogsPrefs = {
    paused?: boolean;
    sortOrder?: LogSortOrder;
    activeSources?: LogSourceFilter[];
    activeChannels?: string[];
    activeChannel?: string;
    levelFilter?: LogLevel[];
    searchText?: string;
    detailPanelOpen?: boolean;
    controlsCollapsed?: boolean;
  };

  type RenderLogRow = LogRow & {
    _rowKey: string;
  };

  const columns: ColumnDef<any, LogRow, unknown>[] = [
    { id: 'date_display', accessorKey: 'date_display', header: 'Date' },
    { id: 'timestamp_display', accessorKey: 'timestamp_display', header: 'Time' },
    { id: 'source', accessorKey: 'source', header: 'Source' },
    { id: 'module', accessorKey: 'module', header: 'Module' },
    { id: 'level', accessorKey: 'level', header: 'Lvl' },
    { id: 'message', accessorKey: 'message', header: 'Message' },
    { id: 'extra', accessorKey: 'extra', header: 'Extra' }
  ];

  let layout = $state<LogsLayout | null>(null);
  let rows = $state<RenderLogRow[]>([]);
  let fileOffsets = $state<Record<string, number>>({});
  let loading = $state(true);
  let error = $state<string | null>(null);
  let pollError = $state<string | null>(null);
  let paused = $state(false);
  let sortOrder = $state<LogSortOrder>('newest');
  let activeSources = $state<LogSourceFilter[]>([]);
  let activeChannel = $state('');
  let levelFilter = $state<LogLevel[]>([...LOG_LEVELS]);
  let searchText = $state('');
  let searchBusy = $state(false);
  let autoScroll = $state(true);
  let detailPanelOpen = $state(false);
  let controlsCollapsed = $state(false);
  let activeRowKey = $state<string | null>(null);
  let initialized = $state(false);
  let polling = false;
  let searchTimer: number | null = null;
  let tableScroller = $state<HTMLDivElement | null>(null);

  function sourcesForLayout(nextLayout: LogsLayout | null): LogSourceFilter[] {
    const sources: LogSourceFilter[] = ['server', 'channels'];
    if (nextLayout?.has_gateway) sources.push('gateway');
    if (nextLayout?.has_cli) sources.push('cli');
    return sources;
  }

  const availableSources = $derived.by<LogSourceFilter[]>(() => sourcesForLayout(layout));

  const channelsVisible = $derived(activeSources.includes('channels'));
  const isSearchMode = $derived(searchText.trim().length > 0);

  const visibleRows = $derived.by(() => {
    const filtered = rows.filter(rowPassesFilters);
    const direction = sortOrder === 'newest' ? -1 : 1;
    return [...filtered].sort((a, b) => (a.timestamp - b.timestamp) * direction);
  });

  const activeRow = $derived(
    activeRowKey ? visibleRows.find((row) => row._rowKey === activeRowKey) ?? null : null
  );

  const table = createTable({
    get data() {
      return visibleRows;
    },
    columns,
    getCoreRowModel: createCoreRowModel(),
    getRowId: (row: RenderLogRow) => row._rowKey
  } as any);

  function withRenderKeys(logRows: LogRow[], startIndex = 0): RenderLogRow[] {
    return logRows.map((row, index) => ({
      ...row,
      _rowKey: `${row.id}:${startIndex + index}`
    }));
  }

  function readPreferences() {
    const raw = sessionStorage.getItem(PREF_KEY);
    if (!raw) return;
    try {
      const prefs = JSON.parse(raw) as LogsPrefs;
      paused = Boolean(prefs.paused);
      sortOrder = prefs.sortOrder === 'oldest' ? 'oldest' : 'newest';
      activeSources = (prefs.activeSources ?? []).filter(isLogSourceFilter);
      activeChannel =
        typeof prefs.activeChannel === 'string'
          ? prefs.activeChannel
          : Array.isArray(prefs.activeChannels)
            ? prefs.activeChannels[0] ?? ''
            : '';
      levelFilter = (prefs.levelFilter ?? [...LOG_LEVELS]).filter(isLogLevel);
      searchText = String(prefs.searchText ?? '');
      detailPanelOpen = Boolean(prefs.detailPanelOpen);
      controlsCollapsed = Boolean(prefs.controlsCollapsed);
    } catch {
      sessionStorage.removeItem(PREF_KEY);
    }
  }

  function savePreferences() {
    const prefs: LogsPrefs = {
      paused,
      sortOrder,
      activeSources,
      activeChannel,
      levelFilter,
      searchText,
      detailPanelOpen,
      controlsCollapsed
    };
    sessionStorage.setItem(PREF_KEY, JSON.stringify(prefs));
  }

  function isLogSourceFilter(value: string): value is LogSourceFilter {
    return value === 'server' || value === 'channels' || value === 'gateway' || value === 'cli';
  }

  function isLogLevel(value: string): value is LogLevel {
    return LOG_LEVELS.includes(value as LogLevel);
  }

  function sourceIsActive(source: LogSourceFilter) {
    return activeSources.includes(source);
  }

  function levelIsActive(level: LogLevel) {
    return levelFilter.includes(level);
  }

  // Render log styling from structured fields so the UI does not need {@html}.
  function levelClass(level: string) {
    return isLogLevel(level) ? `log-lvl-${level.toLowerCase()}` : '';
  }

  function moduleClass(moduleName: string) {
    const bucket =
      Array.from(moduleName).reduce(
        (total, character) => total + (character.codePointAt(0) ?? 0),
        0
      ) % 4;
    return `log-mod-${bucket}`;
  }

  function rowPassesFilters(row: LogRow) {
    if (row.source === 'server' && !activeSources.includes('server')) return false;
    if (row.source === 'gateway' && !activeSources.includes('gateway')) return false;
    if (row.source === 'cli' && !activeSources.includes('cli')) return false;
    if (row.source.startsWith('channel-')) {
      if (!activeSources.includes('channels')) return false;
      const channel = row.source.replace(/^channel-/, '');
      if (activeChannel && activeChannel !== channel) return false;
    }
    if (levelFilter.length > 0 && !levelFilter.includes(row.level as LogLevel)) return false;
    return true;
  }

  function setActiveRow(row: RenderLogRow | null) {
    activeRowKey = row?._rowKey ?? null;
  }

  function selectRow(row: RenderLogRow) {
    setActiveRow(row);
    tableScroller?.focus();
  }

  function toggleSource(source: LogSourceFilter) {
    activeSources = sourceIsActive(source)
      ? activeSources.filter((item) => item !== source)
      : [...activeSources, source];
  }

  function toggleLevel(level: LogLevel) {
    levelFilter = levelIsActive(level)
      ? levelFilter.filter((item) => item !== level)
      : [...levelFilter, level];
  }

  function toggleSort() {
    sortOrder = sortOrder === 'newest' ? 'oldest' : 'newest';
  }

  function togglePause() {
    paused = !paused;
  }

  function toggleDetailPanel() {
    detailPanelOpen = !detailPanelOpen;
    if (detailPanelOpen && !activeRow && visibleRows.length > 0) {
      setActiveRow(visibleRows[0]);
    }
  }

  function toggleControlsCollapsed() {
    controlsCollapsed = !controlsCollapsed;
  }

  async function initialize() {
    loading = true;
    error = null;
    try {
      const layoutPayload = await getLogsLayout();
      const nextLayout = layoutPayload.data;
      layout = nextLayout;
      const validSources = sourcesForLayout(nextLayout);
      const restoredSources = activeSources.filter((source) => validSources.includes(source));
      activeSources =
        activeSources.length > 0 && restoredSources.length > 0 ? restoredSources : validSources;
      activeChannel = nextLayout.available_channels.includes(activeChannel) ? activeChannel : '';
      await reloadRows();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load logs.';
      rows = [];
    } finally {
      loading = false;
      initialized = true;
    }
  }

  async function reloadRows() {
    fileOffsets = {};
    if (searchText.trim()) {
      await runSearch(searchText);
      return;
    }
    const payload = await tailLogs({ lines: INITIAL_TAIL_LINES });
    rows = withRenderKeys(payload.data.rows);
    fileOffsets = payload.data.file_offsets;
    if (visibleRows.length > 0 && !activeRowKey) {
      activeRowKey = visibleRows[0]._rowKey;
    }
  }

  async function poll() {
    if (paused || isSearchMode || loading || polling || Object.keys(fileOffsets).length === 0) {
      return;
    }
    polling = true;
    try {
      const payload = await tailLogs({ after_offsets: fileOffsets });
      pollError = null;
      fileOffsets = payload.data.file_offsets;
      if (payload.data.rows.length > 0) {
        rows = [...rows, ...withRenderKeys(payload.data.rows, rows.length)];
      }
    } catch (err) {
      pollError = err instanceof Error ? err.message : 'Live log polling failed.';
    } finally {
      polling = false;
    }
  }

  async function runSearch(query: string) {
    const trimmed = query.trim();
    if (!trimmed) {
      searchBusy = false;
      await reloadRows();
      return;
    }
    searchBusy = true;
    error = null;
    try {
      const payload = await searchLogs(trimmed);
      if (searchText.trim() !== trimmed) return;
      rows = withRenderKeys(payload.data.rows);
      fileOffsets = {};
      activeRowKey = rows[0]?._rowKey ?? null;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Search failed.';
      rows = [];
      activeRowKey = null;
    } finally {
      searchBusy = false;
    }
  }

  function onSearchInput(event: Event) {
    searchText = (event.currentTarget as HTMLInputElement).value;
    if (searchTimer) {
      window.clearTimeout(searchTimer);
    }
    searchTimer = window.setTimeout(() => {
      searchTimer = null;
      void runSearch(searchText);
    }, 250);
  }

  async function clearSearch() {
    searchText = '';
    if (searchTimer) {
      window.clearTimeout(searchTimer);
      searchTimer = null;
    }
    loading = true;
    try {
      await reloadRows();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to reload logs.';
    } finally {
      loading = false;
    }
  }

  function moveActiveRow(delta: number) {
    if (visibleRows.length === 0) return;
    const currentIndex = activeRowKey
      ? visibleRows.findIndex((row) => row._rowKey === activeRowKey)
      : -1;
    const nextIndex =
      currentIndex < 0
        ? 0
        : Math.min(Math.max(currentIndex + delta, 0), visibleRows.length - 1);
    setActiveRow(visibleRows[nextIndex]);
    void tick().then(() => {
      tableScroller
        ?.querySelector('tr[data-active="true"]')
        ?.scrollIntoView({ block: 'nearest' });
    });
  }

  function handleTableKeydown(event: KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      moveActiveRow(1);
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      moveActiveRow(-1);
    }
  }

  function scrollToEdge() {
    if (!tableScroller || !autoScroll || visibleRows.length === 0) return;
    if (sortOrder === 'newest') {
      tableScroller.scrollTop = 0;
    } else {
      tableScroller.scrollTop = tableScroller.scrollHeight;
    }
  }

  $effect(() => {
    if (!initialized) return;
    savePreferences();
  });

  $effect(() => {
    if (!detailPanelOpen || activeRow || visibleRows.length === 0) return;
    activeRowKey = visibleRows[0]._rowKey;
  });

  $effect(() => {
    rows.length;
    visibleRows.length;
    sortOrder;
    if (!initialized || !autoScroll) return;
    void tick().then(scrollToEdge);
  });

  onMount(() => {
    readPreferences();
    void initialize();
    const interval = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(interval);
      if (searchTimer) window.clearTimeout(searchTimer);
    };
  });
</script>

<section class="logs-page flex h-[calc(100vh-6.5rem)] min-h-[620px] flex-col gap-4">
  <div class="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Operations</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Logs</h2>
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
            onclick={clearSearch}
          >
            <X size={14} />
          </button>
        {/if}
      </label>
      <Button variant="outline" size="sm" onclick={toggleSort}>
        <ArrowDownUp size={15} />
        {sortOrder === 'newest' ? 'Newest first' : 'Oldest first'}
      </Button>
      <Button variant="outline" size="sm" onclick={togglePause}>
        {#if paused}
          <Play size={15} />
          Resume
        {:else}
          <Pause size={15} />
          Pause
        {/if}
      </Button>
      <Button
        variant={autoScroll ? 'secondary' : 'outline'}
        size="sm"
        onclick={() => (autoScroll = !autoScroll)}
      >
        {#if sortOrder === 'newest'}
          <ChevronUp size={15} />
        {:else}
          <ChevronDown size={15} />
        {/if}
        Auto-scroll {autoScroll ? 'on' : 'off'}
      </Button>
      <span class="hidden h-6 w-px bg-border md:block"></span>
      <Button
        class="xl:ml-2"
        variant={detailPanelOpen ? 'secondary' : 'outline'}
        size="sm"
        onclick={toggleDetailPanel}
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
        aria-label={controlsCollapsed ? 'Expand log controls' : 'Collapse log controls'}
        title={controlsCollapsed ? 'Expand log controls' : 'Collapse log controls'}
        onclick={toggleControlsCollapsed}
      >
        {#if controlsCollapsed}
          <ChevronDown size={16} />
        {:else}
          <ChevronUp size={16} />
        {/if}
      </Button>
    </div>
  </div>

  <div
    class={cn(
      'logs-workspace min-h-0 flex-1',
      detailPanelOpen && 'logs-workspace--detail-open'
    )}
  >
    <div class="logs-left-col min-h-0 min-w-0">
      {#if !controlsCollapsed}
        <div class="grid gap-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-sans text-sm font-semibold text-muted-foreground">Source:</span>
            {#each availableSources as source (source)}
              <Button
                size="sm"
                variant={sourceIsActive(source) ? 'secondary' : 'ghost'}
                class={cn(
                  'h-8 border',
                  sourceIsActive(source)
                    ? 'border-border'
                    : 'border-transparent text-muted-foreground'
                )}
                onclick={() => toggleSource(source)}
              >
                {sourceLabels[source]}
              </Button>
            {/each}
            {#if channelsVisible && layout?.available_channels.length}
              <span class="ml-2 font-sans text-sm font-semibold text-muted-foreground">
                Channel:
              </span>
              <select
                class="h-8 min-w-44 rounded-md border border-input bg-background px-2 font-sans text-sm text-foreground shadow-xs outline-none focus:ring-2 focus:ring-ring"
                bind:value={activeChannel}
              >
                <option value="">All channels</option>
                {#each layout.available_channels as channel (channel)}
                  <option value={channel}>{channel}</option>
                {/each}
              </select>
            {/if}
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <span class="font-sans text-sm font-semibold text-muted-foreground">Level:</span>
            {#each LOG_LEVELS as level (level)}
              <Button
                size="sm"
                variant={levelIsActive(level) ? 'secondary' : 'ghost'}
                class={cn(
                  'h-8 border',
                  levelIsActive(level)
                    ? `log-chip-${level.toLowerCase()}`
                    : 'border-transparent text-muted-foreground'
                )}
                onclick={() => toggleLevel(level)}
              >
                {level}
              </Button>
            {/each}
          </div>

          <div class="flex flex-wrap items-center gap-3">
            <div class="font-sans text-xs text-muted-foreground">
              {visibleRows.length} visible / {rows.length} loaded
              {#if searchBusy}
                <span class="ml-2 text-primary">Searching...</span>
              {:else if isSearchMode}
                <span class="ml-2 text-primary">Search mode</span>
              {/if}
            </div>
          </div>
        </div>
      {/if}

      {#if error}
        <div class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 font-sans text-sm text-destructive">
          {error}
        </div>
      {:else if pollError}
        <div class="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 font-sans text-sm text-amber-700 dark:text-amber-300">
          {pollError}
        </div>
      {/if}

      <div class="logs-table-panel min-w-0 flex-1 rounded-md border bg-card/70">
        {#if loading}
          <div class="grid h-full min-h-80 place-items-center font-sans text-sm text-muted-foreground">
            Loading logs...
          </div>
        {:else}
          <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
          <div
            class="logs-table-scroll h-full overflow-auto outline-none"
            tabindex="0"
            role="application"
            aria-label="Log rows"
            bind:this={tableScroller}
            onkeydown={handleTableKeydown}
          >
            <table class="w-full min-w-[1080px] table-fixed border-collapse font-sans text-xs">
              <thead class="sticky top-0 z-10 bg-card text-left text-muted-foreground shadow-sm">
                {#each table.getHeaderGroups() as headerGroup (headerGroup.id)}
                  <tr>
                    {#each headerGroup.headers as header (header.id)}
                      <th
                        class={cn(
                          'border-b px-2 py-2 font-semibold',
                          header.id === 'date_display' && 'w-[78px]',
                          header.id === 'timestamp_display' && 'w-[116px] text-right',
                          header.id === 'source' && 'w-[136px]',
                          header.id === 'module' && 'w-[132px]',
                          header.id === 'level' && 'w-[84px]',
                          header.id === 'message' && 'w-[420px]',
                          header.id === 'extra' && 'w-auto'
                        )}
                      >
                        {String(header.column.columnDef.header ?? header.id)}
                      </th>
                    {/each}
                  </tr>
                {/each}
              </thead>
              <tbody>
                {#each table.getRowModel().rows as tableRow (tableRow.id)}
                  {@const row = tableRow.original as RenderLogRow}
                  <tr
                    class={cn(
                      'cursor-default border-b border-border/60 transition-colors hover:bg-secondary/30',
                      row.is_startup && 'log-startup-row',
                      activeRowKey === row._rowKey && 'bg-primary/10 outline outline-1 outline-primary/30'
                    )}
                    data-active={activeRowKey === row._rowKey ? 'true' : undefined}
                    onclick={() => selectRow(row)}
                  >
                    <td class="truncate px-2 py-1.5 text-muted-foreground">{row.date_display}</td>
                    <td class="truncate px-2 py-1.5 text-right text-muted-foreground">
                      {row.timestamp_display}
                    </td>
                    <td class="truncate px-2 py-1.5">{row.source}</td>
                    <td class="truncate px-2 py-1.5">
                      <span class={moduleClass(row.module)}>{row.module}</span>
                    </td>
                    <td class="truncate px-2 py-1.5">
                      <span class={levelClass(row.level)}>{row.level}</span>
                    </td>
                    <td class="truncate px-2 py-1.5" title={row.message}>
                      {#if row.is_startup}
                        <span class="log-startup-msg">{row.message}</span>
                      {:else}
                        {row.message}
                      {/if}
                    </td>
                    <td class="log-extra-cell truncate px-2 py-1.5" title={row.extra}>
                      {#each row.extra_segments as segment}
                        <span class="log-extra-segment">
                          {#if segment.key}
                            <span class="log-extra-key">{segment.key}</span><span class="log-extra-eq">=</span><span class="log-extra-val">{segment.value}</span>
                          {:else}
                            <span class="log-extra-val">{segment.value}</span>
                          {/if}
                        </span>
                      {/each}
                      {#if row.extra_segments.length}
                        <div class="log-extra-tooltip">
                          {#each row.extra_segments as segment}
                            <div class="log-extra-tooltip-row">
                              {#if segment.key}
                                <span class="log-extra-key">{segment.key}</span><span class="log-extra-eq">=</span><span class="log-extra-val">{segment.value}</span>
                              {:else}
                                <span class="log-extra-val">{segment.value}</span>
                              {/if}
                            </div>
                          {/each}
                        </div>
                      {/if}
                    </td>
                  </tr>
                {:else}
                  <tr>
                    <td colspan="7" class="px-3 py-10 text-center text-muted-foreground">
                      No log rows match the current filters.
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    </div>

    {#if detailPanelOpen}
      <aside class="logs-detail-panel rounded-md border bg-card/80">
        <div class="flex items-center justify-between border-b px-3 py-2">
          <h3 class="font-sans text-sm font-semibold">Log line</h3>
          <Button variant="ghost" size="icon" class="size-8" onclick={() => (detailPanelOpen = false)}>
            <X size={15} />
          </Button>
        </div>
        <div class="logs-detail-body">
          {#if activeRow}
            <div class="detail-field">
              <span>Time</span>
              <p>{activeRow.date_display} {activeRow.timestamp_display}</p>
            </div>
            <div class="detail-field">
              <span>Timestamp (epoch)</span>
              <p>{activeRow.timestamp}</p>
            </div>
            <div class="detail-field">
              <span>Source</span>
              <p>{activeRow.source}</p>
            </div>
            <div class="detail-field">
              <span>Level</span>
              <p>{activeRow.level}</p>
            </div>
            <div class="detail-field">
              <span>Module</span>
              <p>{activeRow.module}</p>
            </div>
            <div class="detail-field">
              <span>Message</span>
              {#if activeRow.message_pretty}
                <pre>{activeRow.message_pretty}</pre>
              {:else}
                <p>{activeRow.message || '-'}</p>
              {/if}
            </div>
            <div class="detail-field">
              <span>Extra</span>
              {#if activeRow.extra_segments.length}
                {#each activeRow.extra_segments as segment}
                  <div class="mt-2">
                    <span>{segment.key ?? 'value'}</span>
                    {#if segment.pretty}
                      <pre>{segment.pretty}</pre>
                    {:else}
                      <p>{segment.value || '-'}</p>
                    {/if}
                  </div>
                {/each}
              {:else}
                <p>-</p>
              {/if}
            </div>
          {:else}
            <p class="p-3 font-sans text-sm text-muted-foreground">
              Click a row in the table to inspect a log line.
            </p>
          {/if}
        </div>
      </aside>
    {/if}
  </div>
</section>

<style>
  .logs-workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.75rem;
    overflow: hidden;
  }

  .logs-left-col {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    overflow: hidden;
  }

  .logs-table-panel {
    min-height: 0;
    overflow: hidden;
  }

  .logs-detail-panel {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  .logs-detail-body {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 0.75rem;
  }

  @media (min-width: 1180px) {
    .logs-workspace--detail-open {
      grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
    }
  }

  :global(.log-lvl-debug) {
    color: #38bdf8;
  }

  :global(.log-lvl-fineinfo) {
    color: #22d3ee;
  }

  :global(.log-lvl-info) {
    color: #10b981;
  }

  :global(.log-lvl-warning) {
    color: #f59e0b;
    font-weight: 700;
  }

  :global(.log-lvl-error) {
    color: #ef4444;
    font-weight: 700;
  }

  :global(.log-lvl-critical) {
    color: #d946ef;
    font-weight: 700;
  }

  :global(.log-mod-0) {
    color: #38bdf8;
  }

  :global(.log-mod-1) {
    color: #d946ef;
  }

  :global(.log-mod-2) {
    color: #f59e0b;
  }

  :global(.log-mod-3) {
    color: #10b981;
  }

  :global(.log-extra-key) {
    color: var(--brand-green);
  }

  :global(.log-extra-eq) {
    opacity: 0.6;
    margin: 0 1px;
  }

  :global(.log-extra-val) {
    color: var(--primary);
  }

  :global(.log-startup-msg) {
    font-weight: 700;
  }

  .log-startup-row td {
    background: color-mix(in srgb, var(--primary) 10%, transparent);
  }

  .log-extra-cell {
    position: relative;
  }

  .log-extra-segment + .log-extra-segment {
    margin-left: 0.35rem;
  }

  .log-extra-tooltip {
    display: none;
    position: fixed;
    z-index: 50;
    max-width: 500px;
    transform: translateY(1.25rem);
    white-space: normal;
    word-break: break-word;
    border: 1px solid var(--border);
    border-radius: 0.375rem;
    background: var(--popover);
    color: var(--popover-foreground);
    padding: 0.5rem 0.75rem;
    line-height: 1.45;
    box-shadow: 0 12px 30px rgb(0 0 0 / 0.25);
  }

  .log-extra-cell:hover .log-extra-tooltip {
    display: block;
  }

  :global(.log-extra-tooltip-row) {
    display: block;
  }

  :global(.log-extra-tooltip-row + .log-extra-tooltip-row) {
    margin-top: 0.25rem;
  }

  .detail-field {
    margin-top: 0.75rem;
    font-family: var(--font-sans);
  }

  .detail-field:first-child {
    margin-top: 0;
  }

  .detail-field span {
    display: block;
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    color: var(--muted-foreground);
  }

  .detail-field p,
  .detail-field pre {
    margin: 0.25rem 0 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: 0.82rem;
  }

  .detail-field pre {
    border-radius: 0.375rem;
    background: color-mix(in srgb, var(--muted) 70%, transparent);
    padding: 0.5rem 0.65rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    line-height: 1.35;
  }

  .log-chip-debug {
    color: #38bdf8;
  }

  .log-chip-fineinfo {
    color: #22d3ee;
  }

  .log-chip-info {
    color: #10b981;
  }

  .log-chip-warning {
    color: #f59e0b;
  }

  .log-chip-error {
    color: #ef4444;
  }

  .log-chip-critical {
    color: #d946ef;
  }
</style>
