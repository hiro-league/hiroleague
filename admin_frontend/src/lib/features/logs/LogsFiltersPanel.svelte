<script lang="ts">
  import { X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { isTrafficClass, TRAFFIC_CLASSES } from '$lib/api/logs';
  import MultiSelectFilter, {
    type MultiSelectOption
  } from '$lib/components/ui/multi-select-filter.svelte';
  import type { LogsPageController } from './state/logs-controller.svelte';
  import type { LogsPreferences } from '$lib/preferences/logs-preferences.svelte';
  import FilterSelectWithClear from './shared/FilterSelectWithClear.svelte';
  import { FILTER_CLEAR_ICON_BTN } from './shared/logs-classes';
  import {
    SOURCE_LABELS,
    TRAFFIC_CLASS_LABELS,
    isLogSourceFilter,
    msgIdFilterPreview
  } from './shared/logs-ui';

  type Props = {
    prefs: LogsPreferences;
    ctrl: LogsPageController;
  };

  // Collapse region/id owned by the parent sticky toolbar (LogsPage) so the whole
  // controls line — toolbar buttons + these filters — collapses together. Level now
  // lives on the search/toolbar line (LogsPage); the rest of the filters live here.
  let { prefs, ctrl }: Props = $props();

  // Source + Traffic both use the searchable multi-select (graph-tab "Edges" widget).
  // Both store the explicit set of SHOWN values, so Select-all / Clear map 1:1.
  const sourceOptions = $derived<MultiSelectOption[]>(
    ctrl.availableSources.map((s) => ({ value: s, label: SOURCE_LABELS[s] }))
  );
  function onSourceSelectedChange(values: string[]) {
    prefs.activeSources = values.filter(isLogSourceFilter);
  }

  const trafficOptions: MultiSelectOption[] = TRAFFIC_CLASSES.map((tc) => ({
    value: tc,
    label: TRAFFIC_CLASS_LABELS[tc]
  }));
  function onTrafficSelectedChange(values: string[]) {
    prefs.trafficClassFilter = values.filter(isTrafficClass);
  }
</script>

<div class="grid min-w-0 gap-3">
  <div class="min-w-0 overflow-x-auto pb-0.5">
    <div class="flex flex-col gap-3">
      <!-- Line 1: Source · Channel · device · request types · Traffic -->
      <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <MultiSelectFilter
          label="Source"
          options={sourceOptions}
          selected={prefs.activeSources}
          searchPlaceholder="Search sources…"
          onSelectedChange={onSourceSelectedChange}
        />

        {#if ctrl.channelsVisible && ctrl.layout && ctrl.layout.available_channels.length}
          <FilterSelectWithClear
            label="Channel:"
            bind:value={prefs.activeChannel}
            selectClass="min-w-44"
            titleClear="Clear channel filter"
            ariaLabelClear="Clear channel filter"
            onClear={() => {
              prefs.activeChannel = '';
            }}
          >
            {#snippet options()}
              <option value="">All channels</option>
              {#each ctrl.layout!.available_channels as channel (channel)}
                <option value={channel}>{channel}</option>
              {/each}
            {/snippet}
          </FilterSelectWithClear>
        {/if}

        <FilterSelectWithClear
          bind:value={prefs.scopeDeviceId}
          selectClass="min-w-48"
          title="Filter logs by device (only devices seen in currently loaded log rows)"
          titleClear="Clear device filter"
          ariaLabelClear="Clear device filter"
          onClear={() => ctrl.removeScopeDevice()}
          onChange={() => void ctrl.afterScopeChange()}
        >
          {#snippet options()}
            <option value="">All devices</option>
            {#each ctrl.devicesForLogs as dev (dev.device_id)}
              {@const fullLabel = dev.device_name?.trim() || dev.device_id}
              {@const truncatedLabel =
                fullLabel.length > 20 ? `${fullLabel.slice(0, 19)}…` : fullLabel}
              <option value={dev.device_id} title={fullLabel}>
                {truncatedLabel}
              </option>
            {/each}
          {/snippet}
        </FilterSelectWithClear>

        <FilterSelectWithClear
          bind:value={prefs.scopeMethod}
          selectClass="min-w-44 font-mono"
          title="Filter by JSON-RPC method seen in recent logs"
          titleClear="Clear request type filter"
          ariaLabelClear="Clear request type filter"
          onClear={() => ctrl.removeScopeMethod()}
          onChange={() => void ctrl.afterScopeChange()}
        >
          {#snippet options()}
            <option value="">All request types</option>
            {#each ctrl.logMethods as m (m)}
              <option value={m}>{m}</option>
            {/each}
          {/snippet}
        </FilterSelectWithClear>

        <MultiSelectFilter
          label="Traffic"
          options={trafficOptions}
          selected={prefs.trafficClassFilter}
          searchPlaceholder="Search traffic classes…"
          onSelectedChange={onTrafficSelectedChange}
        />
      </div>

      <!-- Line 2: Message (only when a message filter is set) -->
      {#if prefs.scopeMsgId.trim()}
        <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
          <div class="flex min-w-0 items-center gap-2">
            <span class="shrink-0 font-sans text-sm font-semibold text-muted-foreground">
              Message:
            </span>
            <span
              class="min-w-0 truncate font-mono text-sm text-foreground"
              title={prefs.scopeMsgId.trim()}
            >
              {msgIdFilterPreview(prefs.scopeMsgId.trim())}
            </span>
            <div class="inline-flex size-8 shrink-0 items-center justify-center">
              <Button
                variant="ghost"
                size="icon"
                class={FILTER_CLEAR_ICON_BTN}
                onclick={() => ctrl.removeScopeMsg()}
                title="Remove message filter"
                aria-label="Remove message filter"
              >
                <X size={15} strokeWidth={2} />
              </Button>
            </div>
          </div>
        </div>
      {/if}
    </div>
  </div>
</div>
