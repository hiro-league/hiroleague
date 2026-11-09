<script lang="ts">
  /**
   * Catalog → Uses, Hiro's own group (Phase 7b MOCKUP): each of Hiro's jobs points at an AI profile,
   * like an extension's use does — instead of a model setting plus a tuning preset. And what speaks,
   * with its voice recipe. Same table as the extensions' groups below; nothing is saved.
   */
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import Badge from '$lib/components/ui/badge.svelte';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import MockupNote from './MockupNote.svelte';
  import {
    MOCK_DEFAULT_PROFILES,
    MOCK_JOBS,
    MOCK_VOICE_RECIPES,
    MOCK_VOICE_USES,
    mockProfile,
    mockRecipe,
    recipeLine
  } from './phase7b';

  /** source: "Hiro" (its jobs and its speaking) or an extension's name (only its speaking; its AI uses are the real table). */
  let { source, extraProfiles = [] }: { source: string; extraProfiles?: { id: string; name: string }[] } = $props();
  const voiceUses = $derived(MOCK_VOICE_USES.filter((u) => (source === 'Hiro' ? u.group === 'Hiro' : u.group !== 'Hiro')));

  const GRID = 'minmax(200px,1.1fr) minmax(170px,0.9fr) minmax(200px,1fr) minmax(240px,1.4fr)';
  let picks = $state<Record<string, string>>(Object.fromEntries(MOCK_JOBS.map((j) => [j.id, j.profileId])));
  let voicePicks = $state<Record<string, string>>(Object.fromEntries(MOCK_VOICE_USES.map((u) => [u.label, u.recipeId])));
</script>

<div class="grid gap-2">
  {#if source === 'Hiro'}
  <MockupNote
    text="Mockup (Phase 7b): Hiro's own jobs, each asking with an AI profile, beside each extension's uses. Today each job is a model setting plus a tuning preset in Preferences."
  />
  <div>
    <h4 class="font-sans text-base font-semibold text-primary">
      Hiro <span class="text-sm font-normal text-muted-foreground">· {MOCK_JOBS.length} jobs</span>
    </h4>
    <p class="text-xs text-muted-foreground">The core's own work. Each job starts with its default profile.</p>
  </div>
  <AdminTableShell layout="grid" minWidth={900} gridColumns={GRID}>
    {#snippet headRow()}
      <span>Job</span>
      <span>Needs</span>
      <span>Profile</span>
      <span>Note</span>
    {/snippet}
    {#snippet body()}
      {#each MOCK_JOBS as job (job.id)}
        {@const p = mockProfile(picks[job.id])}
        <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
          <span class="font-sans text-sm font-semibold">{job.label}</span>
          <span class="flex flex-wrap content-start gap-1">
            {#each job.needs ?? [] as n (n)}<Badge variant="secondary">{n}</Badge>{/each}
          </span>
          <span>
            <select class={cn(ADMIN_SELECT, 'w-full')} aria-label="Profile for {job.label}" bind:value={picks[job.id]}>
              {#each MOCK_DEFAULT_PROFILES as dp (dp.id)}<option value={dp.id}>{dp.name}</option>{/each}
              {#each extraProfiles as xp (xp.id)}<option value={xp.id}>{xp.name}</option>{/each}
            </select>
          </span>
          <span class="grid gap-0.5 text-sm text-muted-foreground">
            <span>{p ? `${p.provider} · ${p.model}${p.fallback ? ` · falls back to ${p.fallback}` : ''}` : 'An AI profile of yours.'}</span>
            <span class="text-xs">Was: {job.today}</span>
          </span>
        </div>
      {/each}
    {/snippet}
  </AdminTableShell>

  {/if}

  {#if voiceUses.length}
  <div class="mt-3">
    <h4 class="font-sans text-base font-semibold text-primary">
      Speaking <span class="text-sm font-normal text-muted-foreground">· {voiceUses.length} {voiceUses.length === 1 ? 'use' : 'uses'}</span>
    </h4>
    <p class="text-xs text-muted-foreground">What speaks, and the voice profile it speaks with (Catalog → Voices).</p>
  </div>
  <AdminTableShell layout="grid" minWidth={900} gridColumns={GRID}>
    {#snippet headRow()}
      <span>Use</span>
      <span>Needs</span>
      <span>Voice</span>
      <span>Note</span>
    {/snippet}
    {#snippet body()}
      {#each voiceUses as u (u.label)}
        {@const r = mockRecipe(voicePicks[u.label])}
        <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
          <span class="font-sans text-sm font-semibold">{u.label}</span>
          <span><Badge variant="secondary">a voice clip</Badge></span>
          <span>
            <select class={cn(ADMIN_SELECT, 'w-full')} aria-label="Voice for {u.label}" bind:value={voicePicks[u.label]}>
              {#each MOCK_VOICE_RECIPES as vr (vr.id)}<option value={vr.id}>{vr.name}</option>{/each}
            </select>
          </span>
          <span class="grid gap-0.5 text-sm text-muted-foreground">
            <span>{r ? recipeLine(r) : ''}</span>
            <span class="text-xs">{u.note}</span>
          </span>
        </div>
      {/each}
    {/snippet}
  </AdminTableShell>
  {/if}
</div>
