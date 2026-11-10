<script lang="ts">
  /**
   * Catalog → Profiles → Voice profiles (Phase 7b): laid out like the AI profiles list — name and what uses
   * it, model and provider, voice and style, actions. Unused profiles are marked; a filter shows each
   * extension's or the unused ones, so the sources don't mix. A designed voice Google dropped is flagged.
   */
  import { Copy, Pencil, Plus, Trash2, TriangleAlert } from '@lucide/svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import type { VoiceProfileRow } from '$lib/api/voice';
  import { ADMIN_SECTION_HEADING_LG } from '$lib/styling/admin-tokens';
  import SourceFilter, { type SourceOption } from '$lib/components/page/SourceFilter.svelte';
  import { sourceOf } from './voice-format';
  import type { VoiceController } from './voice-controller.svelte';

  let {
    ctrl,
    onedit,
    onduplicate
  }: {
    ctrl: VoiceController;
    onedit: (r: VoiceProfileRow | null) => void;
    onduplicate: (r: VoiceProfileRow) => void;
  } = $props();

  const GRID = 'minmax(180px,1.1fr) minmax(200px,1.1fr) minmax(220px,1.5fr) 300px';
  const VOICE_SOURCE = { studio: 'Studio voice', library: 'Voice library', mine: 'Designed voice' } as const;
  const title = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  // Who a voice profile serves: the extensions of the uses that point at it ("home:speak" → Home), and
  // Hiro when it is Hiro's own voice (Phase 7b step 5: `voice.hiro_profile`).
  const HIRO = 'Hiro';
  const isHiroVoice = (r: VoiceProfileRow) => ctrl.hiroProfile === r.id;
  const sourcesOf = (r: VoiceProfileRow) =>
    new Set([...(isHiroVoice(r) ? [HIRO] : []), ...r.used_by.map((k) => title(k.split(':')[0]))]);
  const isUnused = (r: VoiceProfileRow) => !r.used_by.length && !isHiroVoice(r);
  const sources = $derived(
    [...new Set(ctrl.profiles.flatMap((r) => [...sourcesOf(r)]))].sort((a, b) =>
      a === HIRO ? -1 : b === HIRO ? 1 : a.localeCompare(b)
    )
  );
  const options: SourceOption[] = $derived([
    { id: 'all', label: 'All', count: ctrl.profiles.length },
    ...sources.map((s) => ({ id: s, label: s, count: ctrl.profiles.filter((r) => sourcesOf(r).has(s)).length })),
    { id: 'unused', label: 'Unused', count: ctrl.profiles.filter(isUnused).length }
  ]);
  let source = $state('all');
  const rows = $derived(
    source === 'all'
      ? ctrl.profiles
      : source === 'unused'
        ? ctrl.profiles.filter(isUnused)
        : ctrl.profiles.filter((r) => sourcesOf(r).has(source))
  );
  const usedByLine = (r: VoiceProfileRow) =>
    [...(isHiroVoice(r) ? ["Hiro's voice"] : []), ...r.used_by.map(ctrl.useLabel)].join(', ');
  let confirmDelete = $state<string | null>(null);
  let deleteError = $state<string | null>(null);

  async function remove(r: VoiceProfileRow) {
    deleteError = await ctrl.remove(r.id);
    confirmDelete = null;
  }
  const voiceKind = (r: VoiceProfileRow) => (r.provider === 'openai' ? 'OpenAI voice' : VOICE_SOURCE[sourceOf(r.voice)]);
</script>

<SectionCard class="grid gap-4">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class={ADMIN_SECTION_HEADING_LG}>Voice profiles</h3>
      <p class="font-sans text-sm text-muted-foreground">
        How something speaks: the speech model, the voice, the speaking style and speed. Uses point at a profile.
      </p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <SourceFilter {options} value={source} onchange={(id) => (source = id)} />
      <Button onclick={() => onedit(null)}><Plus size={15} /> New voice profile</Button>
    </div>
  </div>

  {#if ctrl.error}<InlineDestructiveAlert message={ctrl.error} />{/if}
  {#if deleteError}<InlineDestructiveAlert message={deleteError} />{/if}

  {#if ctrl.loading && !ctrl.profiles.length}
    <InlineLoading label="Reading voice profiles…" />
  {:else if !ctrl.profiles.length}
    <InlineEmptyState message="No voice profiles yet. Make one for each way something should speak (an alert, a story, Hiro)." />
  {:else}
    <AdminTableShell layout="grid" minWidth={980} gridColumns={GRID}>
      {#snippet headRow()}
        <span>Name</span>
        <span>Model</span>
        <span>Voice and style</span>
        <span class="text-right">Actions</span>
      {/snippet}
      {#snippet body()}
        {#each rows as r (r.id)}
          <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
            <span class="grid content-start gap-1">
              <span class="flex items-center gap-2">
                <span class="font-sans text-sm font-semibold">{r.label}</span>
                {#if isUnused(r)}<Badge variant="outline">Unused</Badge>{/if}
              </span>
              {#if !isUnused(r)}<span class="text-xs text-muted-foreground">Used by {usedByLine(r)}</span>{/if}
            </span>
            <span class="grid content-start gap-1">
              <span class="truncate font-sans text-sm">{r.model.split(':')[1]}</span>
              <span class="truncate text-xs text-muted-foreground">{r.provider === 'openai' ? 'OpenAI' : 'Google'}</span>
            </span>
            <span class="grid content-start gap-1">
              <span class="flex items-center gap-2">
                <span class="font-sans text-sm">{r.voice_label || r.voice}</span>
                <span class="text-xs text-muted-foreground">{voiceKind(r)}{r.provider === 'openai' && r.speed !== 1 ? ` · ${r.speed}×` : ''}</span>
              </span>
              {#if r.voice_ok === false}
                <!-- As HomeHiro's list did: Google no longer has this designed voice (they expire after a year). -->
                <span class="flex items-center gap-1 text-xs text-destructive"><TriangleAlert size={12} /> Gemini no longer has this voice</span>
              {:else if r.style}<span class="truncate text-xs text-muted-foreground" title={r.style}>{r.style}</span>{/if}
            </span>
            <span class="grid justify-items-end gap-1.5">
              <span class="flex flex-wrap justify-end gap-2">
                <Button size="sm" variant="outline" onclick={() => onedit(r)}><Pencil size={13} /> Edit</Button>
                <Button size="sm" variant="outline" onclick={() => onduplicate(r)}><Copy size={13} /> Duplicate</Button>
                <Button size="sm" variant="destructive-outline" onclick={() => (confirmDelete = r.id)}><Trash2 size={13} /> Delete</Button>
              </span>
              {#if confirmDelete === r.id}
                <span class="flex flex-wrap items-center justify-end gap-2 text-xs">
                  Delete "{r.label}"?{r.used_by.length ? ' Its uses will have no voice.' : ''}{isHiroVoice(r)
                    ? " Hiro won't speak its replies until another voice is picked."
                    : ''}
                  <Button size="sm" variant="destructive-outline" onclick={() => remove(r)}>Delete</Button>
                  <Button size="sm" variant="ghost" onclick={() => (confirmDelete = null)}>Cancel</Button>
                </span>
              {/if}
            </span>
          </div>
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</SectionCard>
