<script lang="ts" module>
  import type { CatalogTabPreference } from '$lib/preferences/keys';
  export type ProfilesSub = Extract<CatalogTabPreference, 'profiles' | 'voices' | 'uses'>;
</script>

<script lang="ts">
  /**
   * Catalog → Profiles (Phase 7b): one top tab with three sub-tabs, in this order — AI profiles | Voice
   * profiles | Uses. Each sub-tab is its own `?tab=` value (profiles, voices, uses), so links into one keep
   * working. Designed voices have no sub-tab: they are designed, kept and deleted inside a voice profile's
   * Voice → My voices, where they are used (as in HomeHiro).
   *
   * `&edit=<id>` opens that profile's editor: an extension's "Edit" (HomeHiro) links here, so a profile is
   * only ever edited in the core's admin.
   *
   * Phase 7b step 5: Hiro's own jobs are on AI profiles too — their default profiles are rows of AI
   * profiles, and Uses lists Hiro's jobs and voice first (its count includes them).
   */
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import type { CatalogProviderRow } from '$lib/api/catalog';
  import type { VoiceProfileRow } from '$lib/api/voice';
  import AdminSubtabStrip from '$lib/components/page/AdminSubtabStrip.svelte';
  import AiProfilesTab from '$lib/features/catalog/ai/AiProfilesTab.svelte';
  import AiUsesTab from '$lib/features/catalog/ai/AiUsesTab.svelte';
  import type { AiController } from '$lib/features/catalog/ai/ai-controller.svelte';
  import VoiceProfileEditorDialog from './voice/VoiceProfileEditorDialog.svelte';
  import VoiceProfilesList from './voice/VoiceProfilesList.svelte';
  import { VoiceController } from './voice/voice-controller.svelte';

  let {
    ai,
    active,
    onSelect,
    catalogProviders,
    activeProviderIds
  }: {
    ai: AiController;
    active: ProfilesSub;
    onSelect: (id: ProfilesSub) => void;
    catalogProviders: CatalogProviderRow[];
    activeProviderIds: Set<string>;
  } = $props();

  const voice = new VoiceController();
  onMount(() => void voice.load());

  const voiceUseCount = $derived(voice.uses.extensions.reduce((n, e) => n + e.uses.filter((u) => u.status !== 'removed').length, 0));
  // Uses: Hiro's jobs + its voice (one speaking use), then the extensions' AI and voice uses.
  const hiroUseCount = $derived(ai.jobs.length + 1);
  const subtabs = $derived([
    { id: 'profiles' as const, label: 'AI profiles', count: ai.profiles.length },
    { id: 'voices' as const, label: 'Voice profiles', count: voice.profiles.length },
    { id: 'uses' as const, label: 'Uses', count: hiroUseCount + ai.uses.length + voiceUseCount }
  ]);

  let voiceEditing = $state<VoiceProfileRow | null>(null);
  let voiceCopyOf = $state<VoiceProfileRow | null>(null);
  let voiceEditorOpen = $state(false);
  const editVoice = (r: VoiceProfileRow | null) => {
    voiceEditing = r;
    voiceCopyOf = null;
    voiceEditorOpen = true;
  };
  const duplicateVoice = (r: VoiceProfileRow) => {
    voiceEditing = null;
    voiceCopyOf = r;
    voiceEditorOpen = true;
  };

  // `&edit=<id>` from an extension's Edit link: open that profile once the list has it.
  let pendingEdit = $state<string | null>(null);
  onMount(() => {
    pendingEdit = page.url.searchParams.get('edit');
  });
  $effect(() => {
    const id = pendingEdit;
    if (!id) return;
    if (active === 'voices') {
      const r = voice.profiles.find((x) => x.id === id);
      if (r) {
        editVoice(r);
        pendingEdit = null;
      } else if (!voice.loading && voice.profiles.length) pendingEdit = null;
    } else if (active === 'profiles') {
      if (ai.profiles.some((p) => p.id === id)) {
        ai.editProfile(id);
        pendingEdit = null;
      } else if (!ai.profilesLoading) pendingEdit = null;
    } else pendingEdit = null;
  });
</script>

<div class="grid gap-4">
  <AdminSubtabStrip ariaLabel="Profiles sections" tabs={subtabs} {active} {onSelect} />

  {#if active === 'profiles'}
    <AiProfilesTab {ai} />
  {:else if active === 'voices'}
    <VoiceProfilesList ctrl={voice} onedit={editVoice} onduplicate={duplicateVoice} />
  {:else}
    <AiUsesTab {ai} {voice} />
  {/if}
</div>

<VoiceProfileEditorDialog
  bind:open={voiceEditorOpen}
  profile={voiceEditing}
  copyOf={voiceCopyOf}
  ctrl={voice}
  {catalogProviders}
  {activeProviderIds}
/>
