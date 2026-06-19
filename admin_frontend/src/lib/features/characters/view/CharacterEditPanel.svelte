<script lang="ts">
  import CharacterEditToolbar from '$lib/features/characters/view/CharacterEditToolbar.svelte';
  import CharacterProfileSection from '$lib/features/characters/sections/CharacterProfileSection.svelte';
  import CharacterPreferredModelsSection from '$lib/features/characters/sections/CharacterPreferredModelsSection.svelte';
  import CharacterTtsSettingsSection from '$lib/features/characters/sections/CharacterTtsSettingsSection.svelte';
  import CharacterPromptsSection from '$lib/features/characters/sections/CharacterPromptsSection.svelte';
  import CharacterExtrasSection from '$lib/features/characters/sections/CharacterExtrasSection.svelte';
  import type { createCharactersPageController } from '$lib/features/characters/state/characters-controller.svelte';
  import type { createCharactersFormModel } from '$lib/features/characters/state/characters-form.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';

  let {
    ctrl,
    formApi,
    characterId,
    notify
  }: {
    ctrl: ReturnType<typeof createCharactersPageController>;
    formApi: ReturnType<typeof createCharactersFormModel>;
    characterId: string | null;
    notify: (kind: 'success' | 'error' | 'info' | 'warning', message: string) => void;
  } = $props();

  const editToolbarTitle = $derived(characterId ? 'Edit character' : 'New character');

  const editCharacterDisplayLine = $derived.by(() => {
    if (!characterId) return '';
    const n = formApi.form.name.trim() || ctrl.selected?.name?.trim() || '';
    return n || characterId;
  });
</script>

<section class="rounded-lg border bg-card shadow-sm">
  <CharacterEditToolbar
    title={editToolbarTitle}
    {characterId}
    {editCharacterDisplayLine}
    selected={ctrl.selected}
    dirty={formApi.dirty}
    busy={ctrl.busy}
    onDeleteClick={() => (ctrl.deleteOpen = true)}
    onCancel={() => void ctrl.cancelEdit()}
    onSave={() => void ctrl.saveCharacter()}
  />

  <div class="grid gap-5 px-4 pb-5 pt-3 md:px-5">
    {#if ctrl.loadingDetail}
      <InlineLoading label="Loading character…" />
    {:else if ctrl.detailError}
      <InlineDestructiveAlert title="Could not load character" message={ctrl.detailError} />
    {:else}
      <div class="grid gap-8">
        <CharacterProfileSection
          form={formApi.form}
          {characterId}
          selected={ctrl.selected}
          markDirty={formApi.markDirty}
          onPickPhoto={(e) => void ctrl.photoCrop.pickPhoto(e)}
        />

        <CharacterPreferredModelsSection
          variant="llm"
          form={formApi.form}
          {characterId}
          catalogModels={ctrl.llmOptions}
          catalogAllProviders={ctrl.catalogAllProviders}
          workspaceResolved={ctrl.workspaceActiveProvidersResolved}
          workspaceActiveIds={ctrl.workspaceChatActiveIds}
          busy={ctrl.busy}
          catalogReloadBusy={ctrl.catalogReloadBusy}
          modelPickerResetNonce={formApi.modelPickerResetNonce}
          resolved={ctrl.resolved}
          resolvedError={ctrl.resolvedError}
          tuningProfiles={ctrl.tuningProfiles}
          workspaceDefaultTuningProfile={ctrl.workspaceDefaultTuningProfile}
          dirty={formApi.dirty}
          onReloadCatalog={() => void ctrl.reloadBundledCatalogInEditor()}
          onDuplicateAttempt={() => notify('warning', 'That model is already in the list.')}
          markDirty={formApi.markDirty}
        />

        <CharacterPreferredModelsSection
          variant="voice"
          form={formApi.form}
          {characterId}
          catalogModels={ctrl.voiceOptions}
          catalogAllProviders={ctrl.catalogAllProviders}
          workspaceResolved={ctrl.workspaceActiveProvidersResolved}
          workspaceActiveIds={ctrl.workspaceTtsActiveIds}
          busy={ctrl.busy}
          catalogReloadBusy={ctrl.catalogReloadBusy}
          modelPickerResetNonce={formApi.modelPickerResetNonce}
          resolved={ctrl.resolved}
          resolvedError={ctrl.resolvedError}
          dirty={formApi.dirty}
          onReloadCatalog={() => void ctrl.reloadBundledCatalogInEditor()}
          onDuplicateAttempt={() => notify('warning', 'That model is already in the list.')}
          markDirty={formApi.markDirty}
        />

        <CharacterTtsSettingsSection
          form={formApi.form}
          catalogTtsProviders={ctrl.catalogTtsProviders}
          google={ctrl.ttsPresetGoogle}
          openai={ctrl.ttsPresetOpenai}
          others={ctrl.ttsPresetOtherProviders}
          onPickVoicePreset={(pid, vid) => ctrl.setTtsVoicePreset(pid, vid)}
          markDirty={formApi.markDirty}
        />

        <CharacterPromptsSection form={formApi.form} markDirty={formApi.markDirty} />

        <CharacterExtrasSection form={formApi.form} markDirty={formApi.markDirty} />
      </div>
    {/if}
  </div>
</section>
