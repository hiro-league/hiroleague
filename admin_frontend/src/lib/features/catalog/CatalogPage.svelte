<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { who } from '$kit/state/who.svelte';
  import { tabsFor, type CoreFeature } from '$lib/shell/core-access';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import StickyBar from '$kit/ui/sticky-bar.svelte';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import type { PageTab } from '$kit/ui/page-tabs.svelte';
  import ModelsFilterBar from '$lib/features/catalog/browse/ModelsFilterBar.svelte';
  import ModelsTab from '$lib/features/catalog/browse/ModelsTab.svelte';
  import ProvidersTab from '$lib/features/catalog/browse/ProvidersTab.svelte';
  import ProfilesTab, { type ProfilesSub } from './ProfilesTab.svelte';
  import LocalServerDialog from '$lib/features/catalog/ai/LocalServerDialog.svelte';
  import LocalServerProviderRows from '$lib/features/catalog/ai/LocalServerProviderRows.svelte';
  import PlanProviderRows from '$lib/features/catalog/ai/PlanProviderRows.svelte';
  import PlanToolDialog from '$lib/features/catalog/ai/PlanToolDialog.svelte';
  import { createAiController } from '$lib/features/catalog/ai/ai-controller.svelte';
  import { LOCAL_SERVER_IDS } from '$lib/features/catalog/ai/ai-profile-rules';
  import { createCatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import type { CatalogTabPreference } from '$lib/preferences/keys';
  import { toast } from '$kit/ui/toast.svelte';

  const ctrl = createCatalogController(toast.show);
  // Phase 7a: AI profiles, uses, local servers and plan tools (`/api/ai`).
  const ai = createAiController(toast.show, ctrl);

  const tabDescriptors: readonly PageTab<CatalogTabPreference>[] = [
    // Providers tab merges the former Active + Catalog provider tabs into one list.
    { id: 'providers', label: 'Providers', kind: 'pane' },
    { id: 'models', label: 'Models', kind: 'pane' },
    // Phase 7b mockup: one Profiles tab; its sub-tabs (AI profiles, voice profiles,
    // uses) are `?tab=` values of their own, so the top strip marks Profiles for any of them.
    { id: 'profiles', label: 'Profiles', kind: 'pane' }
  ];
  const PROFILES_SUBS: readonly CatalogTabPreference[] = ['profiles', 'voices', 'embedders', 'rerankers', 'uses'];
  const inProfiles = $derived(PROFILES_SUBS.includes(ctrl.activeTab));

  // Permissions phase 2: Providers and Models need ai.providers (keys and costs), Profiles ai.profiles; a tab this
  // person may not open falls back to the first they may
  const featureOfTab = (id: CatalogTabPreference): CoreFeature => (PROFILES_SUBS.includes(id) ? 'ai.profiles' : 'ai.providers');
  const tabsShown = $derived(tabsFor(tabDescriptors, featureOfTab, who.me?.access));
  $effect(() => {
    const active: CatalogTabPreference = inProfiles ? 'profiles' : ctrl.activeTab;
    const first = tabsShown[0]?.id;
    if (first && !tabsShown.some((t) => t.id === active)) untrack(() => void ctrl.switchTab(first));
  });

  // Local servers (LM Studio, Ollama) and, once read, plan tools (Claude Code, Codex) draw their own
  // rows with live status; the table skips the catalog's rows for them.
  const replacedProviderIds = $derived(new Set<string>([...LOCAL_SERVER_IDS, ...ai.plans.map((t) => t.id)]));

  onMount(() => {
    void ctrl.initialize();
    void ai.initialize();
    return () => ai.dispose();
  });
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="Providers/Models">
    {#snippet tabs()}
    <PageTabs
      label="Providers and models sections"
      tabs={tabsShown}
      value={inProfiles ? 'profiles' : ctrl.activeTab}
      onchange={(id) => void ctrl.switchTab(id)}
    />
    {/snippet}
  </PageHeader>
  

  {#if ctrl.activeTab === 'models'}
    <StickyBar class="-mx-4 border-b bg-background/85 px-4 backdrop-blur md:-mx-6 md:px-6">
      <ModelsFilterBar {ctrl} />
    </StickyBar>
    <ModelsTab {ctrl} />
  {:else if inProfiles}
    <ProfilesTab
      {ai}
      active={ctrl.activeTab as ProfilesSub}
      onSelect={(id) => void ctrl.switchTab(id)}
      catalogProviders={ctrl.providers ?? []}
      activeProviderIds={ctrl.configuredWorkspaceProviderIds}
    />
  {:else}
    <!-- Phase 7a: the local servers' rows and the plan tools' rows, with their dialogs. -->
    <ProvidersTab {ctrl} {replacedProviderIds}>
      {#snippet extraRows(activeOnly: boolean)}
        <LocalServerProviderRows {ai} catalogProviders={ctrl.providers} {activeOnly} />
        <PlanProviderRows {ai} {activeOnly} />
      {/snippet}
    </ProvidersTab>
    <LocalServerDialog {ai} />
    <PlanToolDialog {ai} />
  {/if}
</section>

