<script lang="ts">
  import { browser } from '$app/environment';
  import { afterNavigate } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount, setContext } from 'svelte';
  import { ChevronsDownUp, ChevronsUpDown, RotateCcw, Save } from '@lucide/svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminSubtabStrip from '$lib/components/page/AdminSubtabStrip.svelte';
  import {
    COLLAPSIBLE_SECTION_REGISTRY,
    createCollapsibleSectionRegistry
  } from '$lib/components/page/collapsible-section-registry.svelte';
  import type { AdminSubtabDescriptor } from '$lib/components/page/tab-types';
  import Button from '$lib/components/ui/button.svelte';
  import AgentSection from '$lib/features/preferences/sections/AgentSection.svelte';
  import KnowledgeSection from '$lib/features/preferences/sections/KnowledgeSection.svelte';
  import MediaSection from '$lib/features/preferences/sections/MediaSection.svelte';
  import MemorySection from '$lib/features/preferences/sections/MemorySection.svelte';
  import ModelsSection from '$lib/features/preferences/sections/ModelsSection.svelte';
  import TuningProfilesSection from '$lib/features/preferences/sections/TuningProfilesSection.svelte';
  import {
    DEFAULT_PREFERENCE_TAB,
    LEGACY_PREFERENCE_HASH_TO_TAB,
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS,
    PREFERENCE_TABLIST_LABEL,
    PREFERENCE_TABS,
    type PreferenceTabId
  } from '$lib/features/preferences/shared/preferences-tabs';
  import { createPreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { createPreferencesTabPreferences } from '$lib/preferences/preferences-tab-preferences.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';

  const toasts = createToastNotifier();
  const ctrl = createPreferencesController(toasts.notify);
  const tabPrefs = createPreferencesTabPreferences();
  const sectionRegistry = createCollapsibleSectionRegistry();
  setContext(COLLAPSIBLE_SECTION_REGISTRY, sectionRegistry);

  function migrateLegacyHash() {
    if (!browser) return;
    const hash = window.location.hash.slice(1);
    if (!hash) return;
    const tab = LEGACY_PREFERENCE_HASH_TO_TAB[hash];
    if (!tab) return;
    const nextUrl = new URL(window.location.href);
    nextUrl.hash = '';
    if (tab !== DEFAULT_PREFERENCE_TAB) {
      nextUrl.searchParams.set('tab', tab);
    } else {
      nextUrl.searchParams.delete('tab');
    }
    window.history.replaceState(null, '', `${nextUrl.pathname}${nextUrl.search}`);
  }

  /** Resolve tab from URL/session before first paint — onMount was too late (Models click no-op). */
  function bootstrapTabPrefs() {
    migrateLegacyHash();
    tabPrefs.initialize();
  }

  if (browser) {
    bootstrapTabPrefs();
  }

  afterNavigate(() => {
    if (!browser) return;
    tabPrefs.initialize();
  });

  const subtabDescriptors: readonly AdminSubtabDescriptor<PreferenceTabId>[] = PREFERENCE_TABS.map(
    (tab) => ({
      id: tab.id,
      label: tab.label,
      htmlId: PREFERENCE_TAB_IDS[tab.id],
      ariaControls: PREFERENCE_TAB_PANEL_IDS[tab.id]
    })
  );

  async function switchTab(tab: PreferenceTabId) {
    if (tab === tabPrefs.activeTab) return;
    if (ctrl.dirty) {
      if (!(await ctrl.unsaved.confirmDiscard())) return;
      ctrl.abandonDraft();
    }
    await tabPrefs.setActiveTab(tab);
  }

  function discardUnsavedChanges() {
    ctrl.abandonDraft();
    ctrl.unsaved.confirmUnsavedModalDiscard();
  }

  onMount(() => {
    void ctrl.loadAll();
  });

  // Unsaved-guard `goto` can change `?tab=` without remounting; URL param wins over session.
  $effect(() => {
    page.url.searchParams.get('tab');
    tabPrefs.syncActiveTabFromUrl();
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
  {#if !ctrl.error}
    <AdminPageStickyToolbar>
      <AdminSubtabStrip
        ariaLabel={PREFERENCE_TABLIST_LABEL}
        tabs={subtabDescriptors}
        active={tabPrefs.activeTab}
        onSelect={(id) => {
          void switchTab(id);
        }}
      >
        {#snippet toolbar()}
          <div class="flex flex-wrap items-center gap-2 pb-1">
            {#if ctrl.dirty}
              <Button variant="outline" disabled={ctrl.busy} onclick={() => void ctrl.resetDraft()}>
                <RotateCcw size={16} /> Reset
              </Button>
              <Button disabled={!ctrl.canSave} onclick={() => void ctrl.savePreferences()}>
                <Save size={16} /> {ctrl.busy ? 'Saving...' : 'Save'}
              </Button>
            {/if}
            {#if ctrl.draft && !ctrl.loading}
              <Button
                variant="ghost"
                size="icon"
                class="text-muted-foreground hover:text-foreground"
                type="button"
                aria-label={sectionRegistry.anyExpanded
                  ? 'Collapse all preference sections'
                  : 'Expand all preference sections'}
                title={sectionRegistry.anyExpanded
                  ? 'Collapse all sections'
                  : 'Expand all sections'}
                onclick={() => sectionRegistry.toggleAll()}
              >
                {#if sectionRegistry.anyExpanded}
                  <ChevronsDownUp size={17} strokeWidth={2} aria-hidden="true" />
                {:else}
                  <ChevronsUpDown size={17} strokeWidth={2} aria-hidden="true" />
                {/if}
              </Button>
            {/if}
          </div>
        {/snippet}
      </AdminSubtabStrip>
    </AdminPageStickyToolbar>
  {/if}

  {#if ctrl.loading}
    <InlineLoading label="Loading preferences…" />
  {:else if ctrl.error}
    <InlineDestructiveAlert message={ctrl.error} class="p-4 text-sm" />
  {:else if ctrl.draft}
    {#if tabPrefs.activeTab === 'models'}
      <ModelsSection {ctrl} />
    {:else if tabPrefs.activeTab === 'media'}
      <MediaSection {ctrl} />
    {:else if tabPrefs.activeTab === 'memory'}
      <MemorySection {ctrl} />
    {:else if tabPrefs.activeTab === 'knowledge'}
      <KnowledgeSection {ctrl} />
    {:else if tabPrefs.activeTab === 'agent'}
      <AgentSection {ctrl} />
    {:else}
      <TuningProfilesSection {ctrl} />
    {/if}
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
      <Button variant="destructive" onclick={discardUnsavedChanges}>
        Discard changes
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
