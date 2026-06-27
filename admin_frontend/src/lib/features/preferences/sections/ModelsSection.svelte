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
  import ReloadCatalogButton from '$lib/features/preferences/widgets/ReloadCatalogButton.svelte';
  import ActiveProvidersLink from '$lib/features/preferences/widgets/ActiveProvidersLink.svelte';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS.models}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.models}
>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    {#if ctrl.sectionDescription('llm')}
      <p class="min-w-0 flex-1 text-sm text-muted-foreground">{ctrl.sectionDescription('llm')}</p>
    {/if}
    <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
      <ReloadCatalogButton
        busy={ctrl.busy}
        catalogReloadBusy={ctrl.catalogReloadBusy}
        onReload={() => void ctrl.reloadCatalog()}
      />
      <ActiveProvidersLink busy={ctrl.busy} />
    </div>
  </div>

  {#if ctrl.draft}
    <SectionCardMuted
      title="Default chat model"
      description="Used when a character has no available preferred chat model."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.modelsChat}
    >
      <PrefFieldGrid>
        <div class="grid gap-3">
          <PrefModelPicker
            {ctrl}
            kind="chat"
            path="llm.default_chat"
            embedded
            label="Default chat model"
            selectedId={ctrl.draft.llm.default_chat}
          />
          <TuningProfileSelect
            {ctrl}
            label="Default chat model profile"
            value={ctrl.draft.llm.default_tuning_profile}
            scope="llm"
          />
        </div>
      </PrefFieldGrid>
    </SectionCardMuted>

    <SectionCardMuted
      title="Default speech-to-text model"
      description="Used for voice input transcription when voice input is enabled."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.modelsStt}
    >
      <PrefModelPicker
        {ctrl}
        kind="stt"
        path="llm.default_stt"
        embedded
        label="Default speech-to-text model"
        selectedId={ctrl.draft.llm.default_stt}
      />
    </SectionCardMuted>

    <SectionCardMuted
      title="Default text-to-speech model"
      description="Used as the voice reply fallback when a character has no available TTS model."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.modelsTts}
    >
      <PrefModelPicker
        {ctrl}
        kind="tts"
        path="llm.default_tts"
        embedded
        label="Default text-to-speech model"
        selectedId={ctrl.draft.llm.default_tts}
      />
    </SectionCardMuted>

    <!-- Media modalities — merged in from the former standalone Media tab. -->
    {#if ctrl.sectionDescription('media')}
      <p class="text-sm text-muted-foreground">{ctrl.sectionDescription('media')}</p>
    {/if}

    <div class="grid gap-4 lg:grid-cols-2">
      <SectionCardMuted
        title="Input modalities"
        collapsible
        bodyId={PREFERENCES_SECTION_BODY_IDS.mediaInput}
      >
        <PrefFieldGrid>
          {#each modalityKeys as key (key)}
            <PrefToggleField
              {ctrl}
              path={`media.input.${key}`}
              label={modalityLabels[key]}
              bind:checked={ctrl.draft.media.input[key]}
            />
          {/each}
        </PrefFieldGrid>
      </SectionCardMuted>

      <SectionCardMuted
        title="Output modalities"
        collapsible
        bodyId={PREFERENCES_SECTION_BODY_IDS.mediaOutput}
      >
        <PrefFieldGrid>
          {#each modalityKeys as key (key)}
            <PrefToggleField
              {ctrl}
              path={`media.output.${key}`}
              label={modalityLabels[key]}
              bind:checked={ctrl.draft.media.output[key]}
            />
          {/each}
        </PrefFieldGrid>
      </SectionCardMuted>
    </div>
  {/if}
</div>
