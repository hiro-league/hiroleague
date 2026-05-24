<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { Plus, UserRound } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminRecordTabChip from '$lib/components/page/AdminRecordTabChip.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import Button from '$lib/components/ui/button.svelte';
  import CharactersBrowseSection from '$lib/features/characters/CharactersBrowseSection.svelte';
  import CharacterEditToolbar from '$lib/features/characters/CharacterEditToolbar.svelte';
  import CharacterExtrasSection from '$lib/features/characters/CharacterExtrasSection.svelte';
  import CharacterPreferredModelsSection from '$lib/features/characters/CharacterPreferredModelsSection.svelte';
  import CharacterPhotoCropModal from '$lib/features/characters/CharacterPhotoCropModal.svelte';
  import CharacterProfileSection from '$lib/features/characters/CharacterProfileSection.svelte';
  import CharacterPromptsSection from '$lib/features/characters/CharacterPromptsSection.svelte';
  import CharacterTtsSettingsSection from '$lib/features/characters/CharacterTtsSettingsSection.svelte';
  import CharacterViewPanel from '$lib/features/characters/CharacterViewPanel.svelte';
  import { createCharactersFormModel } from '$lib/features/characters/characters-form.svelte';
  import { createCharactersPageController } from '$lib/features/characters/characters-controller.svelte';
  import { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import { createCharactersPreferences } from '$lib/preferences/characters-preferences.svelte';
  import type { CharactersTabPreference } from '$lib/preferences/keys';

  const prefs = createCharactersPreferences();
  const toasts = createToastNotifier();
  const notify = toasts.notify;

  const formApi = createCharactersFormModel();

  const unsaved = createUnsavedGuard(
    () => formApi.dirty,
    () => prefs.detailMode === 'edit',
    (next) => {
      formApi.dirty = next;
    }
  );

  /** Remote list/detail/catalog + destructive actions wired to prefs + draft formModel. */
  const ctrl = createCharactersPageController({
    prefs,
    formApi,
    notify,
    confirmDiscard: unsaved.confirmDiscard
  });

  const detailVisible = $derived(prefs.activeTab === 'detail');
  const isNew = $derived(detailVisible && prefs.detailMode === 'edit' && !prefs.characterId);

  const detailTabLabel = $derived(
    isNew ? 'New character' : ctrl.selected?.name?.trim() || prefs.characterId || 'Detail'
  );

  const editToolbarTitle = $derived(prefs.characterId ? 'Edit character' : 'New character');

  const editCharacterDisplayLine = $derived.by(() => {
    if (!prefs.characterId) return '';
    const n = formApi.form.name.trim() || ctrl.selected?.name?.trim() || '';
    return n || prefs.characterId;
  });

  const fixedTabs: readonly AdminTabDescriptor<CharactersTabPreference>[] = [
    { id: 'browse', label: 'Browse', kind: 'pane' }
  ];

  onMount(async () => {
    await ctrl.hydrateCharactersFromUrl();
  });

  afterNavigate(({ to }) => {
    if (!to || !ctrl.isCharactersPath(to.url.pathname)) return;
    if (ctrl.charactersUrlHasDetailParams(to.url.searchParams)) return;
    void ctrl.hydrateCharactersFromUrl();
  });
</script>

<AdminPageHeader
  kicker="Configuration"
  title="Characters"
  sticky
  wrapperClass={detailVisible && prefs.detailMode === 'edit'
    ? 'grid max-w-[1420px] gap-3'
    : 'grid max-w-[1420px] gap-5'}
>
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Characters sections"
      tabs={fixedTabs}
      active={prefs.activeTab}
      onSelect={() => void ctrl.openBrowse()}
    >
      {#snippet recordTab()}
        {#if detailVisible}
          <AdminRecordTabChip
            label={detailTabLabel}
            active
            icon={UserRound}
            closeLabel="Close character and return to Browse"
            onClose={() => void ctrl.openBrowse()}
          />
        {/if}
      {/snippet}
    </AdminTabStrip>
  {/snippet}

  {#snippet actions()}
    <Button onclick={() => void ctrl.openNewCharacter()}>
      <Plus size={16} /> New character
    </Button>
  {/snippet}

  {#if prefs.activeTab === 'browse'}
    <CharactersBrowseSection
      rows={ctrl.rows}
      loadingList={ctrl.loadingList}
      listError={ctrl.listError}
      onRefresh={() => ctrl.loadCharacters()}
      onEditCharacter={(row) => void ctrl.openCharacterEdit(row)}
    />
  {:else if prefs.detailMode === 'view'}
    <CharacterViewPanel
      loadingDetail={ctrl.loadingDetail}
      detailError={ctrl.detailError}
      selected={ctrl.selected}
      resolved={ctrl.resolved}
      resolvedError={ctrl.resolvedError}
      onOpenBrowse={() => void ctrl.openBrowse()}
      onEnterEdit={() => void ctrl.enterEditMode()}
    />
  {:else}
    <section class="rounded-lg border bg-card shadow-sm">
      <CharacterEditToolbar
        title={editToolbarTitle}
        characterId={prefs.characterId}
        editCharacterDisplayLine={editCharacterDisplayLine}
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
          <InlineDestructiveAlert
            title="Could not load character"
            message={ctrl.detailError}
          />
        {:else}
          <div class="grid gap-8">
            <CharacterProfileSection
              form={formApi.form}
              characterId={prefs.characterId}
              selected={ctrl.selected}
              markDirty={formApi.markDirty}
              onPickPhoto={(e) => void ctrl.pickPhoto(e)}
            />

            <CharacterPreferredModelsSection
              variant="llm"
              form={formApi.form}
              characterId={prefs.characterId}
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
              onDuplicateAttempt={() =>
                notify('warning', 'That model is already in the list.')
              }
              markDirty={formApi.markDirty}
            />

            <CharacterPreferredModelsSection
              variant="voice"
              form={formApi.form}
              characterId={prefs.characterId}
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
              onDuplicateAttempt={() =>
                notify('warning', 'That model is already in the list.')
              }
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
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />

<Dialog.Root
  open={ctrl.deleteOpen}
  onOpenChange={(next) => {
    if (!next && !ctrl.busy) ctrl.deleteOpen = false;
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Delete '{prefs.characterId}'?</Dialog.Title>
      <Dialog.Description>This removes the character folder and index row.</Dialog.Description>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">This action cannot be undone.</p>
    <Dialog.Footer>
      <Button variant="outline" disabled={ctrl.busy} onclick={() => (ctrl.deleteOpen = false)}>Cancel</Button>
      <Button variant="destructive" disabled={ctrl.busy} onclick={() => void ctrl.confirmDelete()}>Delete</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<CharacterPhotoCropModal
  open={ctrl.cropOpen}
  busy={ctrl.busy}
  cropZoom={ctrl.cropZoom}
  cropX={ctrl.cropX}
  cropY={ctrl.cropY}
  onDismiss={() => ctrl.dismissCropModal()}
  onCropZoomChange={ctrl.handleCropZoom}
  onCropXChange={ctrl.handleCropPanX}
  onCropYChange={ctrl.handleCropPanY}
  onCropCanvasChange={ctrl.handleCropCanvas}
  onSubmitPhoto={() => void ctrl.submitPhoto()}
/>

<Dialog.Root
  open={unsaved.unsavedModalOpen}
  onOpenChange={(next) => { if (!next) unsaved.closeUnsavedModalContinueEditing(); }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Unsaved changes</Dialog.Title>
      <Dialog.Description>You have edits that are not saved yet.</Dialog.Description>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">
      Discard them and leave, or stay on this page to keep editing.
    </p>
    <Dialog.Footer>
      <Button variant="outline" onclick={unsaved.closeUnsavedModalContinueEditing}>Continue editing</Button>
      <Button variant="destructive" onclick={unsaved.confirmUnsavedModalDiscard}>Discard changes</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
