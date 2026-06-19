<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { GRAPH_VIEW_COPY } from '$lib/features/preferences/shared/preferences-copy';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

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
    <FormField
      label="Large node-type warning threshold"
      hint={GRAPH_VIEW_COPY.largeTypeThreshold}
      class="max-w-md"
    >
      <input
        type="number"
        min="10"
        max="10000"
        class={ADMIN_SELECT_LG}
        bind:value={ctrl.draft.graph.view.large_type_threshold}
        oninput={ctrl.markDirty}
      />
    </FormField>
  </SectionCardMuted>
{/if}
