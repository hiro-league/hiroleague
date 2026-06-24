<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    modalityKeys,
    modalityLabels
  } from '$lib/features/preferences/shared/preferences-constants';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS.media}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.media}
>
  {#if ctrl.sectionDescription('media')}
    <p class="text-sm text-muted-foreground">{ctrl.sectionDescription('media')}</p>
  {/if}

  {#if ctrl.draft}
    <div class="grid gap-4 lg:grid-cols-2">
      <SectionCardMuted
        title="Input modalities"
        collapsible
        bodyId={PREFERENCES_SECTION_BODY_IDS.mediaInput}
      >
        {#each modalityKeys as key (key)}
          <PrefToggleField
            {ctrl}
            path={`media.input.${key}`}
            label={modalityLabels[key]}
            bind:checked={ctrl.draft.media.input[key]}
          />
        {/each}
      </SectionCardMuted>

      <SectionCardMuted
        title="Output modalities"
        collapsible
        bodyId={PREFERENCES_SECTION_BODY_IDS.mediaOutput}
      >
        {#each modalityKeys as key (key)}
          <PrefToggleField
            {ctrl}
            path={`media.output.${key}`}
            label={modalityLabels[key]}
            bind:checked={ctrl.draft.media.output[key]}
          />
        {/each}
      </SectionCardMuted>
    </div>
  {/if}
</div>
