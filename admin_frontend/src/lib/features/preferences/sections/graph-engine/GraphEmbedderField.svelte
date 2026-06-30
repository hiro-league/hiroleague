<script lang="ts">
  /**
   * Bespoke embedder block for the Graph Extraction card: heading + "locked while indexed" badge +
   * model picker + inline download affordance. Referenced from the manifest as the `graphEmbedder`
   * custom field (the lock/download logic is too specific for a generic widget).
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
      Embedder model
      {#if ctrl.draft.graph.embedder_model_locked}
        <Badge variant="outline">Locked while indexed</Badge>
      {/if}
    </h4>
    <PrefModelPicker
      {ctrl}
      kind="embedding"
      path="graph.embedder_model"
      embedded
      emptyFallbackId={ctrl.draft.llm.default_embedder}
      busy={ctrl.busy || Boolean(ctrl.draft.graph.embedder_model_locked)}
    />
    <PrefEmbedderDownload {ctrl} modelId={ctrl.draft.graph.embedder_model} />
  </div>
{/if}
