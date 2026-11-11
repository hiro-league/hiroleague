<script lang="ts">
  import { afterNavigate } from '$app/navigation';
  import { onMount } from 'svelte';
  import { Plus, UserRound } from '@lucide/svelte';
  import PageHeader from '$kit/ui/page-header.svelte';
  import AdminRecordTabChip from '$lib/components/page/AdminRecordTabChip.svelte';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import type { PageTab } from '$kit/ui/page-tabs.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import CharactersBrowseSection from '$lib/features/characters/browse/CharactersBrowseSection.svelte';
  import CharacterViewPanel from '$lib/features/characters/view/CharacterViewPanel.svelte';
  import CharacterEditPanel from '$lib/features/characters/view/CharacterEditPanel.svelte';
  import CharacterDialogs from '$lib/features/characters/modals/CharacterDialogs.svelte';
  import { createCharactersPageController } from '$lib/features/characters/state/characters-controller.svelte';
  import { ask } from '$kit/ui/confirm.svelte';
  import { toast } from '$kit/ui/toast.svelte';
  import { createCharactersPreferences } from '$lib/preferences/characters-preferences.svelte';
  import type { CharactersTabPreference } from '$lib/preferences/keys';

  const prefs = createCharactersPreferences();
  const notify = toast.show;

  /** Remote list/detail/catalog + destructive actions wired to prefs; it holds the character being edited (`ctrl.draft`). */
  const ctrl = createCharactersPageController({
    prefs,
    notify,
    confirmDiscard: async () =>
      !ctrl.draft.dirty ||
      ask({
        title: 'Unsaved changes',
        description: 'You have edits that are not saved yet. Discard them and leave, or stay to keep editing.',
        action: 'Discard changes',
        danger: true
      })
  });

  const detailVisible = $derived(prefs.activeTab === 'detail');
  const isNew = $derived(detailVisible && prefs.detailMode === 'edit' && !prefs.characterId);

  const detailTabLabel = $derived(
    isNew ? 'New character' : ctrl.selected?.name?.trim() || prefs.characterId || 'Detail'
  );

  const fixedTabs: readonly PageTab<CharactersTabPreference>[] = [
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

<section class={detailVisible && prefs.detailMode === 'edit'
    ? 'grid max-w-[1420px] gap-3'
    : 'grid max-w-[1420px] gap-5'}>
  <PageHeader title="Characters">
    {#snippet tabs()}
    <PageTabs
      label="Characters sections"
      tabs={fixedTabs}
      value={prefs.activeTab}
      onchange={() => void ctrl.openBrowse()}
    >
      {#snippet extra()}
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
    </PageTabs>
    {/snippet}
    {#snippet actions()}
    <Button onclick={() => void ctrl.openNewCharacter()}>
      <Plus size={16} /> New character
    </Button>
    {/snippet}
  </PageHeader>
  

  

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
    <CharacterEditPanel {ctrl} characterId={prefs.characterId} {notify} />
  {/if}
</section>


<CharacterDialogs {ctrl} characterId={prefs.characterId} />
