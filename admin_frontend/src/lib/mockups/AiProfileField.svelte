<script lang="ts">
  /**
   * Preferences (Phase 7b MOCKUP): where a job had a model picker plus a tuning preset, it now picks
   * ONE AI profile (the model, its settings, budget and fallback in one recipe, kept in Catalog → AI
   * profiles). The same choice shows in Catalog → Uses under Hiro. Also the default voice, as a
   * voice recipe. Nothing is saved.
   */
  import { ExternalLink } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import {
    MOCK_DEFAULT_PROFILES,
    MOCK_VOICE_RECIPES,
    mockProfile,
    mockRecipe,
    profileLine,
    recipeLine,
    type MockJob
  } from './phase7b';

  let { job = null, voice = false, heading = '' }: { job?: MockJob | null; voice?: boolean; heading?: string } = $props();

  let pick = $state(voice ? 'v-hiro' : (job?.profileId ?? ''));
  const p = $derived(voice ? null : mockProfile(pick));
  const r = $derived(voice ? mockRecipe(pick) : null);
  const label = $derived(heading || (voice ? "Hiro's voice" : `${job?.label ?? 'Job'}: AI profile`));
</script>

<div class="grid gap-1.5 rounded-md border border-dashed border-amber-500/50 bg-amber-500/5 p-3">
  <FormField label={label}>
    <select class={cn(ADMIN_SELECT, 'w-full')} bind:value={pick}>
      {#if voice}
        {#each MOCK_VOICE_RECIPES as vr (vr.id)}<option value={vr.id}>{vr.name}</option>{/each}
      {:else}
        {#each MOCK_DEFAULT_PROFILES as dp (dp.id)}<option value={dp.id}>{dp.name}</option>{/each}
      {/if}
    </select>
  </FormField>
  <p class="font-sans text-xs text-muted-foreground">{p ? profileLine(p) : r ? recipeLine(r) : ''}</p>
  <p class="flex flex-wrap items-center gap-2 font-sans text-xs">
    <Badge variant="outline" class="border-amber-500/60 text-amber-700 dark:text-amber-300">Mockup</Badge>
    <span class="text-muted-foreground">
      {voice ? 'Was: Default text-to-speech model.' : `Was: ${job?.today ?? ''}.`}
    </span>
    <a class="inline-flex items-center gap-1 text-primary hover:underline" href={voice ? '/catalog/?tab=voices' : '/catalog/?tab=profiles'}
      >{voice ? 'Edit voices' : 'Edit AI profiles'} <ExternalLink size={11} /></a
    >
  </p>
</div>
