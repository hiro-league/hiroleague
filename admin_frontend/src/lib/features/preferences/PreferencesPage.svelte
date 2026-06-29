<script lang="ts">
  import { browser } from '$app/environment';
  import { afterNavigate } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount, setContext, tick } from 'svelte';
  import { ChevronsDownUp, ChevronsUpDown, Eye, EyeOff, RotateCcw, Save } from '@lucide/svelte';
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
  import EvalSection from '$lib/features/preferences/sections/EvalSection.svelte';
  import GraphEngineSection from '$lib/features/preferences/sections/GraphEngineSection.svelte';
  import KnowledgeSection from '$lib/features/preferences/sections/KnowledgeSection.svelte';
  import ModelsSection from '$lib/features/preferences/sections/ModelsSection.svelte';
  import TuningProfilesSection from '$lib/features/preferences/sections/TuningProfilesSection.svelte';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS,
    PREFERENCE_TABLIST_LABEL,
    PREFERENCE_TABS,
    type PreferenceTabId
  } from '$lib/features/preferences/shared/preferences-tabs';
  import {
    createAdvancedVisibility,
    provideAdvancedVisibility
  } from '$lib/features/preferences/shared/preferences-advanced.svelte';
  import { createPreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { createPreferencesSearch } from '$lib/features/preferences/state/preferences-search.svelte';
  import PrefSearchBox from '$lib/features/preferences/widgets/PrefSearchBox.svelte';
  import type { PrefSearchEntry } from '$lib/features/preferences/shared/preferences-search-index';
  import { createPreferencesTabPreferences } from '$lib/preferences/preferences-tab-preferences.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';
  import UnsavedPreferencesDialog from '$lib/features/preferences/widgets/UnsavedPreferencesDialog.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';

  const toasts = createToastNotifier();
  const ctrl = createPreferencesController(toasts.notify);
  // Global "show advanced" toggle, shared with every field gate via context (session-persisted).
  const advancedVis = createAdvancedVisibility();
  provideAdvancedVisibility(advancedVis);
  const tabPrefs = createPreferencesTabPreferences();
  const sectionRegistry = createCollapsibleSectionRegistry();
  setContext(COLLAPSIBLE_SECTION_REGISTRY, sectionRegistry);
  // Settings search — data-driven (schema titles + tab map), so per-tab counts cover every tab while
  // only the active one is mounted. Clean-only: cleared + disabled while there are unsaved edits.
  const search = createPreferencesSearch(() => ctrl.fieldSchema);

  if (browser) {
    tabPrefs.bootstrap();
  }

  afterNavigate(() => {
    if (!browser) return;
    tabPrefs.initialize();
  });

  // Per-tab result counts appear in the tab strip while a search is active (e.g. "Memory (3)").
  const subtabDescriptors = $derived<readonly AdminSubtabDescriptor<PreferenceTabId>[]>(
    PREFERENCE_TABS.map((tab) => ({
      id: tab.id,
      label: tab.label,
      htmlId: PREFERENCE_TAB_IDS[tab.id],
      ariaControls: PREFERENCE_TAB_PANEL_IDS[tab.id],
      count: search.active ? (search.countsByTab[tab.id] ?? 0) : undefined
    }))
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

  // Search is clean-only: drop the query the moment edits make the page dirty (the box also disables).
  $effect(() => {
    if (ctrl.dirty && search.query) search.clear();
  });

  // Jump to the active match whenever it changes (typing picks the first match; arrows step through).
  // Reads `activeMatch` synchronously so the effect tracks it, then performs the DOM-side jump. The
  // path guard avoids re-scrolling when narrowing the query keeps the same top match.
  let lastNavPath: string | null = null;
  $effect(() => {
    const match = search.activeMatch;
    if (!match) {
      lastNavPath = null;
      return;
    }
    if (match.path === lastNavPath) return;
    lastNavPath = match.path;
    void navigateToMatch(match);
  });

  // Persistent highlight on EVERY match in the mounted tab (a stronger marker on the active one),
  // so all matching fields stay visibly marked while searching — not just a transient flash on the
  // one you jumped to. Only the active tab is mounted, so only its matches are tagged here; the
  // others are surfaced by the per-tab count badges and get tagged when you arrow into that tab.
  // Re-runs after the DOM settles whenever the match set, active match, tab, or reveal state changes.
  function markMatches() {
    if (!browser) return;
    const paths = new Set(search.matches.map((m) => m.path));
    const active = search.activeMatch?.path ?? null;
    for (const el of document.querySelectorAll<HTMLElement>('[data-pref-path]')) {
      const path = el.getAttribute('data-pref-path');
      el.classList.toggle('pref-search-match', !!path && paths.has(path));
      el.classList.toggle('pref-search-active', path === active);
    }
  }

  $effect(() => {
    // Track the inputs that change which matches are visible/marked.
    search.matches;
    search.activeMatch;
    tabPrefs.activeTab;
    advancedVis.showAdvanced;
    sectionRegistry.anyExpanded;
    if (!browser) return;
    void tick().then(markMatches);
  });

  let flashTimer: ReturnType<typeof setTimeout> | undefined;

  async function navigateToMatch(match: PrefSearchEntry) {
    if (!browser) return;
    // Reveal anything that would hide the target: advanced fields + collapsed sections.
    advancedVis.set(true);
    if (tabPrefs.activeTab !== match.tabId) {
      // Clean-only, so this never trips the unsaved-changes guard `switchTab` runs.
      await tabPrefs.setActiveTab(match.tabId);
    }
    await tick(); // let the (possibly newly mounted) tab + its section cards render
    sectionRegistry.expandAll();
    await tick(); // let expanded sections + advanced fields paint before we look them up
    const el = document.querySelector(`[data-pref-path="${match.path}"]`);
    if (!el) return; // dict/table controls (e.g. tuning_profiles) have no single anchor — tab switch is enough
    el.scrollIntoView({ block: 'center' });
    document
      .querySelectorAll('.pref-search-hit')
      .forEach((node) => node.classList.remove('pref-search-hit'));
    el.classList.add('pref-search-hit');
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => el.classList.remove('pref-search-hit'), 1800);
  }
</script>

<svelte:head>
  <title>Settings - Hiro Admin</title>
</svelte:head>

<ToastHost toast={toasts.toast} />

<AdminPageHeader
  sticky
  forceCompact={search.active}
  kicker="Workspace"
  title="Settings"
  subtitle="Runtime settings are held in memory and persisted to preferences.json when saved."
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
              <PrefSearchBox
                query={search.query}
                disabled={ctrl.dirty}
                position={search.position}
                total={search.total}
                onQuery={(next) => search.setQuery(next)}
                onPrev={search.prev}
                onNext={search.next}
                onClear={search.clear}
              />
              <Button
                variant="ghost"
                size="icon"
                class="text-muted-foreground hover:text-foreground"
                type="button"
                aria-pressed={advancedVis.showAdvanced}
                aria-label={advancedVis.showAdvanced
                  ? 'Hide advanced settings'
                  : 'Show advanced settings'}
                title={advancedVis.showAdvanced ? 'Hide advanced settings' : 'Show advanced settings'}
                onclick={() => advancedVis.toggle()}
              >
                {#if advancedVis.showAdvanced}
                  <Eye size={17} strokeWidth={2} aria-hidden="true" />
                {:else}
                  <EyeOff size={17} strokeWidth={2} aria-hidden="true" />
                {/if}
              </Button>
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
    {:else if tabPrefs.activeTab === 'knowledge'}
      <KnowledgeSection {ctrl} />
    {:else if tabPrefs.activeTab === 'graph-engine'}
      <GraphEngineSection {ctrl} />
    {:else if tabPrefs.activeTab === 'eval'}
      <EvalSection {ctrl} />
    {:else if tabPrefs.activeTab === 'agent'}
      <AgentSection {ctrl} />
    {:else}
      <TuningProfilesSection {ctrl} />
    {/if}
  {/if}
</AdminPageHeader>

<UnsavedPreferencesDialog unsaved={ctrl.unsaved} onDiscard={discardUnsavedChanges} />

<style>
  /* Search highlights. Targets live in child section components, so the rules must be :global.
     `match` = persistent marker on every matching field; `active` = stronger marker on the current
     one; `hit` = transient pulse applied on each jump. Ordered so `active` wins over `match`. */
  :global([data-pref-path].pref-search-match) {
    border-radius: 0.5rem;
    background-color: color-mix(in oklab, var(--ring) 8%, transparent);
    outline: 1px solid color-mix(in oklab, var(--ring) 35%, transparent);
    outline-offset: 3px;
  }
  :global([data-pref-path].pref-search-active) {
    background-color: color-mix(in oklab, var(--ring) 16%, transparent);
    outline: 2px solid var(--ring);
    outline-offset: 4px;
  }
  :global([data-pref-path].pref-search-hit) {
    animation: pref-search-pulse 1.6s ease-out;
  }
  @keyframes pref-search-pulse {
    0% {
      background-color: color-mix(in oklab, var(--ring) 38%, transparent);
    }
    100% {
      background-color: transparent;
    }
  }
</style>
