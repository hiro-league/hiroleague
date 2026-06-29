<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Graph view (display)"
    description="Display-only settings for the shared Knowledge / Memories Graph tab. These tune the in-browser graph view and do not affect extraction, search, or retrieval."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphView}
  >
    <PrefFieldGrid>
      <PrefNumberField
        {ctrl}
        path="graph.view.large_type_threshold"
        bind:value={ctrl.draft.graph.view.large_type_threshold}
      />
    </PrefFieldGrid>
  </PrefSectionCard>
{/if}
