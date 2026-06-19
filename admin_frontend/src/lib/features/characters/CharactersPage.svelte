<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { Plus, UserRound } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminRecordTabChip from '$lib/components/page/AdminRecordTabChip.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
  import Button from '$lib/components/ui/button.svelte';
  import CharactersBrowseSection from '$lib/features/characters/browse/CharactersBrowseSection.svelte';
  import CharacterViewPanel from '$lib/features/characters/view/CharacterViewPanel.svelte';
  import CharacterEditPanel from '$lib/features/characters/view/CharacterEditPanel.svelte';
  import CharacterDialogs from '$lib/features/characters/modals/CharacterDialogs.svelte';
  import { createCharactersFormModel } from '$lib/features/characters/state/characters-form.svelte';
  import { createCharactersPageController } from '$lib/features/characters/state/characters-controller.svelte';
  import { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';
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
    <CharacterEditPanel {ctrl} {formApi} characterId={prefs.characterId} {notify} />
  {/if}
</AdminPageHeader>

<ToastHost toast={toasts.toast} />

<CharacterDialogs {ctrl} {unsaved} characterId={prefs.characterId} />
