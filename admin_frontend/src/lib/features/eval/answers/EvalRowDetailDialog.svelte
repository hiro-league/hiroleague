<!--
  Giant per-row detail dialog — all diagnostic tabs for one answer row: Overview (judge) /
  Evidence recall / Facts / Entities / Episodes / Trajectory, plus per-leg stats + action buttons.
  Single column for the memory recall leg; side-by-side for knowledge legs. Opened from the
  ANSWER TYPE cell or the slim fold's "Open details" button.

  Recalled tables (Facts/Entities/Episodes) render via EvalRecalledTable so they mirror what the
  answerer saw: ordered by score, capped-out items struck through, text trimmed to the eval caps
  (toggleable). A header search box filters + highlights across all tables.
-->
<script lang="ts">
  import { Scissors } from '@lucide/svelte';
  import SearchInput from '$lib/search/SearchInput.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import Highlight from '$lib/search/Highlight.svelte';
  import EvalLegActions from '$lib/features/eval/answers/EvalLegActions.svelte';
  import EvalRecalledTable from '$lib/features/eval/answers/EvalRecalledTable.svelte';
  import { fmtCost, fmtEpisodeDate } from '$lib/features/eval/shared/eval-format';
  import { markLabel, markTitle, markVariant } from '$lib/features/eval/shared/eval-display';
  import {
    ariaSort,
    DEFAULT_RECALL_RENDER,
    nextSort,
    recalledTabCount,
    sortArrow,
    sortRows,
    type SortState
  } from '$lib/features/eval/shared/eval-recall-render';
  import TraceTabs, { type TraceTab } from '$lib/features/graph-runs/shared/TraceTabs.svelte';
  import EvalRetrievalTrajectory from '$lib/features/eval/answers/EvalRetrievalTrajectory.svelte';
  import type {
    EvalRecallRender,
    EvidenceRecall,
    EvidenceRecallItem,
    RecalledFact
  } from '$lib/features/eval/shared/eval-events';
  import type { RetrievalLoop } from '$lib/features/eval/shared/retrieval-loop';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { RowDetailTraces } from '$lib/features/eval/state/eval-traces.svelte';

  interface Props {
    /** The row to show, or null when the dialog is closed. */
    row: EvalRow | null;
    legColumns: string[];
    /** Active answer-search term (highlights the answer surface). */
    searchTerm: string;
    /** Recalled-search term (seeds the dialog's own search box on open; '' = none). */
    recalledTerm: string;
    /** Narrow trace seam — the full Eval panel passes its `EvalTraces`; the Graph-Runs bridge
     *  passes a lighter controller (no Copy). */
    traces: RowDetailTraces;
    onClose: () => void;
  }
  let { row, legColumns, searchTerm, recalledTerm, traces, onClose }: Props = $props();

  type FoldTabKey = 'judge' | 'evidence' | 'facts' | 'entities' | 'episodes' | 'trajectory';

  // Per-leg active-tab selection. Keyed by leg mode so each side of a knowledge split stays put.
  let activeTabs = $state<Record<string, FoldTabKey>>({});
  // Search-id highlight driven from the Trajectory tab (dims non-matching facts).
  let trajectorySearchId = $state<number | null>(null);
  // Dialog-local search (filters + highlights the recalled / evidence tables). Seeded from the
  // externally-passed recalled term whenever a new row opens.
  let q = $state('');
  // Trim each recalled item's text to the eval cap (default ON = what the answerer saw) vs. full text.
  let trimmed = $state(true);
  // Evidence table sort (the recalled tables own their own sort state inside EvalRecalledTable).
  const EVIDENCE_DEFAULT_SORT: SortState = { key: 'score', dir: -1 };
  let evidenceSort = $state<SortState>({ ...EVIDENCE_DEFAULT_SORT });

  $effect(() => {
    void row;
    q = recalledTerm;
    evidenceSort = { ...EVIDENCE_DEFAULT_SORT };
  });

  const searching = $derived(q.trim().length > 0);
  // The header box, when typed in, also drives the Overview highlight; otherwise the external
  // answer-search term still highlights the answer surface.
  const overviewTerm = $derived(searching ? q : searchTerm);

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
    recalled: { facts: RecalledFact[]; entities: RecalledFact[]; episodes: RecalledFact[] },
    render: EvalRecallRender,
    term: string,
    trajectory: string | undefined
  ): TraceTab[] {
    const cap = render.max_elements_per_kind;
    const out: TraceTab[] = [];
    if (gold || leg.answer || leg.mark || leg.reason) out.push({ key: 'judge', label: 'Overview' });
    if (mode === 'recall' && evidence && evidence.total > 0)
      out.push({ key: 'evidence', label: 'Evidence recall', count: `${evidence.matched}/${evidence.total}` });
    if (recalled.facts.length > 0)
      out.push({ key: 'facts', label: 'Facts', count: recalledTabCount(recalled.facts, cap, term) });
    if (recalled.entities.length > 0)
      out.push({ key: 'entities', label: 'Entities', count: recalledTabCount(recalled.entities, cap, term) });
    if (recalled.episodes.length > 0)
      out.push({ key: 'episodes', label: 'Episodes', count: recalledTabCount(recalled.episodes, cap, term) });
    if (trajectory) out.push({ key: 'trajectory', label: 'Trajectory', count: trajectory });
    return out;
  }

  function activeFor(mode: string, tabs: TraceTab[]): FoldTabKey {
    const picked = activeTabs[mode];
    if (picked && tabs.some((t) => t.key === picked)) return picked;
    return (tabs[0]?.key as FoldTabKey) ?? 'judge';
  }

  // --- Evidence table sort/filter (kept inline — its shape differs from the recalled kinds). ------
  function evAccessor(it: EvidenceRecallItem, key: string): string | number {
    switch (key) {
      case 'status':
        return it.matched ? 1 : 0;
      case 'evidence':
        return `${it.dia_id || it.short_id || it.episode_id || ''} ${it.speaker || ''} ${it.text || ''}`;
      case 'when':
        return it.when || '';
      case 'via':
        return it.matched_via || '';
      case 'score':
        return typeof it.score === 'number' ? it.score : -1;
      default:
        return '';
    }
  }
  function evMatches(it: EvidenceRecallItem, term: string): boolean {
    const t = term.trim().toLowerCase();
    if (!t) return true;
    return [it.dia_id, it.short_id, it.episode_id, it.speaker, it.text, it.matched_via]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
      .includes(t);
  }
  const evidenceRows = (ev: EvidenceRecall): EvidenceRecallItem[] =>
    sortRows(ev.items.filter((it) => evMatches(it, q)), evidenceSort, evAccessor);
