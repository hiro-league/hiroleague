<script lang="ts">
  import MetricCard from '$lib/components/page/MetricCard.svelte';
  import Sparkline from '../shared/Sparkline.svelte';
  import type { MetricsCardSpec } from '../shared/metrics-card-config';
  import { frameString } from '../shared/metrics-display';
  import type { MetricsController } from '../state/metrics-controller.svelte';

  type Props = {
    ctrl: MetricsController;
    cards: readonly MetricsCardSpec[];
    class?: string;
  };

  let { ctrl, cards, class: className = 'grid gap-4 lg:grid-cols-3' }: Props = $props();
</script>

<div class={className}>
  {#each cards as card (card.id)}
    <MetricCard
      title={card.title}
      icon={card.icon}
      value={frameString(ctrl.frame, card.valueKey)}
      caption={card.staticCaption ?? frameString(ctrl.frame, card.captionKey)}
      detail={card.detailKey ? frameString(ctrl.frame, card.detailKey) : undefined}
      nested={card.nested}
    >
      {#snippet children()}
        <Sparkline
          series={card.sparklines.map((line) => ({
            label: line.label,
            color: line.color,
            data: ctrl.chartSeriesFor(line.seriesKey)
          }))}
          yMax={card.yMax ?? null}
        />
      {/snippet}
    </MetricCard>
  {/each}
</div>
