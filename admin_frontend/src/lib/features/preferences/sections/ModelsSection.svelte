<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCE_SECTION_SCROLL_MT, ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import ReloadCatalogButton from '$lib/features/preferences/widgets/ReloadCatalogButton.svelte';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<section id="preferences-models" class="{PREFERENCE_SECTION_SCROLL_MT} grid gap-4 border-b pb-6">
  <div>
    <h3 class="font-sans text-xl font-semibold text-foreground">
      {ctrl.sectionLabel('llm', 'Models')}
    </h3>
    <p class="mt-1 text-sm text-muted-foreground">{ctrl.sectionDescription('llm')}</p>
  </div>

  {#if ctrl.draft}
    <SingleModelPicker
      label="Default chat model"
      hint="Used when a character has no available preferred chat model."
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
    >
      {#snippet toolbar()}
        <ReloadCatalogButton
          busy={ctrl.busy}
          catalogReloadBusy={ctrl.catalogReloadBusy}
          onReload={() => void ctrl.reloadCatalog()}
        />
      {/snippet}
    </SingleModelPicker>

    <SingleModelPicker
      label="Default speech-to-text model"
      hint="Used for voice input transcription when voice input is enabled."
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
    >
      {#snippet toolbar()}
        <ReloadCatalogButton
          busy={ctrl.busy}
          catalogReloadBusy={ctrl.catalogReloadBusy}
          onReload={() => void ctrl.reloadCatalog()}
        />
      {/snippet}
    </SingleModelPicker>

    <SingleModelPicker
      label="Default text-to-speech model"
      hint="Used as the voice reply fallback when a character has no available TTS model."
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

    <FormField label="Default chat tuning profile" class="max-w-md">
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
  {/if}
</section>
