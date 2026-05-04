<script lang="ts">
  import { X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { LOG_LEVELS } from '$lib/api/logs';
  import { cn } from '$lib/utils';
  import type { LogsPageController } from './state/logs-controller.svelte';
  import type { LogsPreferences } from './state/logs-preferences.svelte';
  import { logLevelFilterChipClass, logSourceFilterChipClass } from './shared/logs-classes';
  import LogLevelIcon from './shared/LogLevelIcon.svelte';
  import LogSourceIcon from './shared/LogSourceIcon.svelte';
  import { SOURCE_LABELS, msgIdFilterPreview } from './shared/logs-ui';

  type Props = {
    prefs: LogsPreferences;
    ctrl: LogsPageController;
    regionId: string;
    regionHidden: boolean;
  };

  let { prefs, ctrl, regionId, regionHidden }: Props = $props();

  /** Icon-only clears for selects: reserved width so layout doesn’t shift when empty. */
  const filterClearIconBtnClass =
    'size-8 shrink-0 text-destructive hover:bg-destructive/15 hover:text-destructive';
</script>

<div
  id={regionId}
  class="grid min-w-0 gap-3"
  role="region"
  aria-label="Log filters"
  hidden={regionHidden}
>
  <div class="min-w-0 overflow-x-auto pb-0.5">
    <!-- Single 2×2: Source | Scope / Level | Message (auto row-major placement). -->
    <div
      class="grid w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] grid-rows-2 items-start gap-x-2 gap-y-3"
    >
      <div class="flex min-w-0 flex-wrap items-center gap-2">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Source:</span>
        {#each ctrl.availableSources as source (source)}
          <Button
            size="sm"
            variant={prefs.sourceIsActive(source) ? 'secondary' : 'ghost'}
            class={cn(logSourceFilterChipClass(prefs.sourceIsActive(source)), 'shadow-none')}
            onclick={() => prefs.toggleSource(source)}
          >
            <LogSourceIcon
              source={source}
              size={11}
              class="shrink-0 opacity-80"
            />
            {SOURCE_LABELS[source]}
          </Button>
        {/each}
        {#if ctrl.channelsVisible && ctrl.layout && ctrl.layout.available_channels.length}
          <span class="ml-2 font-sans text-sm font-semibold text-muted-foreground">Channel:</span>
          <div class="flex items-center gap-0.5">
            <select
              class="h-8 min-w-44 rounded-md border border-input bg-background px-2 font-sans text-sm text-foreground shadow-xs outline-none focus:ring-2 focus:ring-ring"
              bind:value={prefs.activeChannel}
            >
              <option value="">All channels</option>
              {#each ctrl.layout.available_channels as channel (channel)}
                <option value={channel}>{channel}</option>
              {/each}
            </select>
            <div class="inline-flex size-8 shrink-0 items-center justify-center">
              {#if prefs.activeChannel}
                <Button
                  variant="ghost"
                  size="icon"
                  class={filterClearIconBtnClass}
                  onclick={() => {
                    prefs.activeChannel = '';
                  }}
                  title="Clear channel filter"
                  aria-label="Clear channel filter"
                >
                  <X size={15} strokeWidth={2} />
                </Button>
              {/if}
            </div>
          </div>
        {/if}
      </div>

      <div class="flex min-w-0 flex-nowrap items-center gap-3">
        <div class="flex items-center gap-0.5">
          <select
            class="h-8 min-w-48 rounded-md border border-input bg-background px-2 font-sans text-sm text-foreground shadow-xs outline-none focus:ring-2 focus:ring-ring"
            bind:value={prefs.scopeDeviceId}
            onchange={() => void ctrl.afterScopeChange()}
            title="Filter logs by paired device (workspace DB)"
          >
            <option value="">All devices</option>
            {#each ctrl.devicesForLogs as dev (dev.device_id)}
              <option value={dev.device_id}>
                {dev.device_name?.trim() || dev.device_id}
              </option>
            {/each}
          </select>
          <div class="inline-flex size-8 shrink-0 items-center justify-center">
            {#if prefs.scopeDeviceId.trim()}
              <Button
                variant="ghost"
                size="icon"
                class={filterClearIconBtnClass}
                onclick={() => ctrl.removeScopeDevice()}
                title="Clear device filter"
                aria-label="Clear device filter"
              >
                <X size={15} strokeWidth={2} />
              </Button>
            {/if}
          </div>
        </div>
        <div class="flex items-center gap-0.5">
          <select
            class="h-8 min-w-44 rounded-md border border-input bg-background px-2 font-mono text-sm text-foreground shadow-xs outline-none focus:ring-2 focus:ring-ring"
            bind:value={prefs.scopeMethod}
            onchange={() => void ctrl.afterScopeChange()}
            title="Filter by JSON-RPC method seen in recent logs"
          >
            <option value="">All request types</option>
            {#each ctrl.logMethods as m (m)}
              <option value={m}>{m}</option>
            {/each}
          </select>
          <div class="inline-flex size-8 shrink-0 items-center justify-center">
            {#if prefs.scopeMethod.trim()}
              <Button
                variant="ghost"
                size="icon"
                class={filterClearIconBtnClass}
                onclick={() => ctrl.removeScopeMethod()}
                title="Clear request type filter"
                aria-label="Clear request type filter"
              >
                <X size={15} strokeWidth={2} />
              </Button>
            {/if}
          </div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Level:</span>
        {#each LOG_LEVELS as level (level)}
          <Button
            size="sm"
            variant={prefs.levelIsActive(level) ? 'secondary' : 'ghost'}
            class={cn(logLevelFilterChipClass(prefs.levelIsActive(level), level), 'shadow-none')}
            onclick={() => prefs.toggleLevel(level)}
          >
            <LogLevelIcon level={level} size={11} class="shrink-0" />
            {level}
          </Button>
        {/each}
      </div>

      <div class="min-w-0">
        {#if prefs.scopeMsgId.trim()}
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
                class={filterClearIconBtnClass}
                onclick={() => ctrl.removeScopeMsg()}
                title="Remove message filter"
                aria-label="Remove message filter"
              >
                <X size={15} strokeWidth={2} />
              </Button>
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>
