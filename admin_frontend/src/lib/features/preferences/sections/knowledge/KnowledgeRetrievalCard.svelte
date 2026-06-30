<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { knowledgeHybridPrefetchActive } from '$lib/features/preferences/shared/preferences-helpers';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefPanel from '$lib/features/preferences/widgets/PrefPanel.svelte';
  import PrefRerankerDownload from '$lib/features/preferences/widgets/PrefRerankerDownload.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  const hybridPrefetchActive = $derived(knowledgeHybridPrefetchActive(ctrl.draft));
  // The Enable-reranking toggle is the single gate for both the reranker model and the rerank top-N.
  const rerankerEnabled = $derived(Boolean(ctrl.draft?.knowledge.retrieval.reranker.enabled));
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Retrieval defaults"
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeRetrieval}
  >
    <PrefFieldGrid>
      <PrefToggleField
        {ctrl}
        path="knowledge.retrieval.hybrid"
        hint="Runs BM25 keyword search alongside dense embeddings and fuses them with Reciprocal Rank Fusion — recovers exact terms, proper nouns, and Arabic surface forms. Sparse model: Qdrant/bm25 (local, no extra setup)."
        bind:checked={ctrl.draft.knowledge.retrieval.hybrid}
      />
      <PrefNumberField
        {ctrl}
        path="knowledge.retrieval.min_score"
        bind:value={ctrl.draft.knowledge.retrieval.min_score}
      />
    </PrefFieldGrid>
    <PrefFieldGrid>
      <div class={cn(!hybridPrefetchActive && 'opacity-50')}>
        <PrefNumberField
          {ctrl}
          path="knowledge.retrieval.prefetch_limit"
          disabled={ctrl.busy || !hybridPrefetchActive}
          bind:value={ctrl.draft.knowledge.retrieval.prefetch_limit}
        />
      </div>
      <PrefNumberField
        {ctrl}
        path="knowledge.retrieval.top_k"
        bind:value={ctrl.draft.knowledge.retrieval.top_k}
      />
    </PrefFieldGrid>

    <!-- Reranker (moved in from its own card): cross-encoder that reorders candidates. The single
         Enable toggle gates both the model picker and the rerank top-N. -->
    <PrefPanel
      {ctrl}
      title="Reranker"
      hint="Optional cross-encoder that reorders retrieved candidates by relevance before answering (precision step). Cloud models need a provider key; local models must be downloaded first. Switching is a hot swap — no re-ingest."
    >
      <PrefFieldGrid>
        <PrefToggleField
          {ctrl}
          path="knowledge.retrieval.reranker.enabled"
          hint="Cloud scores are calibrated [0,1]; local cross-encoder scores are sigmoid-normalized. A normalized relevance is emitted whether reranking is on (reranker score) or off (retrieval rank), so downstream ranking stays consistent."
          bind:checked={ctrl.draft.knowledge.retrieval.reranker.enabled}
        />
        <div class={cn(!rerankerEnabled && 'opacity-50')}>
          <div class="grid gap-2">
            <PrefModelPicker
              {ctrl}
              kind="rerank"
              path="knowledge.retrieval.reranker.model_id"
              embedded
              selectedId={ctrl.draft.knowledge.retrieval.reranker.model_id}
              emptyFallbackId={ctrl.draft.llm.default_reranker}
              busy={ctrl.busy || !rerankerEnabled}
            />
            {#if ctrl.draft.knowledge.retrieval.reranker.model_id}
              <PrefRerankerDownload
                {ctrl}
                modelId={ctrl.draft.knowledge.retrieval.reranker.model_id}
              />
            {/if}
          </div>
        </div>
        <div class={cn(!rerankerEnabled && 'opacity-50')}>
          <PrefNumberField
            {ctrl}
            path="knowledge.retrieval.reranker.top_n"
            disabled={ctrl.busy || !rerankerEnabled}
            bind:value={ctrl.draft.knowledge.retrieval.reranker.top_n}
          />
        </div>
      </PrefFieldGrid>
    </PrefPanel>
  </PrefSectionCard>
{/if}
