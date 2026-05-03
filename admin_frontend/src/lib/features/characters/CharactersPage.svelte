<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import {
    Plus,
    UserRound,
    X
  } from '@lucide/svelte';
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
  import { createCharactersUnsavedGuard } from '$lib/features/characters/characters-unsaved-guard.svelte';
  import Modal from '$lib/ui/Modal.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { createCharactersPreferences } from '$lib/preferences/characters-preferences.svelte';
  import { cn } from '$lib/utils';

  type NotifyKind = 'success' | 'error' | 'info' | 'warning';

  const prefs = createCharactersPreferences();
  let toast = $state<{ kind: NotifyKind; message: string } | null>(null);

  function notify(kind: NotifyKind, message: string) {
    toast = { kind, message };
    window.setTimeout(() => {
      toast = null;
    }, 4500);
  }

  const formApi = createCharactersFormModel();

  /** Unsaved-changes UX is owned by guard; SPA navigation interception lives beside controller boot. */
  const unsaved = createCharactersUnsavedGuard(
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

  /** Tab strip label for the Detail tab chip. */
  const detailTabLabel = $derived(
    isNew ? 'New character' : ctrl.selected?.name?.trim() || prefs.characterId || 'Detail'
  );

  const editToolbarTitle = $derived(prefs.characterId ? 'Edit character' : 'New character');

  /** Toolbar subtitle uses live editable name vs loaded row for existing IDs. */
  const editCharacterDisplayLine = $derived.by(() => {
    if (!prefs.characterId) return '';
    const n = formApi.form.name.trim() || ctrl.selected?.name?.trim() || '';
    return n || prefs.characterId;
  });

  /** Route-level hydration mirrors original mount + SPA navigation reconciliation. */
  onMount(async () => {
    await ctrl.hydrateCharactersFromUrl();
  });

  afterNavigate(({ to }) => {
    if (!to || !ctrl.isCharactersPath(to.url.pathname)) return;
    if (ctrl.charactersUrlHasDetailParams(to.url.searchParams)) return;
    void ctrl.hydrateCharactersFromUrl();
  });
</script>

<section
  class={cn(
    'grid max-w-[1420px]',
    detailVisible && prefs.detailMode === 'edit' ? 'gap-3' : 'gap-5'
  )}
>
  <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div>
      <p class="font-sans text-xs font-extrabold uppercase text-primary">Configuration</p>
      <h2 class="brand-text-gradient mt-1 text-3xl font-semibold">Characters</h2>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <div class="inline-flex rounded-lg border bg-card p-1" role="tablist" aria-label="Characters sections">
        <Button
          class={cn(
            'shadow-none',
            prefs.activeTab === 'browse' ? '' : 'bg-transparent text-muted-foreground hover:bg-secondary'
          )}
          variant={prefs.activeTab === 'browse' ? 'secondary' : 'ghost'}
          role="tab"
          aria-selected={prefs.activeTab === 'browse'}
          onclick={() => ctrl.openBrowse()}
        >
          Browse
        </Button>
        {#if detailVisible}
          <div
            class="inline-flex max-w-[min(20rem,calc(100vw-9rem))] items-center rounded-md bg-secondary text-secondary-foreground shadow-none"
            role="tab"
            aria-selected="true"
          >
            <span class="flex min-w-0 items-center gap-2 px-3 py-2 font-sans text-sm font-semibold">
              <UserRound size={15} class="shrink-0" aria-hidden="true" />
              <span class="truncate">{detailTabLabel}</span>
            </span>
            <Button
              variant="ghost"
              size="icon"
              class="size-8 shrink-0 text-muted-foreground hover:bg-transparent hover:text-foreground"
              aria-label="Close character and return to Browse"
              onclick={() => void ctrl.openBrowse()}
            >
              <X size={17} aria-hidden="true" />
            </Button>
          </div>
        {/if}
      </div>
      <Button onclick={() => void ctrl.openNewCharacter()}><Plus size={16} /> New character</Button>
    </div>
  </div>

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
          <p class="text-muted-foreground">Loading character...</p>
        {:else if ctrl.detailError}
          <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
            <strong class="font-sans">Could not load character</strong>
            <span class="block text-sm">{ctrl.detailError}</span>
          </div>
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
</section>

<ToastHost {toast} />

<Modal
  open={ctrl.deleteOpen}
  title={`Delete '${prefs.characterId}'?`}
  subtitle="This removes the character folder and index row."
  onClose={() => {
    if (!ctrl.busy) ctrl.deleteOpen = false;
  }}
>
  <p class="text-sm text-muted-foreground">This action cannot be undone.</p>
  {#snippet footer()}
    <Button variant="outline" disabled={ctrl.busy} onclick={() => (ctrl.deleteOpen = false)}>Cancel</Button>
    <Button variant="destructive" disabled={ctrl.busy} onclick={() => void ctrl.confirmDelete()}>Delete</Button>
  {/snippet}
</Modal>

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

<Modal
  open={unsaved.unsavedModalOpen}
  title="Unsaved changes"
  subtitle="You have edits that are not saved yet."
  onClose={unsaved.closeUnsavedModalContinueEditing}
>
  <p class="text-sm text-muted-foreground">
    Discard them and leave, or stay on this page to keep editing.
  </p>
  {#snippet footer()}
    <Button variant="outline" onclick={unsaved.closeUnsavedModalContinueEditing}>Continue editing</Button>
    <Button variant="destructive" onclick={unsaved.confirmUnsavedModalDiscard}>Discard changes</Button>
  {/snippet}
</Modal>
