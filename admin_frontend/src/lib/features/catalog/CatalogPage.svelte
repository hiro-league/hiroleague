<script lang="ts">
  import { onMount } from 'svelte';
  import AdminPageHeader from '$lib/components/page/AdminPageHeader.svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import AdminTabStrip from '$lib/components/page/AdminTabStrip.svelte';
  import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
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
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';

  const toasts = createToastNotifier();
  const ctrl = createCatalogController(toasts.notify);
  // Phase 7a: AI profiles, uses, local servers and plan tools (`/api/ai`).
  const ai = createAiController(toasts.notify, ctrl);

  const tabDescriptors: readonly AdminTabDescriptor<CatalogTabPreference>[] = [
    // Providers tab merges the former Active + Catalog provider tabs into one list.
    { id: 'providers', label: 'Providers', kind: 'pane' },
    { id: 'models', label: 'Models', kind: 'pane' },
    // Phase 7b mockup: one Profiles tab; its sub-tabs (AI profiles, voice profiles,
    // uses) are `?tab=` values of their own, so the top strip marks Profiles for any of them.
    { id: 'profiles', label: 'Profiles', kind: 'pane' }
  ];
  const PROFILES_SUBS: readonly CatalogTabPreference[] = ['profiles', 'voices', 'uses'];
  const inProfiles = $derived(PROFILES_SUBS.includes(ctrl.activeTab));

  // Local servers (LM Studio, Ollama) and, once read, plan tools (Claude Code, Codex) draw their own
  // rows with live status; the table skips the catalog's rows for them.
  const replacedProviderIds = $derived(new Set<string>([...LOCAL_SERVER_IDS, ...ai.plans.map((t) => t.id)]));

  onMount(() => {
    void ctrl.initialize();
    void ai.initialize();
    return () => ai.dispose();
  });
</script>

<AdminPageHeader sticky kicker="Configuration" title="Providers/Models">
  {#snippet tabs()}
    <AdminTabStrip
      ariaLabel="Providers and models sections"
      tabs={tabDescriptors}
      active={inProfiles ? 'profiles' : ctrl.activeTab}
      onSelect={(id) => void ctrl.switchTab(id)}
    />
  {/snippet}

  {#if ctrl.activeTab === 'models'}
    <AdminPageStickyToolbar>
      <ModelsFilterBar {ctrl} />
    </AdminPageStickyToolbar>
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
</AdminPageHeader>

<ToastHost toast={toasts.toast} />
