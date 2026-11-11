<script lang="ts">
  import { onMount } from 'svelte';
  import { RefreshCw } from '@lucide/svelte';
  import StickyBar from '$kit/ui/sticky-bar.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Checkbox } from '$kit/components/ui/checkbox/index.js';
  import SliderField from '$kit/ui/slider-field.svelte';
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
      <Checkbox
        checked={ctrl.enabled}
        disabled={!ctrl.available || ctrl.applying}
        onCheckedChange={ctrl.onEnabledChange}
      />
    </FormField>
    <SliderField
      label="Interval"
      class="min-w-60"
      min={1}
      max={10}
      step={0.5}
      value={ctrl.intervalValue}
      disabled={!ctrl.available || ctrl.applying}
      onchange={ctrl.onIntervalInput}
      oncommit={() => ctrl.onIntervalChange()}
      format={(v) => `${v.toFixed(1)}s`}
    />
    <Button variant="outline" size="sm" disabled={ctrl.polling} onclick={() => void ctrl.loadTick(true)}>
      <RefreshCw size={15} class={cn(ctrl.polling && 'animate-spin')} />
      Refresh
    </Button>
    <Badge variant={ctrl.statusVariant}>{ctrl.statusText}</Badge>
  </div>
</StickyBar>

<MetricsPanel {ctrl} />
