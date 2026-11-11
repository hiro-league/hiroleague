<script lang="ts">
  import CharacterEditToolbar from '$lib/features/characters/view/CharacterEditToolbar.svelte';
  import CharacterProfileSection from '$lib/features/characters/sections/CharacterProfileSection.svelte';
  import CharacterProfilesSection from '$lib/features/characters/sections/CharacterProfilesSection.svelte';
  import CharacterPromptsSection from '$lib/features/characters/sections/CharacterPromptsSection.svelte';
  import CharacterExtrasSection from '$lib/features/characters/sections/CharacterExtrasSection.svelte';
  import type { createCharactersPageController } from '$lib/features/characters/state/characters-controller.svelte';
  import type { createCharactersFormModel } from '$lib/features/characters/state/characters-form.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import Loading from '$kit/ui/loading.svelte';

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

  async function reloadProfiles() {
    try {
      await ctrl.reloadProfileOptions();
      notify('success', 'Profiles reloaded.');
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Could not read the profiles.');
    }
  }

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
      <Loading label="Loading character…" />
    {:else if ctrl.detailError}
      <Notice title="Could not load character" message={ctrl.detailError} />
    {:else}
      <div class="grid gap-8">
        <CharacterProfileSection
          form={formApi.form}
          {characterId}
          selected={ctrl.selected}
          markDirty={formApi.markDirty}
          onPickPhoto={(e) => void ctrl.photoCrop.pickPhoto(e)}
        />

        <!-- Phase 7b step 5: ordered AI / voice profiles (were model pickers, a tuning profile and TTS settings). -->
        <CharacterProfilesSection
          variant="ai"
          form={formApi.form}
          {characterId}
          options={ctrl.aiProfileOptions}
          busy={ctrl.busy}
          resolved={ctrl.resolved}
          resolvedError={ctrl.resolvedError}
          dirty={formApi.dirty}
          onReloadProfiles={() => void reloadProfiles()}
          markDirty={formApi.markDirty}
        />

        <CharacterProfilesSection
          variant="voice"
          form={formApi.form}
          {characterId}
          options={ctrl.voiceProfileOptions}
          busy={ctrl.busy}
          resolved={ctrl.resolved}
          resolvedError={ctrl.resolvedError}
          dirty={formApi.dirty}
          onReloadProfiles={() => void reloadProfiles()}
          markDirty={formApi.markDirty}
        />

        <CharacterPromptsSection form={formApi.form} markDirty={formApi.markDirty} />

        <CharacterExtrasSection form={formApi.form} markDirty={formApi.markDirty} />
      </div>
    {/if}
  </div>
</section>
