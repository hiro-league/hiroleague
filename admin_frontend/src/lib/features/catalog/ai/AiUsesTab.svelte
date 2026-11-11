<script lang="ts">
  /**
   * Uses: what Hiro and each extension ask an AI for, one source at a time, each pointed at a profile.
   * Hiro (first) is the core's own jobs and its voice (`HiroUsesTable`, Phase 7b step 5).
   * The note flags a profile whose model can't serve the use, else shows its fallback chain.
   * An extension can change its list without telling the core, so each group has Refresh ("Ask Home
   * for its uses") and an "as of" time; the server marks new uses ("New") and ones no longer offered
   * (greyed out, choice read-only, Forget).
   */
  import { RefreshCw, X } from '@lucide/svelte';
  import Panel from '$kit/ui/panel.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { dateTime } from '$lib/format/time';
  import ResourceView from '$kit/ui/resource-view.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import { cn } from '$lib/utils';
  import type { AiController } from './ai-controller.svelte';
  import { chainLabel, fallbackChain, needsMismatch } from './ai-profile-rules';
  import type { AiUse } from './ai-types';
  import Segmented from '$kit/ui/segmented.svelte';
  import VoiceUsesTable from '$lib/features/catalog/voice/VoiceUsesTable.svelte';
  import type { VoiceController } from '$lib/features/catalog/voice/voice-controller.svelte';
  import HiroUsesTable from './HiroUsesTable.svelte';

  let { ai, voice }: { ai: AiController; voice: VoiceController } = $props();

  // A filter per source: Hiro's own jobs and voice first, then each extension that declared uses.
  const HIRO = 'Hiro';
  let source = $state(HIRO);
  const sourceTabs = $derived([
    // Hiro's jobs plus its one speaking use (Hiro's voice).
    { value: HIRO, label: 'Hiro', count: ai.jobs.length + 1 },
    ...ai.useGroups.map((g) => ({ value: g.extension, label: g.extension, count: ai.uses.filter((u) => u.extension === g.extension && u.status !== 'removed').length }))
  ]);
  const activeSource = $derived(sourceTabs.some((t) => t.value === source) ? source : (sourceTabs[0]?.value ?? ''));

  // The two sources load apart, each with its own states (the kit's ResourceView). `data` is null while there is
  // nothing to show yet or the load failed, so a failed load shows the error alone, as before.
  const hiroJobs = {
    get data() {
      return ai.profilesError || (ai.profilesLoading && ai.jobs.length === 0) ? null : ai.jobs;
    },
    get error() {
      return ai.profilesError ?? '';
    },
    get loading() {
      return ai.profilesLoading;
    }
  };
  const extensionUses = {
    get data() {
      return ai.usesError || (ai.usesLoading && ai.useGroups.length === 0) ? null : ai.useGroups;
    },
    get error() {
      return ai.usesError ?? '';
    },
    get loading() {
      return ai.usesLoading;
    }
  };

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

<Panel
  title="Uses"
  description="What Hiro and each extension ask an AI for, and what speaks. Pick the profile each one uses."
  class="grid gap-4"
>
  {#snippet actions()}
    <!-- One source at a time — Hiro's own jobs, then each extension. The same pills as the profile lists
         (Uses is itself a sub-tab of Profiles, so no second tab strip). -->
    <Segmented class="flex-wrap" label="Show uses for" options={sourceTabs} value={activeSource} onchange={(id) => (source = id)} />
  {/snippet}

  {#if activeSource === HIRO}
    <ResourceView resource={hiroJobs} loadingLabel="Loading Hiro's jobs…" errorTitle="Could not load Hiro's jobs">
      {#snippet children()}
        <HiroUsesTable {ai} {voice} />
      {/snippet}
    </ResourceView>
  {:else}
  <ResourceView
    resource={extensionUses}
    empty={(groups) => groups.length === 0}
    emptyMessage="No extension has declared uses yet."
    emptyHint="Pair an extension on the Extensions page."
    loadingLabel="Loading uses…"
    errorTitle="Could not load uses"
  >
  {#snippet children(groups)}
  {#each groups.filter((g) => g.extension === activeSource) as group (group.extension)}
    {@const rows = ai.uses.filter((u) => u.extension === group.extension)}
    {@const offered = rows.filter((u) => u.status !== 'removed').length}
    {@const refreshing = ai.refreshingExtension(group.extension)}
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
            Uses as of {group.asOf ? dateTime(group.asOf) : 'never'}
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
      <TableShell layout="grid" minWidth={900} gridColumns={GRID}>
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
            {@const busy = ai.useBusy(use.id)}
            <div class={cn(TABLE_GRID_ROW, removed && 'opacity-60')} style:grid-template-columns={GRID}>
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
                <PickSelect
                  class="h-9 w-full text-sm"
                  label={`Profile for ${use.label}`}
                  value={use.profileId ?? ''}
                  disabled={removed || busy}
                  options={[{ value: '', label: 'No profile' }, ...ai.profiles.map((p) => ({ value: p.id, label: p.name }))]}
                  onchange={(v) => void ai.setUseProfile(use.id, v)}
                />
              </span>
              <span class="flex flex-wrap items-start justify-between gap-2">
                <span class={cn('text-sm', n.warn ? 'text-warning' : 'text-muted-foreground')}>
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
      </TableShell>
    </div>
      <!-- Phase 7b: the extension's speaking (voice uses), real. -->
      <VoiceUsesTable {voice} extension={group.extension} />
  {/each}
  {/snippet}
  </ResourceView>
  {/if}
</Panel>
