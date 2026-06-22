<!--
  Giant per-row detail dialog — all diagnostic tabs for one answer row: Overview (judge) /
  Evidence recall / Facts / Entities / Episodes / Trajectory, plus per-leg stats + action buttons.
  Single column for the memory recall leg; side-by-side for knowledge legs. Opened from the
  ANSWER TYPE cell or the slim fold's "Open details" button.
-->
<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import EvalHighlight from '$lib/features/eval/shared/EvalHighlight.svelte';
  import EvalLegActions from '$lib/features/eval/answers/EvalLegActions.svelte';
  import { fmtCost, fmtEpisodeDate } from '$lib/features/eval/shared/eval-format';
  import { markLabel, markTitle, markVariant } from '$lib/features/eval/shared/eval-display';
  import TraceTabs, { type TraceTab } from '$lib/features/graph-runs/shared/TraceTabs.svelte';
  import EvalRetrievalTrajectory from '$lib/features/eval/answers/EvalRetrievalTrajectory.svelte';
  import type { EvidenceRecall, RecalledFact } from '$lib/features/eval/shared/eval-events';
  import type { RetrievalLoop } from '$lib/features/eval/shared/retrieval-loop';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';

  interface Props {
    /** The row to show, or null when the dialog is closed. */
    row: EvalRow | null;
    legColumns: string[];
    /** Active answer-search term (highlights the answer surface). */
    searchTerm: string;
    /** Recalled-search term (highlights inside the recalled / evidence tables; '' = no highlight). */
    recalledTerm: string;
    traces: EvalTraces;
    onClose: () => void;
  }
  let { row, legColumns, searchTerm, recalledTerm, traces, onClose }: Props = $props();

  type FoldTabKey = 'judge' | 'evidence' | 'facts' | 'entities' | 'episodes' | 'trajectory';

  // Per-leg active-tab selection. Keyed by leg mode so each side of a knowledge split stays put.
  let activeTabs = $state<Record<string, FoldTabKey>>({});
  // Search-id highlight driven from the Trajectory tab (dims non-matching facts).
  let trajectorySearchId = $state<number | null>(null);

  function recalledOf(items: RecalledFact[] | undefined) {
    const arr = items ?? [];
    return {
      facts: arr.filter((x) => (x.kind ?? 'fact') === 'fact'),
      entities: arr.filter((x) => x.kind === 'entity'),
      episodes: arr.filter((x) => x.kind === 'episode')
    };
  }

  function tabsForLeg(
    mode: string,
    leg: { answer?: string | null; mark?: string | null; reason?: string | null; retrieval_loop?: RetrievalLoop },
    gold: string | undefined,
    evidence: EvidenceRecall | null | undefined,
    counts: { facts: number; entities: number; episodes: number; trajectory?: string }
  ): TraceTab[] {
    const out: TraceTab[] = [];
    if (gold || leg.answer || leg.mark || leg.reason) out.push({ key: 'judge', label: 'Overview' });
    if (mode === 'recall' && evidence && evidence.total > 0)
      out.push({ key: 'evidence', label: 'Evidence recall', count: `${evidence.matched}/${evidence.total}` });
    if (counts.facts > 0) out.push({ key: 'facts', label: 'Facts', count: String(counts.facts) });
    if (counts.entities > 0) out.push({ key: 'entities', label: 'Entities', count: String(counts.entities) });
    if (counts.episodes > 0) out.push({ key: 'episodes', label: 'Episodes', count: String(counts.episodes) });
    if (counts.trajectory) out.push({ key: 'trajectory', label: 'Trajectory', count: counts.trajectory });
    return out;
  }

  function activeFor(mode: string, tabs: TraceTab[]): FoldTabKey {
    const picked = activeTabs[mode];
    if (picked && tabs.some((t) => t.key === picked)) return picked;
    return (tabs[0]?.key as FoldTabKey) ?? 'judge';
  }
</script>

