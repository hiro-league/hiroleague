<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefRerankerDownload from '$lib/features/preferences/widgets/PrefRerankerDownload.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Reranker"
    description="Optional cross-encoder that reorders retrieved candidates by relevance before answering (precision step). Default off. Cloud models need a provider key; local models must be downloaded first. Switching is a hot swap — no re-ingest."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeReranker}
  >
    <PrefToggleField
      {ctrl}
      path="knowledge.retrieval.reranker.enabled"
      label="Enable reranking"
      bind:checked={ctrl.draft.knowledge.retrieval.reranker.enabled}
    />
    <PrefModelPicker
      {ctrl}
      kind="rerank"
      path="knowledge.retrieval.reranker.model_id"
      embedded
      label="Reranker model"
      selectedId={ctrl.draft.knowledge.retrieval.reranker.model_id}
      emptyFallbackId={ctrl.draft.llm.default_reranker}
    />

    {#if ctrl.draft.knowledge.retrieval.reranker.model_id}
      <PrefRerankerDownload {ctrl} modelId={ctrl.draft.knowledge.retrieval.reranker.model_id} />
    {/if}

    <p class="text-xs text-muted-foreground">
      Cloud scores are calibrated <code>[0,1]</code>; local cross-encoder scores are
      sigmoid-normalized. A normalized <code>relevance</code> is emitted whether reranking is on
      (reranker score) or off (retrieval rank), so downstream ranking stays consistent.
    </p>
  </PrefSectionCard>
{/if}
