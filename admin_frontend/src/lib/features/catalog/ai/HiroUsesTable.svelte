<script lang="ts">
  /**
   * Catalog → Profiles → Uses, Hiro's own group (Phase 7b step 5): each of the core's jobs (from
   * `GET /api/ai/profiles` `jobs`) points at ONE AI profile, like an extension's use does — picking one
   * PATCHes the job's preference field. Unset, a job borrows the profile of the job it falls back to.
   * Then "Speaking": Hiro's own voice → a voice profile (`voice.hiro_profile`). Same table as the
   * extensions' groups. A job can't use a plan tool's model (claude_code:* / codex:*), so those
   * profiles aren't offered.
   */
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { isPlanModel } from '$lib/catalog/hiro-jobs';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import Notice from '$kit/ui/notice.svelte';
  import { cn } from '$lib/utils';
  import type { VoiceController } from '$lib/features/catalog/voice/voice-controller.svelte';
  import type { AiController } from './ai-controller.svelte';
  import { chainLabel, fallbackChain, findModel } from './ai-profile-rules';
  import type { AiJob } from './ai-types';

  let { ai, voice }: { ai: AiController; voice: VoiceController } = $props();

  const GRID = 'minmax(200px,1.1fr) minmax(170px,0.9fr) minmax(200px,1fr) minmax(240px,1.4fr)';
  // What a job's model must handle (from the jobs' own descriptions): a picture to read, or a reply in JSON.
  const NEEDS: Record<string, string[]> = {
    vision: ['a picture'],
    rewrite: ['JSON'],
    graph_extraction: ['JSON']
  };

  const jobProfiles = $derived(ai.profiles.filter((p) => !isPlanModel(p.model)));
  let voiceError = $state<string | null>(null);
  let voiceBusy = $state(false);

  function modelWords(model: string | null): string {
    if (!model) return '';
    return findModel(ai.providers, model).model?.name ?? model;
  }

  function note(job: AiJob): { text: string; warn: boolean } {
    const profile = job.profileId ? ai.profiles.find((p) => p.id === job.profileId) : undefined;
    if (job.profileId && !profile) return { text: `No AI profile "${job.profileId}": pick another.`, warn: true };
    if (profile) {
      const { provider, model } = ai.modelOf(profile);
      const words = [profile.server?.providerLabel || provider?.label, model?.name ?? profile.model].filter(Boolean).join(' · ');
      const notReady = profile.server?.notReady ?? provider?.notReady;
      if (notReady) return { text: `${words}. ${notReady}`, warn: true };
      const chain = chainLabel(ai.profiles, fallbackChain(ai.profiles, profile.id));
      // chainLabel starts with "→ "; drop it after "falls back to".
      return { text: chain ? `${words} · falls back to ${chain.slice(2)}` : words, warn: false };
    }
    const parent = ai.jobLabel(job.fallsBackTo);
    // Hiro's chat has nothing to fall back to: unset, Hiro only answers with a character's own profiles.
    if (!parent) return { text: job.id === 'vision' ? "Not set: pictures aren't read." : 'Not set: off.', warn: job.id === 'chat' };
    return job.model
      ? { text: `Falls back to ${parent} (${modelWords(job.model)}).`, warn: false }
      : { text: `Falls back to ${parent}, which can't answer now.`, warn: true };
  }

  const hiroVoice = $derived(voice.profiles.find((p) => p.id === voice.hiroProfile));

  async function pickVoice(id: string) {
    voiceBusy = true;
    voiceError = await voice.setHiroProfile(id || null);
    voiceBusy = false;
  }
</script>

<div class="grid gap-2">
  <div>
    <h4 class="font-sans text-base font-semibold text-primary">
      Hiro <span class="text-sm font-normal text-muted-foreground">· {ai.jobs.length} jobs</span>
    </h4>
    <p class="text-xs text-muted-foreground">
      The core's own work. Each job asks with one AI profile; not set, it borrows the profile of the job it falls back to.
    </p>
  </div>
  <AdminTableShell layout="grid" minWidth={900} gridColumns={GRID}>
    {#snippet headRow()}
      <span>Job</span>
      <span>Needs</span>
      <span>Profile</span>
      <span>Note</span>
    {/snippet}
    {#snippet body()}
      {#each ai.jobs as job (job.id)}
        {@const n = note(job)}
        {@const known = !job.profileId || jobProfiles.some((p) => p.id === job.profileId)}
        <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
          <span class="font-sans text-sm font-semibold">{job.label}</span>
          <span class="flex flex-wrap content-start gap-1">
            {#each NEEDS[job.id] ?? [] as need (need)}
              <Badge variant={need === 'JSON' ? 'outline' : 'secondary'}>{need}</Badge>
            {/each}
          </span>
          <span>
            <select
              class={cn(ADMIN_SELECT, 'w-full')}
              aria-label={`Profile for ${job.label}`}
              value={job.profileId ?? ''}
              disabled={ai.jobBusy[job.id]}
              onchange={(event) => void ai.setJobProfile(job.id, event.currentTarget.value)}
            >
              <option value="">Not set</option>
              {#each jobProfiles as p (p.id)}
                <option value={p.id}>{p.name}</option>
              {/each}
              {#if !known}<option value={job.profileId}>{job.profileId} (missing)</option>{/if}
            </select>
          </span>
          <span class={cn('text-sm', n.warn ? 'text-amber-700 dark:text-amber-300' : 'text-muted-foreground')}>
            {n.text}
          </span>
        </div>
      {/each}
    {/snippet}
  </AdminTableShell>

  <div class="mt-3">
    <h4 class="font-sans text-base font-semibold text-primary">
      Speaking <span class="text-sm font-normal text-muted-foreground">· 1 use</span>
    </h4>
    <p class="text-xs text-muted-foreground">
      The voice profile Hiro speaks its voice replies with. A character with voice profiles of its own speaks with those first.
    </p>
  </div>
  {#if voiceError}<Notice message={voiceError} />{/if}
  <AdminTableShell layout="grid" minWidth={900} gridColumns={GRID}>
    {#snippet headRow()}
      <span>Use</span>
      <span>Needs</span>
      <span>Voice</span>
      <span>Note</span>
    {/snippet}
    {#snippet body()}
      <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
        <span class="font-sans text-sm font-semibold">Hiro's voice</span>
        <span><Badge variant="secondary">a voice clip</Badge></span>
        <span>
          <select
            class={cn(ADMIN_SELECT, 'w-full')}
            aria-label="Voice for Hiro's voice replies"
            value={voice.hiroProfile ?? ''}
            disabled={voiceBusy}
            onchange={(e) => void pickVoice(e.currentTarget.value)}
          >
            <option value="">None</option>
            {#each voice.profiles as vp (vp.id)}<option value={vp.id}>{vp.label}</option>{/each}
            {#if voice.hiroProfile && !hiroVoice}
              <option value={voice.hiroProfile}>{voice.hiroProfile} (missing)</option>
            {/if}
          </select>
        </span>
        <span class="text-sm text-muted-foreground">
          {#if hiroVoice}{hiroVoice.line}{:else}Hiro doesn't speak its replies until a voice is picked.{/if}
        </span>
      </div>
    {/snippet}
  </AdminTableShell>
</div>
