<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import ReloadCatalogButton from '$lib/features/preferences/widgets/ReloadCatalogButton.svelte';
  import ActiveProvidersLink from '$lib/features/preferences/widgets/ActiveProvidersLink.svelte';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';

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
      <SingleModelPicker
        embedded
        label="Default chat model"
        hint=""
        selectedId={ctrl.draft.llm.default_chat}
        catalogModels={ctrl.chatOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.chatActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No chat providers in catalog."
        emptyModelsForProvider="No chat models for this provider."
        onSelect={(id) => ctrl.setDefaultModel('default_chat', id)}
        onChange={ctrl.markDirty}
      />
      <FormField label="Default chat model profile" class="max-w-md">
        <select
          class={ADMIN_SELECT_LG}
          value={ctrl.draft.llm.default_tuning_profile}
          onchange={(event) => ctrl.setDefaultTuningProfile('llm', event.currentTarget.value)}
        >
          {#each ctrl.profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
      </FormField>
    </SectionCardMuted>

    <SectionCardMuted
      title="Default speech-to-text model"
      description="Used for voice input transcription when voice input is enabled."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.modelsStt}
    >
      <SingleModelPicker
        embedded
        label="Default speech-to-text model"
        hint=""
        selectedId={ctrl.draft.llm.default_stt}
        catalogModels={ctrl.sttOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.sttActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No speech-to-text providers in catalog."
        emptyModelsForProvider="No speech-to-text models for this provider."
        onSelect={(id) => ctrl.setDefaultModel('default_stt', id)}
        onChange={ctrl.markDirty}
      />
    </SectionCardMuted>

    <SectionCardMuted
      title="Default text-to-speech model"
      description="Used as the voice reply fallback when a character has no available TTS model."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.modelsTts}
    >
      <SingleModelPicker
        embedded
        label="Default text-to-speech model"
        hint=""
        selectedId={ctrl.draft.llm.default_tts}
        catalogModels={ctrl.ttsOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.ttsActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No text-to-speech providers in catalog."
        emptyModelsForProvider="No text-to-speech models for this provider."
        onSelect={(id) => ctrl.setDefaultModel('default_tts', id)}
        onChange={ctrl.markDirty}
      />
    </SectionCardMuted>
  {/if}
</div>
