<script lang="ts">
  // Logs → AI usage (Phase 7b): the headline numbers for the days shown, each with its change
  // from the same span before. Billed (API keys) and the plans' estimate stay apart.
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import { change, short, usd, type Totals } from './ai-usage';

  let { now, before, compared }: { now: Totals; before: Totals; compared: string } = $props();

  const avg = (t: Totals) => (t.requests ? t.ms / t.requests / 1000 : 0);
  const failedPct = (t: Totals) => (t.requests ? (t.failed / t.requests) * 100 : 0);
  const tiles = $derived([
    { label: 'Billed', value: usd(now.billed), sub: 'on API keys', delta: change(now.billed, before.billed), up: 'bad' },
    { label: 'Plans at API prices', value: usd(now.estimate), sub: 'estimate: what calls on your plans would cost on an API key', delta: change(now.estimate, before.estimate), up: 'bad' },
    { label: 'Calls', value: short(now.requests), sub: `${short(now.plan)} on your plans · ${short(now.local)} on a home PC; questions, speech, transcription, images and embeddings`, delta: change(now.requests, before.requests), up: 'neutral' },
    { label: 'Tokens in / out', value: `${short(now.tokensIn)} / ${short(now.tokensOut)}`, sub: now.requests ? `${short(now.tokensIn / now.requests)} in per call` : '', delta: change(now.tokensIn + now.tokensOut, before.tokensIn + before.tokensOut), up: 'bad' },
    { label: 'Failed', value: short(now.failed), sub: `${failedPct(now).toFixed(1)}% · ${short(now.fellBack)} fell back`, delta: change(now.failed, before.failed), up: 'bad' },
    { label: 'Average time', value: `${avg(now).toFixed(1)} s`, sub: 'per call, fallbacks included', delta: change(avg(now), avg(before)), up: 'bad' }
  ] as const);
  const tone = (d: number | null, up: string) =>
    d === null || d === 0 || up === 'neutral'
      ? 'text-muted-foreground'
      : (d > 0) === (up === 'bad')
        ? 'text-amber-600 dark:text-amber-400'
        : 'text-emerald-600 dark:text-emerald-400';
</script>

<div class="grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
  {#each tiles as t (t.label)}
    <!-- The tile's explanation is a tooltip, so the numbers stand out. -->
    <div class="grid content-start gap-0.5 rounded-md border bg-card p-3 font-sans shadow-sm">
      <span class="flex items-center gap-1 text-xs text-muted-foreground"
        >{t.label}{#if t.sub}<FieldHelp text={t.sub} label="About {t.label}" />{/if}</span
      >
      <span class="text-xl font-semibold tabular-nums">{t.value}</span>
      <span class="text-[11px] {tone(t.delta, t.up)}" title="Compared with {compared}"
        >{t.delta === null
          ? 'nothing before to compare'
          : `${t.delta > 0 ? '▲' : t.delta < 0 ? '▼' : ''} ${Math.abs(t.delta)}% vs ${compared}`}</span
      >
    </div>
  {/each}
</div>
{#if now.unpriced}
  <!-- As HomeHiro's page said it: what the totals above leave at $0. -->
  <p class="font-sans text-xs text-muted-foreground">
    Counted at $0: {short(now.unpriced)} calls on {now.unpricedModels.join(', ')}, which have no price, or no token counts to
    work one out (Codex says only a total).
  </p>
{/if}
