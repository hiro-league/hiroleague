<script lang="ts">
  /**
   * Uses: what each extension asks an AI for, grouped by extension, each pointed at a profile.
   * The note flags a profile whose model can't serve the use, else shows its fallback chain.
   * An extension can change its list without telling the core, so each group has Refresh ("Ask Home
   * for its uses") and an "as of" time; the server marks new uses ("New") and ones no longer offered
   * (greyed out, choice read-only, Forget).
   */
  import { RefreshCw, X } from '@lucide/svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { humanDateTime } from '$lib/format/human-datetime';
  import { ADMIN_SECTION_HEADING_LG, ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { cn } from '$lib/utils';
  import type { AiController } from './ai-controller.svelte';
  import { chainLabel, fallbackChain, needsMismatch } from './ai-profile-rules';
  import type { AiUse } from './ai-types';
  import HiroUsesMock from '$lib/mockups/HiroUsesMock.svelte';
  import VoiceUsesTable from '$lib/features/catalog/voice/VoiceUsesTable.svelte';
  import type { VoiceController } from '$lib/features/catalog/voice/voice-controller.svelte';
  import SourceFilter from '$lib/mockups/SourceFilter.svelte';
  import { MOCK_JOBS, PHASE7B_MOCKUP } from '$lib/mockups/phase7b';

  let { ai, voice }: { ai: AiController; voice: VoiceController } = $props();

  // A filter per source: each extension that declared uses (and, with the step 5 mockup on, Hiro's jobs first).
  let source = $state(PHASE7B_MOCKUP ? 'Hiro' : '');
  const sourceTabs = $derived([
    ...(PHASE7B_MOCKUP ? [{ id: 'Hiro', label: 'Hiro', count: MOCK_JOBS.length }] : []),
    ...ai.useGroups.map((g) => ({ id: g.extension, label: g.extension, count: ai.uses.filter((u) => u.extension === g.extension && u.status !== 'removed').length }))
  ]);
  const activeSource = $derived(sourceTabs.some((t) => t.id === source) ? source : (sourceTabs[0]?.id ?? ''));

  const GRID = 'minmax(200px,1.1fr) minmax(170px,0.9fr) minmax(200px,1fr) minmax(240px,1.4fr)';

  function note(use: AiUse): { text: string; warn: boolean } {
    if (use.status === 'removed') return { text: `No longer offered by ${use.extension}.`, warn: false };
    const profile = ai.profiles.find((p) => p.id === use.profileId);
    if (!profile) return { text: 'No profile: this use is not asked.', warn: true };
    const { provider, model } = ai.modelOf(profile);
    // Only judge what the picker knows; a model it doesn't list (e.g. a local one not checked yet) isn't flagged.
    const mismatch = model ? needsMismatch(use, provider, model) : null;
    if (mismatch) return { text: mismatch, warn: true };
    const chain = chainLabel(ai.profiles, fallbackChain(ai.profiles, profile.id));
    // chainLabel starts with "→ "; drop it after "Falls back to".
    return { text: chain ? `Falls back to ${chain.slice(2)}` : 'No fallback.', warn: false };
  }
</script>

<SectionCard class="grid gap-4">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class={ADMIN_SECTION_HEADING_LG}>Uses</h3>
      <p class="font-sans text-sm text-muted-foreground">
        What Hiro and each extension ask an AI for, and what speaks. Pick the profile each one uses.
      </p>
    </div>
    <!-- Phase 7b mockup: one source at a time — Hiro's own jobs, then each extension. The same pills as
         the profile lists (Uses is itself a sub-tab of Profiles, so no second tab strip). -->
    <SourceFilter options={sourceTabs} value={activeSource} onchange={(id) => (source = id)} />
  </div>

  {#if activeSource === 'Hiro'}
    <HiroUsesMock source="Hiro" extraProfiles={ai.profiles.map((p) => ({ id: p.id, name: p.name }))} />
  {:else}

  {#if ai.usesLoading && ai.useGroups.length === 0}
    <InlineLoading label="Loading uses…" />
  {:else if ai.usesError}
    <InlineDestructiveAlert title="Could not load uses" message={ai.usesError} />
  {:else if ai.useGroups.length === 0}
    <InlineEmptyState message="No extension has declared uses yet." hint="Pair an extension on the Extensions page." />
  {/if}

  {#each ai.useGroups.filter((g) => g.extension === activeSource) as group (group.extension)}
    {@const rows = ai.uses.filter((u) => u.extension === group.extension)}
    {@const offered = rows.filter((u) => u.status !== 'removed').length}
    {@const refreshing = ai.refreshingExtensions[group.extension]}
    <div class="grid gap-2">
      <div class="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h4 class="font-sans text-base font-semibold text-primary">
            {group.extension} <span class="text-sm font-normal text-muted-foreground">· {offered} uses</span>
            {#if !group.extensionId}
              <Badge variant="secondary">Not paired</Badge>
            {:else if group.connected === false}
              <Badge variant="secondary">Not connected</Badge>
            {/if}
          </h4>
          <p class="text-xs text-muted-foreground">
            Uses as of {group.asOf ? humanDateTime(group.asOf) : 'never'}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={refreshing || !group.extensionId || group.connected === false}
          title={group.connected === false ? `${group.extension} isn't connected` : `Ask ${group.extension} for its uses`}
          onclick={() => void ai.refreshUses(group)}
        >
          <RefreshCw size={13} class={cn(refreshing && 'animate-spin')} />
          {refreshing ? 'Asking…' : 'Refresh'}
        </Button>
      </div>
      <AdminTableShell layout="grid" minWidth={900} gridColumns={GRID}>
        {#snippet headRow()}
          <span>Use</span>
          <span>Needs</span>
          <span>Profile</span>
          <span>Note</span>
        {/snippet}
        {#snippet body()}
          {#each rows as use (use.id)}
            {@const n = note(use)}
            {@const removed = use.status === 'removed'}
            {@const busy = ai.useBusy[use.id]}
            <div class={cn(ADMIN_TABLE_GRID_ROW, removed && 'opacity-60')} style:grid-template-columns={GRID}>
              <span class="flex items-start gap-2">
                <span class="font-sans text-sm font-semibold">{use.label}</span>
                {#if use.status === 'new'}
                  <Badge variant="success">New</Badge>
                {/if}
              </span>
              <span class="flex flex-wrap content-start gap-1">
                {#if use.needs.pictures}
                  <Badge variant="secondary">
                    {use.needs.pictures === 1 ? 'a picture' : `up to ${use.needs.pictures} pictures`}
                  </Badge>
                {/if}
                {#if use.needs.sound}
                  <Badge variant="secondary">sound</Badge>
                {/if}
                {#if use.needs.json}
                  <Badge variant="outline">JSON</Badge>
                {/if}
              </span>
              <span>
                <select
                  class={cn(ADMIN_SELECT, 'w-full')}
                  aria-label={`Profile for ${use.label}`}
                  value={use.profileId ?? ''}
                  disabled={removed || busy}
                  onchange={(event) => void ai.setUseProfile(use.id, event.currentTarget.value)}
                >
                  <option value="">No profile</option>
                  {#each ai.profiles as p (p.id)}
                    <option value={p.id}>{p.name}</option>
                  {/each}
                </select>
              </span>
              <span class="flex flex-wrap items-start justify-between gap-2">
                <span class={cn('text-sm', n.warn ? 'text-amber-700 dark:text-amber-300' : 'text-muted-foreground')}>
                  {n.text}
                </span>
                {#if removed}
                  <Button size="sm" variant="outline" disabled={busy} onclick={() => void ai.forgetUse(use.id)}>
                    <X size={13} /> Forget
                  </Button>
                {/if}
              </span>
            </div>
          {/each}
        {/snippet}
      </AdminTableShell>
    </div>
      <!-- Phase 7b: the extension's speaking (voice uses), real. -->
      <VoiceUsesTable {voice} extension={group.extension} />
  {/each}
  {/if}
</SectionCard>
