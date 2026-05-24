<script lang="ts">
  import { onMount } from 'svelte';
  import { RefreshCw } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import MetricsPanel from '$lib/features/metrics/MetricsPanel.svelte';
  import { createMetricsController } from '$lib/features/metrics/state/metrics-controller.svelte';
  import { cn } from '$lib/utils';

  const ctrl = createMetricsController();

  onMount(() => ctrl.startPolling());
</script>

<AdminPageHeader kicker="Operations" title="Metrics" sticky>
  {#snippet actions()}
    <div class="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-3">
      <label class="inline-flex items-center gap-2 font-sans text-sm font-semibold">
        <input
          class="size-4 accent-primary"
          type="checkbox"
          checked={ctrl.enabled}
          disabled={!ctrl.available || ctrl.applying}
          onchange={ctrl.onEnabledChange}
        />
        Enable metrics
      </label>
      <label class="flex min-w-60 items-center gap-3 font-sans text-sm text-muted-foreground">
        <span class="font-semibold text-foreground">Interval</span>
        <input
          class="min-w-36 flex-1 accent-primary"
          type="range"
          min="1"
          max="10"
          step="0.5"
          value={ctrl.intervalValue}
          disabled={!ctrl.available || ctrl.applying}
          oninput={ctrl.onIntervalInput}
          onchange={ctrl.onIntervalChange}
        />
        <span class="w-12 text-right">{ctrl.intervalValue.toFixed(1)}s</span>
      </label>
      <Button variant="outline" size="sm" disabled={ctrl.polling} onclick={() => void ctrl.loadTick(true)}>
        <RefreshCw size={15} class={cn(ctrl.polling && 'animate-spin')} />
        Refresh
      </Button>
      <Badge variant={ctrl.statusVariant}>{ctrl.statusText}</Badge>
    </div>
  {/snippet}

  <MetricsPanel {ctrl} />
</AdminPageHeader>