<Dialog.Root open={row !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="flex h-[90vh] flex-col sm:max-w-[min(96vw,1100px)]">
    {#if row}
      {@const r = row}
      <Dialog.Header>
        <Dialog.Title class="line-clamp-2 pr-8">{r.question}</Dialog.Title>
      </Dialog.Header>

      <div class="grid flex-1 content-start gap-4 overflow-y-auto pr-1 {legColumns.length > 1 ? 'md:grid-cols-2' : ''}">
        {#each legColumns as mode, legIdx (mode)}
          {#if r.legs[mode]}
            {@const leg = r.legs[mode]}
            {@const recalled = recalledOf(leg.recalled)}
            {@const tabs = tabsForLeg(mode, leg, r.gold, r.evidence_recall, {
              facts: recalled.facts.length,
              entities: recalled.entities.length,
              episodes: recalled.episodes.length,
              trajectory: leg.retrieval_loop ? `${leg.retrieval_loop.agent_turns}` : undefined
            })}
            {@const active = activeFor(mode, tabs)}
            <div class="grid content-start gap-2">
              <!-- Tabs (left) · leg meta + trace/Graph-Run/copy (right), then the active tab below. -->
              <div class="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
                {#if tabs.length > 0}
                  <TraceTabs
                    {tabs}
                    {active}
                    onSelect={(k) => (activeTabs = { ...activeTabs, [mode]: k as FoldTabKey })}
                    ariaLabel="Diagnostic detail tabs"
                    variant="lanes"
                  />
                {:else}
                  <span></span>
                {/if}
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-mono text-xs tabular-nums text-muted-foreground">{leg.elapsed_ms}ms</span>
                  {#if leg.cost_usd}
                    <span class="font-mono text-xs tabular-nums text-muted-foreground">{fmtCost(leg.cost_usd)}</span>
                  {/if}
                  {#if r.subcategory && legIdx === 0}
                    <span class="font-sans text-xs text-muted-foreground">· {r.subcategory}</span>
                  {/if}
                  <EvalLegActions {r} {mode} {leg} {legIdx} {traces} />
                </div>
              </div>
              {#if active === 'judge'}
                {@render judgePane(mode, leg)}
              {:else if active === 'evidence' && r.evidence_recall}
                {@render evidencePane(r.evidence_recall)}
              {:else if active === 'facts'}
                {@render factsPane(recalled.facts, trajectorySearchId)}
              {:else if active === 'entities'}
                {@render entitiesPane(recalled.entities)}
              {:else if active === 'episodes'}
                {@render episodesPane(recalled.episodes)}
              {:else if active === 'trajectory' && leg.retrieval_loop}
                <EvalRetrievalTrajectory
                  loop={leg.retrieval_loop}
                  facts={recalled.facts}
                  onSearchSelect={(sid) => (trajectorySearchId = sid)}
                  onOpenTrace={leg.run_id
                    ? (sid) => void traces.openTraceForSubQuery(leg.run_id!, sid, r.gold, leg.answer)
                    : undefined}
                  loadingSid={traces.traceLoadingSid}
                />
              {/if}
            </div>
          {/if}
        {/each}
      </div>

      <Dialog.Footer>
        <Button variant="outline" onclick={onClose}>Close</Button>
      </Dialog.Footer>
    {/if}
  </Dialog.Content>
</Dialog.Root>

<!-- Overview — gold reference answer, verdict + recall sufficiency + grounded, judge reason,
     (memory only) quoted evidence, then our LLM answer. -->
{#snippet judgePane(mode: string, leg: EvalRow['legs'][string])}
  {#if row}
    {@const r = row}
    <div class="grid gap-2 text-xs leading-5">
      <div class="flex flex-wrap gap-2">
        <span class="min-w-[64px] text-muted-foreground">Gold Answer</span>
        {#if r.gold}
          <span class="flex-1 whitespace-pre-wrap text-foreground"><EvalHighlight text={r.gold} term={searchTerm} /></span>
        {:else}
          <span class="flex-1 italic text-muted-foreground">— (no gold answer)</span>
        {/if}
      </div>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="min-w-[64px] text-muted-foreground">Verdict</span>
          {#if leg.mark}
            <Badge variant={markVariant(leg.mark, r.is_negative_control)} class="font-mono" title={markTitle(leg.mark, r.is_negative_control)}>{leg.mark} {markLabel(leg.mark, r.is_negative_control)}</Badge>
          {:else}
            <span class="text-muted-foreground">—</span>
          {/if}
        </div>
        {#if mode === 'recall'}
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-muted-foreground">Recall</span>
            {#if leg.recall_sufficient === false}
              <Badge variant="destructive" title="The recalled context did NOT contain what was needed — a recall miss, not an answering miss.">recall miss</Badge>
            {:else}
              <Badge variant="success" title="The recalled facts/entities/episodes contained what was needed to answer.">sufficient</Badge>
            {/if}
          </div>
        {/if}
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-muted-foreground">Grounded</span>
          {#if leg.grounded === false}
            <Badge variant="warning" title="The answer was not grounded in the provided context.">ungrounded</Badge>
          {:else}
            <Badge variant="success" title="The answer is supported by the provided context.">grounded</Badge>
          {/if}
        </div>
      </div>
      {#if leg.reason}
        <div class="flex flex-wrap gap-2">
          <span class="min-w-[64px] text-muted-foreground">Reason</span>
          <span class="flex-1 text-foreground"><EvalHighlight text={leg.reason} term={searchTerm} /></span>
        </div>
      {/if}
      {#if mode === 'recall'}
        <div class="flex flex-wrap gap-2">
          <span class="min-w-[64px] text-muted-foreground">Evidence</span>
          {#if leg.evidence}
            <span class="flex-1 whitespace-pre-wrap border-l-2 border-sky-400 bg-muted/40 px-2 py-1 font-mono text-[11px] leading-5 dark:border-sky-500"><EvalHighlight text={leg.evidence} term={searchTerm} /></span>
          {:else}
            <span class="italic text-muted-foreground">— none quoted</span>
          {/if}
        </div>
      {/if}
      <div class="flex flex-wrap gap-2">
        <span class="min-w-[64px] text-muted-foreground">Our Answer</span>
        {#if leg.answer}
          <span class="flex-1 whitespace-pre-wrap text-foreground"><EvalHighlight text={leg.answer} term={searchTerm} /></span>
        {:else}
          <span class="flex-1 italic text-muted-foreground">— (no answer)</span>
        {/if}
      </div>
    </div>
  {/if}
{/snippet}

<!-- Evidence recall (LoCoMo): gold evidence episodes, each matched or missed against recall. -->
{#snippet evidencePane(ev: EvidenceRecall)}
  <div class="overflow-x-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-xs">
      <thead class="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
        <tr>
          <th class="px-2 py-1 text-left">Status</th>
          <th class="px-2 py-1 text-left">Evidence</th>
          <th class="px-2 py-1 text-left">When</th>
          <th class="px-2 py-1 text-left">Via</th>
          <th class="px-2 py-1 text-right">Score</th>
        </tr>
      </thead>
      <tbody>
        {#each ev.items as it, i (it.episode_id || i)}
          <tr class="border-t align-top">
            <td class="whitespace-nowrap px-2 py-1">
              {#if it.matched}
                <Badge variant="success">matched</Badge>
              {:else}
                <Badge variant="destructive">missed</Badge>
              {/if}
            </td>
            <td class="max-w-[32rem] px-2 py-1">
              <span class="font-mono text-[11px] text-muted-foreground"><EvalHighlight text={it.dia_id || it.short_id || it.episode_id} term={recalledTerm} /></span>
              {#if it.text}
                <span class="line-clamp-3" title={it.text}>{#if it.speaker}<span class="font-semibold"><EvalHighlight text={it.speaker} term={recalledTerm} />:</span> {/if}<EvalHighlight text={it.text} term={recalledTerm} /></span>
              {:else}
                <span class="block italic text-muted-foreground">(episode text unavailable)</span>
              {/if}
            </td>
            <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{it.when ? fmtEpisodeDate(it.when) : '—'}</td>
            <td class="px-2 py-1">
              {#if it.matched_via}<Badge variant="outline" class="font-sans normal-case">{it.matched_via}</Badge>{:else}<span class="text-muted-foreground">—</span>{/if}
            </td>
            <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">{it.score != null ? it.score.toFixed(3) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/snippet}

{#snippet factsPane(facts: RecalledFact[], selectedSearchId: number | null)}
  <div class="overflow-x-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-xs">
      <thead class="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
        <tr>
          <th class="px-2 py-1 text-left">Fact</th>
          <th class="px-2 py-1 text-left">Relationship</th>
          <th class="px-2 py-1 text-left">Valid from</th>
          <th class="px-2 py-1 text-left">Invalid at</th>
          <th class="px-2 py-1 text-left">Status</th>
          <th class="px-2 py-1 text-right">Score</th>
        </tr>
      </thead>
      <tbody>
        {#each facts as f, i (i)}
          {@const dimmed = selectedSearchId != null && f.search_id != null && f.search_id !== selectedSearchId}
          <tr class="border-t align-top {dimmed ? 'opacity-35' : ''}">
            <td class="max-w-[24rem] px-2 py-1">
              <span class="line-clamp-3" title={f.fact || f.memory}><EvalHighlight text={f.fact || f.memory} term={recalledTerm} /></span>
            </td>
            <td class="px-2 py-1 font-mono text-[11px] text-muted-foreground">{#if f.name}<EvalHighlight text={f.name} term={recalledTerm} />{:else}—{/if}</td>
            <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{f.valid_at || '—'}</td>
            <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{f.invalid_at || '—'}</td>
            <td class="px-2 py-1">
              {#if f.superseded}
                <Badge variant="warning">superseded</Badge>
              {:else}
                <Badge variant="success">active</Badge>
              {/if}
            </td>
            <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
              {f.score != null ? f.score.toFixed(3) : '—'}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/snippet}

{#snippet entitiesPane(entities: RecalledFact[])}
  <div class="overflow-x-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-xs">
      <thead class="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
        <tr>
          <th class="px-2 py-1 text-left">Entity</th>
          <th class="px-2 py-1 text-left">Type</th>
          <th class="px-2 py-1 text-right">Score</th>
        </tr>
      </thead>
      <tbody>
        {#each entities as e, i (i)}
          <tr class="border-t align-top">
            <td class="max-w-[28rem] px-2 py-1">
              {#if e.name}<span class="font-semibold"><EvalHighlight text={e.name} term={recalledTerm} /></span>{/if}
              <span class="line-clamp-2 text-muted-foreground" title={e.summary || e.memory}><EvalHighlight text={e.summary || e.memory} term={recalledTerm} /></span>
            </td>
            <td class="px-2 py-1">
              {#if e.entity_type}<Badge variant="outline" class="font-sans normal-case">{e.entity_type}</Badge>{:else}<span class="text-muted-foreground">—</span>{/if}
            </td>
            <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
              {e.score != null ? e.score.toFixed(3) : '—'}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/snippet}

{#snippet episodesPane(episodes: RecalledFact[])}
  <div class="overflow-x-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-xs">
      <thead class="bg-muted/40 text-[10px] uppercase tracking-wide text-muted-foreground">
        <tr>
          <th class="px-2 py-1 text-left">Episode</th>
          <th class="px-2 py-1 text-left">When</th>
          <th class="px-2 py-1 text-right">Score</th>
        </tr>
      </thead>
      <tbody>
        {#each episodes as ep, i (i)}
          <tr class="border-t align-top">
            <td class="max-w-[32rem] px-2 py-1">
              <span class="line-clamp-3" title={ep.memory}><EvalHighlight text={ep.memory} term={recalledTerm} /></span>
            </td>
            <td class="px-2 py-1 font-mono text-[11px] tabular-nums">{ep.valid_at ? fmtEpisodeDate(ep.valid_at) : '—'}</td>
            <td class="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
              {ep.score != null ? ep.score.toFixed(3) : '—'}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/snippet}
