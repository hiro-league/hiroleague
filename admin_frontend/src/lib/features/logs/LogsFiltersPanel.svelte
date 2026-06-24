<script lang="ts">
  import { isTrafficClass, TRAFFIC_CLASSES } from '$lib/api/logs';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import MultiSelectFilter, {
    type MultiSelectOption
  } from '$lib/components/ui/multi-select-filter.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { X } from '@lucide/svelte';
  import type { LogsPageController } from './state/logs-controller.svelte';
  import type { LogsPreferences } from '$lib/preferences/logs-preferences.svelte';
  import { FILTER_CLEAR_ICON_BTN } from '$lib/styling/admin-tokens';
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

  let { prefs, ctrl }: Props = $props();

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

  const channelOptions = $derived(
    (ctrl.layout?.available_channels ?? []).map((channel) => ({ value: channel, label: channel }))
  );
  const deviceOptions = $derived(
    ctrl.devicesForLogs.map((dev) => {
      const fullLabel = dev.device_name?.trim() || dev.device_id;
      const truncatedLabel = fullLabel.length > 20 ? `${fullLabel.slice(0, 19)}…` : fullLabel;
      return { value: dev.device_id, label: truncatedLabel, title: fullLabel };
    })
  );
  const methodOptions = $derived(ctrl.logMethods.map((m) => ({ value: m, label: m })));
</script>

<div class="grid min-w-0 gap-3">
  <div class="min-w-0 overflow-x-auto pb-0.5">
    <div class="flex flex-col gap-3">
      <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <MultiSelectFilter
          label="Source"
          options={sourceOptions}
          selected={prefs.activeSources}
          searchPlaceholder="Search sources…"
          onSelectedChange={onSourceSelectedChange}
        />

        {#if ctrl.channelsVisible && ctrl.layout && ctrl.layout.available_channels.length}
          <AdminFilterBarSelect
            layout="inline"
            label="Channel:"
            clearable
            bind:value={prefs.activeChannel}
            options={channelOptions}
            placeholder="All channels"
            selectClass="min-w-44"
            onClear={() => {
              prefs.activeChannel = '';
            }}
          />
        {/if}

        <AdminFilterBarSelect
          layout="inline"
          clearable
          bind:value={prefs.scopeDeviceId}
          options={deviceOptions}
          placeholder="All devices"
          selectClass="min-w-48"
          title="Filter logs by device (only devices seen in currently loaded log rows)"
          onClear={() => ctrl.removeScopeDevice()}
          onValueChange={() => void ctrl.afterScopeChange()}
        />

        <AdminFilterBarSelect
          layout="inline"
          clearable
          bind:value={prefs.scopeMethod}
          options={methodOptions}
          placeholder="All request types"
          selectClass="min-w-44 font-mono"
          title="Filter by JSON-RPC method seen in recent logs"
          onClear={() => ctrl.removeScopeMethod()}
          onValueChange={() => void ctrl.afterScopeChange()}
        />

        <MultiSelectFilter
          label="Traffic"
          options={trafficOptions}
          selected={prefs.trafficClassFilter}
          searchPlaceholder="Search traffic classes…"
          onSelectedChange={onTrafficSelectedChange}
        />
      </div>

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
