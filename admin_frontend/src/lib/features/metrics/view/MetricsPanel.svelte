<script lang="ts">
  import { Server } from '@lucide/svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import InlineWarningAlert from '$lib/ui/InlineWarningAlert.svelte';
  import type { MetricsController } from '../state/metrics-controller.svelte';
  import MetricsChannelPluginsSection from './MetricsChannelPluginsSection.svelte';
  import MetricsIoSection from './MetricsIoSection.svelte';
  import MetricsProcessSection from './MetricsProcessSection.svelte';
  import MetricsSystemSection from './MetricsSystemSection.svelte';

  type Props = {
    ctrl: MetricsController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.error}
  <InlineDestructiveAlert message={ctrl.error} />
{:else if ctrl.pollError}
  <InlineWarningAlert message={ctrl.pollError} />
{/if}

{#if ctrl.loading}
  <div class="grid min-h-80 place-items-center rounded-md border bg-card">
    <InlineLoading label="Loading metrics…" />
  </div>
{:else if !ctrl.available}
  <InlineEmptyState message="Metrics collector is not available" class="min-h-80 justify-center">
    {#snippet icon()}
      <Server size={34} />
    {/snippet}
  </InlineEmptyState>
{:else}
  <div class="grid gap-4">
    <MetricsProcessSection {ctrl} />
    <MetricsChannelPluginsSection {ctrl} />
    <MetricsIoSection {ctrl} />
    <MetricsSystemSection {ctrl} />
  </div>
{/if}
