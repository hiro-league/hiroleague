<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    knowledgeHybridPrefetchActive,
    knowledgeRerankTopNActive
  } from '$lib/features/preferences/shared/preferences-helpers';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import SettingToggle from '$lib/features/preferences/widgets/SettingToggle.svelte';
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
    <SettingToggle
      label="Hybrid retrieval (dense + BM25, RRF fusion)"
      bind:checked={ctrl.draft.knowledge.retrieval.hybrid}
      onchange={ctrl.markDirty}
    />
    <p class="text-xs text-muted-foreground">
      Runs BM25 keyword search alongside dense embeddings and fuses them with Reciprocal Rank
      Fusion — recovers exact terms, proper nouns, and Arabic surface forms. Sparse model:
      <code>{ctrl.draft.knowledge.retrieval.sparse_model}</code> (local, no extra setup).
    </p>
    <div class="grid gap-3">
      <label class="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span class="w-60 shrink-0 font-sans text-sm font-semibold text-muted-foreground"
          >Minimum score (Dense only)</span
        >
        <input
          type="number"
          min="0"
          max="1"
          step="0.05"
          class="{ADMIN_SELECT_LG} w-28 shrink-0"
          bind:value={ctrl.draft.knowledge.retrieval.min_score}
          oninput={ctrl.markDirty}
        />
        <span class="min-w-0 flex-1 font-sans text-xs text-muted-foreground"
          >Applies only to dense (Vector search) branch</span
        >
      </label>
      <label
        class={cn(
          'flex flex-wrap items-center gap-x-3 gap-y-2',
          !hybridPrefetchActive && 'opacity-50'
        )}
      >
        <span class="w-60 shrink-0 font-sans text-sm font-semibold text-muted-foreground"
          >Candidates per branch</span
        >
        <input
          type="number"
          min="1"
          max="500"
          class="{ADMIN_SELECT_LG} w-28 shrink-0"
          bind:value={ctrl.draft.knowledge.retrieval.prefetch_limit}
          disabled={ctrl.busy || !hybridPrefetchActive}
          oninput={ctrl.markDirty}
        />
        <span class="min-w-0 flex-1 font-sans text-xs text-muted-foreground"
          >Results to return for dense(Vector) or sparse(BM25) separately, before RRF fusion
          (Hybrid Only)</span
        >
      </label>
      <label class="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span class="w-60 shrink-0 font-sans text-sm font-semibold text-muted-foreground"
          >Search/fused results (top K)</span
        >
        <input
          type="number"
          min="1"
          max="100"
          class="{ADMIN_SELECT_LG} w-28 shrink-0"
          bind:value={ctrl.draft.knowledge.retrieval.top_k}
          oninput={ctrl.markDirty}
        />
        <span class="min-w-0 flex-1 font-sans text-xs text-muted-foreground"
          >Fused results from hybrid search or direct results from dense only search (after applying
          minimum score)</span
        >
      </label>
      <label
        class={cn('flex flex-wrap items-center gap-x-3 gap-y-2', !rerankTopNActive && 'opacity-50')}
      >
        <span class="w-60 shrink-0 font-sans text-sm font-semibold text-muted-foreground"
          >Rerank results (top N)</span
        >
        <input
          type="number"
          min="1"
          max="100"
          class="{ADMIN_SELECT_LG} w-28 shrink-0"
          bind:value={ctrl.draft.knowledge.retrieval.reranker.top_n}
          disabled={ctrl.busy || !rerankTopNActive}
          oninput={ctrl.markDirty}
        />
        <span class="min-w-0 flex-1 font-sans text-xs text-muted-foreground"
          >Final returned results if using rerank (top N)</span
        >
      </label>
    </div>
  </SectionCardMuted>
{/if}
