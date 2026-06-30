<script lang="ts">
  /**
   * Bespoke knowledge-embedder block for the Indexing Options card: heading + "locked while indexed"
   * badge + model picker + inline download. Referenced from the manifest as the `knowledgeEmbedder`
   * custom field (mirrors `graphEmbedder` for the knowledge override paths).
   */
  import Badge from '$lib/components/ui/badge.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import PrefEmbedderDownload from '$lib/features/preferences/widgets/PrefEmbedderDownload.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';

  let { ctrl }: { ctrl: PreferencesController } = $props();
</script>

{#if ctrl.draft}
  <div class="grid gap-2">
    <h4
      class="inline-flex items-center gap-1.5 font-sans text-base font-semibold leading-snug text-foreground"
    >
      Knowledge embedder
      {#if ctrl.draft.knowledge.default_embedding_model_locked}
        <Badge variant="outline">Locked while indexed</Badge>
      {/if}
    </h4>
    <PrefModelPicker
      {ctrl}
      kind="embedding"
      path="knowledge.default_embedding_model"
      embedded
      emptyFallbackId={ctrl.draft.llm.default_embedder}
      busy={ctrl.busy || Boolean(ctrl.draft.knowledge.default_embedding_model_locked)}
    />
    <PrefEmbedderDownload {ctrl} modelId={ctrl.draft.knowledge.default_embedding_model} />
  </div>
{/if}
