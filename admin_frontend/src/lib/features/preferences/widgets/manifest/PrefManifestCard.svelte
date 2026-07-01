<script lang="ts">
  /**
   * Renders one `PrefCardSpec` as a `PrefSectionCard` wrapping its manifest fields. An optional
   * card-level `validate` (cross-field error registered via `ctrl.setSectionError`, so it gates Save)
   * covers the one cross-field concern the field specs can't express — see the retrieval-agent card in
   * graph-engine-manifest.ts. Whole-card gating uses a `gated` FIELD spec around the body (the reranker
   * card), rendered by `PrefFieldRenderer` like any other field.
   */
  import type { WorkspacePreferences } from '$lib/api/preferences';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import type { PrefCardSpec } from './manifest-types';
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import PrefFieldRenderer from './PrefFieldRenderer.svelte';

  let { ctrl, card }: { ctrl: PreferencesController; card: PrefCardSpec } = $props();

  // The card renders under a `{#if ctrl.draft}` guard at the section level, so draft is present here.
  const draft = $derived(ctrl.draft as WorkspacePreferences);

  const validationError = $derived(card.validate ? card.validate(draft) : null);

  // Register the cross-field error (gating Save), and CLEAR it on unmount — otherwise a stale error
  // sticks in `sectionErrors` after the user navigates away from an invalid card (tabs unmount their
  // section), leaving Save disabled everywhere with no visible cause.
  $effect(() => {
    if (!card.validate) return;
    ctrl.setSectionError(card.id, validationError);
    return () => ctrl.setSectionError(card.id, null);
  });
</script>

<PrefSectionCard
  title={card.title}
  description={card.descriptionOf ? card.descriptionOf(ctrl) : card.description}
  collapsible={card.collapsible ?? false}
  bodyId={card.bodyId}
>
  {#each card.body as field, i (i)}
    <PrefFieldRenderer {ctrl} spec={field} />
  {/each}

  {#if validationError}
    <p class="text-xs text-destructive">{validationError}</p>
  {/if}
</PrefSectionCard>
