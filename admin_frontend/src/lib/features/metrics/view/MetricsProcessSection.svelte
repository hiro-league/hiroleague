<script lang="ts">
  import { METRICS_PROCESS_CARDS } from '../shared/metrics-card-config';
  import type { MetricsController } from '../state/metrics-controller.svelte';
  import MetricsCardsGrid from './MetricsCardsGrid.svelte';

  type Props = {
    ctrl: MetricsController;
  };

  let { ctrl }: Props = $props();
</script>

<MetricsCardsGrid {ctrl} cards={METRICS_PROCESS_CARDS} class="grid gap-4 lg:grid-cols-3" />
