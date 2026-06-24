<script lang="ts">
  import { ChevronDown, ChevronUp, PanelRightClose, PanelRightOpen, Pause, Play, Trash2 } from '@lucide/svelte';
  import SearchInput from '$lib/search/SearchInput.svelte';
  import type { LogTimeRange } from '$lib/api/logs';
  import Button from '$lib/components/ui/button.svelte';
  import AdminIconToggleGroup from '$lib/components/page/AdminIconToggleGroup.svelte';
  import { ADMIN_INPUT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import { LOG_LEVELS, LOG_TIME_RANGES } from '$lib/api/logs';
  import type { LogsPageController } from './state/logs-controller.svelte';
  import type { LogsPreferences } from '$lib/preferences/logs-preferences.svelte';
  import { logLevelAccentClass } from './shared/logs-classes';
  import LogLevelIcon from './shared/LogLevelIcon.svelte';
  import { LOGS_FILTER_REGION_ID } from './shared/logs-a11y';
  import { isLogTimeRange } from './shared/logs-ui';

  type Props = {
    prefs: LogsPreferences;
    ctrl: LogsPageController;
    onRequestClearLogs: () => void;
    filters: import('svelte').Snippet;
  };

  let { prefs, ctrl, onRequestClearLogs, filters }: Props = $props();

  const timeRangeLabels: Record<LogTimeRange, string> = {
    '1h': '1 hr',
    '2h': '2 hrs',
    '4h': '4 hrs',
    '1d': '1 day',
    '2d': '2 days',
    '3d': '3 days',
    all: 'All'
  };

  // Merged "Last session" + time-range picker: "last" pins to the latest server
  // startup; any other value is a rolling past-window.
  function onSessionRangeChange(value: string) {
    if (value === 'last') {
      prefs.lastSessionOnly = true;
    } else if (isLogTimeRange(value)) {
      prefs.lastSessionOnly = false;
      prefs.logTimeRange = value;
    } else {
      return;
    }
    void ctrl.reloadLiveTail();
  }
  const logLevelOptions = $derived(
    LOG_LEVELS.map((level) => ({
      value: level,
      label: `${prefs.levelIsActive(level) ? 'Hide' : 'Show'} ${level} logs`
    }))
  );
</script>

<div class="flex flex-col gap-3">
  <div class="flex min-w-0 flex-wrap items-center gap-2">
    <AdminIconToggleGroup
      label="Level:"
      layout="inline"
      appearance="toolbar"
      options={logLevelOptions}
      isSelected={(level) => prefs.levelIsActive(level as (typeof LOG_LEVELS)[number])}
      onToggle={(level) => prefs.toggleLevel(level as (typeof LOG_LEVELS)[number])}
    >
      {#snippet optionContent(option, active)}
        <LogLevelIcon
          level={option.value as (typeof LOG_LEVELS)[number]}
          size={14}
          class={cn('shrink-0', active ? logLevelAccentClass(option.value as (typeof LOG_LEVELS)[number]) : 'opacity-40')}
        />
      {/snippet}
    </AdminIconToggleGroup>
    <SearchInput
      variant="inline"
      value={prefs.searchText}
      onValueChange={ctrl.onSearchInput}
      placeholder="Search logs..."
    />
    <Button
      variant="outline"
      size="icon"
      class="size-8"
      title={prefs.paused ? 'Resume live tail' : 'Pause live tail'}
      aria-label={prefs.paused ? 'Resume live tail' : 'Pause live tail'}
      onclick={() => prefs.togglePause()}
    >
      {#if prefs.paused}
        <Play size={15} />
      {:else}
        <Pause size={15} />
      {/if}
    </Button>
    {#if ctrl.blocksLiveTail}
      <Button variant="outline" size="sm" onclick={() => void ctrl.clearAllFilters()}>
        Clear filters
      </Button>
    {/if}
    <label class="flex items-center gap-1.5 font-sans text-sm text-muted-foreground">
      <span class="sr-only">Time window</span>
      <select
        class={cn(ADMIN_INPUT, 'min-w-[7rem] px-2')}
        value={prefs.lastSessionOnly ? 'last' : prefs.logTimeRange}
        onchange={(event) =>
          onSessionRangeChange((event.currentTarget as HTMLSelectElement).value)}
        aria-label="Log time window"
        title="Show logs from the last session or a rolling time window"
      >
        <option value="last">Last session</option>
        {#each LOG_TIME_RANGES as r (r)}
          <option value={r}>{timeRangeLabels[r]}</option>
        {/each}
      </select>
    </label>
    <!-- Trailing actions grouped to the right; the collapse chevron pins to the far
         right of the line so the first toolbar row stays usable while collapsed. -->
    <div class="ml-auto flex items-center gap-2">
      <span class="hidden h-6 w-px bg-border md:block"></span>
      <!-- Icon-only toggle for the right-hand log details panel. -->
      <Button
        variant="outline"
        size="icon"
        class="size-8"
        title={prefs.detailPanelOpen ? 'Hide log details' : 'Show log details'}
        aria-label={prefs.detailPanelOpen ? 'Hide log details' : 'Show log details'}
        aria-pressed={prefs.detailPanelOpen}
        onclick={() => (prefs.detailPanelOpen = !prefs.detailPanelOpen)}
      >
        {#if prefs.detailPanelOpen}
          <PanelRightClose size={15} />
        {:else}
          <PanelRightOpen size={15} />
        {/if}
      </Button>
      <Button
        variant="destructive"
        size="icon"
        class="size-8"
        title={ctrl.clearingLogs ? 'Clearing logs…' : 'Clear all logs'}
        aria-label="Clear all logs"
        onclick={onRequestClearLogs}
        disabled={ctrl.clearingLogs}
      >
        <Trash2 size={15} />
      </Button>
      <!-- Collapse/expand the secondary-filters line below. -->
      <Button
        variant="outline"
        size="icon"
        class="size-8"
        aria-expanded={!prefs.controlsCollapsed}
        aria-controls={LOGS_FILTER_REGION_ID}
        aria-label={prefs.controlsCollapsed ? 'Expand log filters' : 'Collapse log filters'}
        title={prefs.controlsCollapsed ? 'Expand log filters' : 'Collapse log filters'}
        onclick={() => prefs.toggleControlsCollapsed()}
      >
        {#if prefs.controlsCollapsed}
          <ChevronDown size={16} />
        {:else}
          <ChevronUp size={16} />
        {/if}
      </Button>
    </div>
  </div>

  <div
    id={LOGS_FILTER_REGION_ID}
    role="region"
    aria-label="Log filters"
    class={cn(prefs.controlsCollapsed && 'hidden')}
  >
    {@render filters()}
  </div>
</div>
