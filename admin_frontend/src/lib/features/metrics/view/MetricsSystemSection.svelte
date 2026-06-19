<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import { METRICS_SYSTEM_CARDS } from '../shared/metrics-card-config';
  import { METRICS_SYSTEM_SECTION_ID } from '../shared/metrics-a11y';
  import type { MetricsController } from '../state/metrics-controller.svelte';
  import MetricsCardsGrid from './MetricsCardsGrid.svelte';

  type Props = {
    ctrl: MetricsController;
  };

  let { ctrl }: Props = $props();
</script>

<SectionCardMuted
  title="System-wide"
  collapsible
  defaultExpanded={false}
  bodyId={METRICS_SYSTEM_SECTION_ID}
>
  <MetricsCardsGrid {ctrl} cards={METRICS_SYSTEM_CARDS} class="grid gap-4 lg:grid-cols-2" />
</SectionCardMuted>
