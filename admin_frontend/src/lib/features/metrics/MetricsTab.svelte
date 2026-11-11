<script lang="ts">
  import { onMount } from 'svelte';
  import { RefreshCw } from '@lucide/svelte';
  import StickyBar from '$kit/ui/sticky-bar.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { setupMetricsTabRuntime } from '$lib/features/metrics/shared/metrics-page-lifecycle';
  import { createMetricsController } from '$lib/features/metrics/state/metrics-controller.svelte';
  import MetricsPanel from '$lib/features/metrics/view/MetricsPanel.svelte';
  import type { Notify } from '$kit/ui/toast.svelte';
  import { cn } from '$lib/utils';

  let { notify }: { notify: Notify } = $props();

  const ctrl = createMetricsController({
    notify: (kind, message) => notify(kind, message)
  });

  onMount(() => setupMetricsTabRuntime(ctrl));
</script>

<StickyBar class="-mx-4 border-b bg-background/85 px-4 backdrop-blur md:-mx-6 md:px-6">
  <div class="flex flex-wrap items-end gap-4">
    <FormField label="Enable metrics">
      <input
        class="size-4 accent-primary"
        type="checkbox"
        checked={ctrl.enabled}
        disabled={!ctrl.available || ctrl.applying}
        onchange={ctrl.onEnabledChange}
      />
    </FormField>
    <FormField label="Interval" class="min-w-60">
      <div class="flex items-center gap-3">
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
        <span class="w-12 text-right font-sans text-sm tabular-nums text-muted-foreground">
          {ctrl.intervalValue.toFixed(1)}s
        </span>
      </div>
    </FormField>
    <Button variant="outline" size="sm" disabled={ctrl.polling} onclick={() => void ctrl.loadTick(true)}>
      <RefreshCw size={15} class={cn(ctrl.polling && 'animate-spin')} />
      Refresh
    </Button>
    <Badge variant={ctrl.statusVariant}>{ctrl.statusText}</Badge>
  </div>
</StickyBar>

<MetricsPanel {ctrl} />
