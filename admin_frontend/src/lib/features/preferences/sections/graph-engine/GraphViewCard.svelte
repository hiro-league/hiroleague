<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Graph view (display)"
    description="Display-only settings for the shared Knowledge / Memories Graph tab. These tune the in-browser graph view and do not affect extraction, search, or retrieval."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphView}
  >
    <PrefNumberField
      {ctrl}
      path="graph.view.large_type_threshold"
      label="Large node-type warning threshold"
      class="max-w-md"
      bind:value={ctrl.draft.graph.view.large_type_threshold}
    />
  </SectionCardMuted>
{/if}