</script>

<Dialog.Root open={row !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="flex h-[90vh] flex-col sm:max-w-[min(96vw,1100px)]">
    {#if row}
      {@const r = row}
      <Dialog.Header>
        <Dialog.Title class="line-clamp-2 pr-8">{r.question}</Dialog.Title>
      </Dialog.Header>

      <!-- Dialog toolbar: search (filters + highlights the tables) · trimmed/full text toggle. -->
      <div class="flex items-center gap-2 border-b border-border pb-3">
        <SearchInput
          variant="inline"
          class="min-w-0 flex-1 border-input bg-muted/30 shadow-none"
          inputClass="text-xs text-foreground"
          bind:value={q}
          placeholder="Search facts, entities, episodes…"
        />
        <Button
          variant="outline"
          size="sm"
          aria-pressed={trimmed}
          title={trimmed
            ? 'Showing trimmed item text (as sent to eval). Click to show full text.'
            : 'Showing full item text. Click to trim it to the eval caps (as sent to eval).'}
          onclick={() => (trimmed = !trimmed)}
        >
          <Scissors size={14} aria-hidden="true" />
          <span class="text-xs">{trimmed ? 'Trimmed' : 'Full text'}</span>
        </Button>
      </div>

      <div class="grid flex-1 content-start gap-4 overflow-y-auto pr-1 {legColumns.length > 1 ? 'md:grid-cols-2' : ''}">
        {#each legColumns as mode, legIdx (mode)}
          {#if r.legs[mode]}
            {@const leg = r.legs[mode]}
            {@const recalled = recalledOf(leg.recalled)}
            {@const render = leg.render ?? DEFAULT_RECALL_RENDER}
            {@const tabs = tabsForLeg(mode, leg, r.gold, r.evidence_recall, recalled, render, q,
              leg.retrieval_loop ? `${leg.retrieval_loop.agent_turns}` : undefined)}
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
                <EvalRecalledTable rows={recalled.facts} kind="fact" {render} {trimmed} search={q} dimSearchId={trajectorySearchId} />
              {:else if active === 'entities'}
                <EvalRecalledTable rows={recalled.entities} kind="entity" {render} {trimmed} search={q} />
              {:else if active === 'episodes'}
                <EvalRecalledTable rows={recalled.episodes} kind="episode" {render} {trimmed} search={q} />
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

<!-- Overview — verdict/recall/grounded up top, then gold reference + judge reason, (memory only)
     quoted evidence, a divider, and finally our LLM answer. -->
{#snippet judgePane(mode: string, leg: EvalRow['legs'][string])}
  {#if row}
    {@const r = row}
    <div class="grid gap-2 text-xs leading-5">
      <!-- Verdict · recall sufficiency · grounded — moved to the top so the outcome reads first. -->
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
      <div class="flex flex-wrap gap-2">
        <span class="min-w-[64px] text-muted-foreground">Gold Answer</span>
        {#if r.gold}
          <span class="flex-1 whitespace-pre-wrap text-foreground"><Highlight text={r.gold} query={overviewTerm} /></span>
        {:else}
          <span class="flex-1 italic text-muted-foreground">— (no gold answer)</span>
        {/if}
      </div>
      <!-- Rubric (BEAM corpora): the required-element criteria the judge grades against, co-equal
           with the gold answer. Shown only when the corpus ships one (empty for LoCoMo/adam). -->
      {#if r.rubric.length}
        <div class="flex flex-wrap gap-2">
          <span class="min-w-[64px] text-muted-foreground">Rubric</span>
          <ul class="flex-1 list-disc space-y-0.5 pl-4 text-foreground">
            {#each r.rubric as criterion (criterion)}
              <li class="whitespace-pre-wrap"><Highlight text={criterion} query={overviewTerm} /></li>
            {/each}
          </ul>
        </div>
      {/if}
      {#if leg.reason}
        <div class="flex flex-wrap gap-2">
          <span class="min-w-[64px] text-muted-foreground">Reason</span>
          <span class="flex-1 text-foreground"><Highlight text={leg.reason} query={overviewTerm} /></span>
        </div>
      {/if}
      {#if mode === 'recall'}
        <div class="flex flex-wrap gap-2">
          <span class="min-w-[64px] text-muted-foreground">Evidence</span>
          {#if leg.evidence}
            <span class="flex-1 whitespace-pre-wrap border-l-2 border-sky-400 bg-muted/40 px-2 py-1 font-mono text-[11px] leading-5 dark:border-sky-500"><Highlight text={leg.evidence} query={overviewTerm} /></span>
          {:else}
            <span class="italic text-muted-foreground">— none quoted</span>
          {/if}
        </div>
      {/if}
      <!-- Divider before our answer, so the model's output is visually separated from the references. -->
      <hr class="my-1 border-border" />
      <div class="flex flex-wrap gap-2">
        <span class="min-w-[64px] text-muted-foreground">Our Answer</span>
        {#if leg.answer}
          <span class="flex-1 whitespace-pre-wrap text-foreground"><Highlight text={leg.answer} query={overviewTerm} /></span>
        {:else}
          <span class="flex-1 italic text-muted-foreground">— (no answer)</span>
        {/if}
      </div>
    </div>
  {/if}
{/snippet}

<!-- Evidence recall (LoCoMo): gold evidence episodes, each matched or missed against recall.
     Sticky sortable header; filtered + highlighted by the dialog search (no cap/trim — evidence is
     gold-vs-recall, not items sent to the answerer). -->
{#snippet evTh(key: string, label: string, align: 'left' | 'right', title: string)}
  <th
    class="sticky top-0 z-10 cursor-pointer select-none bg-muted px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground {align === 'right' ? 'text-right' : 'text-left'}"
    aria-sort={ariaSort(evidenceSort, key)}
    title={title || 'Click to sort'}
    onclick={() => (evidenceSort = nextSort(evidenceSort, key, EVIDENCE_DEFAULT_SORT))}
  >
    {label}<span class="ml-1 text-[9px] text-primary">{sortArrow(evidenceSort, key)}</span>
  </th>
{/snippet}

{#snippet evidencePane(ev: EvidenceRecall)}
  <div class="max-h-[60vh] overflow-auto rounded-md border">
    <table class="w-full border-collapse font-sans text-xs">
      <thead>
        <tr>
          {@render evTh('status', 'Status', 'left', '')}
          {@render evTh('evidence', 'Evidence', 'left', '')}
          {@render evTh('when', 'When', 'left', '')}
          {@render evTh('via', 'Via', 'left', '')}
          {@render evTh('score', 'Score', 'right', '')}
        </tr>
      </thead>
      <tbody>
        {#each evidenceRows(ev) as it, i (it.episode_id || i)}
          <tr class="border-t align-top">
            <td class="whitespace-nowrap px-2 py-1">
              {#if it.matched}
                <Badge variant="success">matched</Badge>
              {:else}
                <Badge variant="destructive">missed</Badge>
              {/if}
            </td>
            <td class="max-w-[32rem] px-2 py-1">
              <span class="font-mono text-[11px] text-muted-foreground"><Highlight text={it.dia_id || it.short_id || it.episode_id} query={q} /></span>
              {#if it.text}
                <span class="line-clamp-3" title={it.text}>{#if it.speaker}<span class="font-semibold"><Highlight text={it.speaker} query={q} />:</span> {/if}<Highlight text={it.text} query={q} /></span>
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
        {#if evidenceRows(ev).length === 0}
          <tr><td class="px-2 py-3 text-center text-muted-foreground" colspan="5">No evidence matches “{q}”.</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
{/snippet}
