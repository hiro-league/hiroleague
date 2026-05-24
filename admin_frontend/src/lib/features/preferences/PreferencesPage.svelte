<script lang="ts">
  import { onMount } from 'svelte';
  import { KeyRound, RotateCcw, Save } from '@lucide/svelte';
  import { base } from '$app/paths';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminPageLinkAction from '$lib/components/page/AdminPageLinkAction.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import SectionScrollNav from '$lib/components/page/SectionScrollNav.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import KnowledgeSection from '$lib/features/preferences/sections/KnowledgeSection.svelte';
  import MediaSection from '$lib/features/preferences/sections/MediaSection.svelte';
  import MemorySection from '$lib/features/preferences/sections/MemorySection.svelte';
  import ModelsSection from '$lib/features/preferences/sections/ModelsSection.svelte';
  import TuningProfilesSection from '$lib/features/preferences/sections/TuningProfilesSection.svelte';
  import { createPreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    PREFERENCE_SECTION_NAV,
    PREFERENCE_SECTION_SCROLL_MARKER_PX
  } from '$lib/features/preferences/state/preferences-section-nav';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';

  const toasts = createToastNotifier();
  const ctrl = createPreferencesController(toasts.notify);

  onMount(() => {
    void ctrl.loadAll();
  });
</script>

<svelte:head>
  <title>Preferences - Hiro Admin</title>
</svelte:head>

<ToastHost toast={toasts.toast} />

<AdminPageHeader
  sticky
  kicker="Workspace"
  title="Preferences"
  subtitle="Runtime preferences are held in memory and persisted to preferences.json when saved."
>
  {#snippet actions()}
    <AdminPageLinkAction
      href={`${base}/active-providers/`}
      icon={KeyRound}
      variant="outline"
      class={ctrl.busy ? 'pointer-events-none opacity-60' : ''}
    >
      Active providers
    </AdminPageLinkAction>
    {#if ctrl.dirty}
      <Button variant="outline" disabled={ctrl.busy} onclick={() => void ctrl.resetDraft()}>
        <RotateCcw size={16} /> Reset
      </Button>
      <Button disabled={!ctrl.canSave} onclick={() => void ctrl.savePreferences()}>
        <Save size={16} /> {ctrl.busy ? 'Saving...' : 'Save'}
      </Button>
    {/if}
  {/snippet}

  <AdminPageStickyToolbar>
    <SectionScrollNav
      ariaLabel="Preference sections"
      sections={PREFERENCE_SECTION_NAV}
      scrollMarkerPx={PREFERENCE_SECTION_SCROLL_MARKER_PX}
    />
  </AdminPageStickyToolbar>

  {#if ctrl.loading}
    <InlineLoading label="Loading preferences…" />
  {:else if ctrl.error}
    <InlineDestructiveAlert message={ctrl.error} class="p-4 text-sm" />
  {:else if ctrl.draft}
    <ModelsSection {ctrl} />
    <MediaSection {ctrl} />
    <MemorySection {ctrl} />
    <KnowledgeSection {ctrl} />
    <TuningProfilesSection {ctrl} />
  {/if}
</AdminPageHeader>

<Dialog.Root
  open={ctrl.unsaved.unsavedModalOpen}
  onOpenChange={(next) => { if (!next) ctrl.unsaved.closeUnsavedModalContinueEditing(); }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Discard unsaved preferences?</Dialog.Title>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">
      You have unsaved workspace preference changes. Discard them and leave, or keep editing.
    </p>
    <Dialog.Footer>
      <Button variant="outline" onclick={ctrl.unsaved.closeUnsavedModalContinueEditing}>
        Keep editing
      </Button>
      <Button variant="destructive" onclick={ctrl.unsaved.confirmUnsavedModalDiscard}>
        Discard changes
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
