<script lang="ts">
  import { errorMessage } from '$kit/api/client';
  /**
   * Preferences → General → Spoken clips (Phase 7b): what the clip cache holds now and what it saved, beside
   * its size setting (`voice.clip_cache_mb`). Clips the extensions had spoken (an alert, a Speak node) are
   * kept, so the same words in the same voice are said again without paying for them.
   */
  import { onMount } from 'svelte';
  import { getClipCache, type ClipCacheStats } from '$lib/api/voice';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { dateTime } from '$lib/format/time';

  let { ctrl }: { ctrl: PreferencesController } = $props();

  let stats = $state<ClipCacheStats | null>(null);
  let error = $state<string | null>(null);
  onMount(async () => {
    // Step 1d: a failed request throws (answers are the data itself; there is no {ok, error} to test).
    try {
      stats = await getClipCache();
    } catch (err) {
      error = errorMessage(err);
    }
  });

  const maxMb = $derived(Number((ctrl.draft as { voice?: { clip_cache_mb?: number } }).voice?.clip_cache_mb ?? 0));
  const usedMb = $derived((stats?.bytes ?? 0) / 1024 / 1024);
  const pct = $derived(maxMb > 0 ? Math.min(100, Math.round((usedMb / maxMb) * 100)) : 0);
</script>

<div class="grid content-start gap-1.5 font-sans">
  <span class="text-sm font-medium">Now</span>
  {#if error}
    <span class="text-xs text-destructive">{error}</span>
  {:else if stats}
    <span class="h-2 w-full overflow-hidden rounded-full bg-muted"
      ><span class="block h-full rounded-full bg-primary" style:width="{pct}%"></span></span
    >
    <span class="text-xs text-muted-foreground">
      {usedMb.toFixed(1)} MB, {stats.clips} clips · said again {stats.hits} times, saved ${stats.saved_usd.toFixed(2)}{stats.since
        ? ` since ${dateTime(stats.since)}`
        : ''}
    </span>
  {:else}
    <span class="text-xs text-muted-foreground">Reading…</span>
  {/if}
</div>
