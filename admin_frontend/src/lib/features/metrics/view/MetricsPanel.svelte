<script lang="ts">
  import { Server } from '@lucide/svelte';
  import Notice from '$kit/ui/notice.svelte';
  import EmptyState from '$kit/ui/empty-state.svelte';
  import Loading from '$kit/ui/loading.svelte';
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
  <Notice message={ctrl.error} />
{:else if ctrl.pollError}
  <Notice tone="warning" message={ctrl.pollError} />
{/if}

{#if ctrl.loading}
  <div class="grid min-h-80 place-items-center rounded-md border bg-card">
    <Loading label="Loading metrics…" />
  </div>
{:else if !ctrl.available}
  <EmptyState message="Metrics collector is not available" class="min-h-80 justify-center">
    {#snippet icon()}
      <Server size={34} />
    {/snippet}
  </EmptyState>
{:else}
  <div class="grid gap-4">
    <MetricsProcessSection {ctrl} />
    <MetricsChannelPluginsSection {ctrl} />
    <MetricsIoSection {ctrl} />
    <MetricsSystemSection {ctrl} />
  </div>
{/if}
