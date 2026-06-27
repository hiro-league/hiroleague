<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    knowledgeHybridPrefetchActive,
    knowledgeRerankTopNActive
  } from '$lib/features/preferences/shared/preferences-helpers';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  const hybridPrefetchActive = $derived(knowledgeHybridPrefetchActive(ctrl.draft));
  const rerankTopNActive = $derived(
    knowledgeRerankTopNActive(
      ctrl.draft,
      ctrl.localRerankers,
      ctrl.activeProvidersStore.resolved,
      ctrl.activeProvidersStore.rerankActiveProviderIds
    )
  );
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Retrieval defaults"
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeRetrieval}
  >
    <PrefToggleField
      {ctrl}
      path="knowledge.retrieval.hybrid"
      label="Hybrid retrieval (dense + BM25, RRF fusion)"
      bind:checked={ctrl.draft.knowledge.retrieval.hybrid}
    />
    <p class="text-xs text-muted-foreground">
      Runs BM25 keyword search alongside dense embeddings and fuses them with Reciprocal Rank
      Fusion — recovers exact terms, proper nouns, and Arabic surface forms. Sparse model:
      <code>{ctrl.draft.knowledge.retrieval.sparse_model}</code> (local, no extra setup).
    </p>
    <PrefFieldGrid>
      <PrefNumberField
        {ctrl}
        path="knowledge.retrieval.min_score"
        label="Minimum score (Dense only)"
        bind:value={ctrl.draft.knowledge.retrieval.min_score}
      />
      <PrefNumberField
        {ctrl}
        path="knowledge.retrieval.top_k"
        label="Search/fused results (top K)"
        bind:value={ctrl.draft.knowledge.retrieval.top_k}
      />
      <div class={cn(!hybridPrefetchActive && 'opacity-50')}>
        <PrefNumberField
          {ctrl}
          path="knowledge.retrieval.prefetch_limit"
          label="Candidates per branch"
          disabled={ctrl.busy || !hybridPrefetchActive}
          bind:value={ctrl.draft.knowledge.retrieval.prefetch_limit}
        />
      </div>
      <div class={cn(!rerankTopNActive && 'opacity-50')}>
        <PrefNumberField
          {ctrl}
          path="knowledge.retrieval.reranker.top_n"
          label="Rerank results (top N)"
          disabled={ctrl.busy || !rerankTopNActive}
          bind:value={ctrl.draft.knowledge.retrieval.reranker.top_n}
        />
      </div>
    </PrefFieldGrid>
  </SectionCardMuted>
{/if}
