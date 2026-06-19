<!--
  Expanded fold for one answer row: per-leg diagnostic detail (leg meta + trace/Graph-Run/copy
  actions, full question + answer, the Judge section, evidence recall, and the recalled
  facts/entities/episodes tables). Question/ideal/answer are clamped in the row above, so here
  they render in full. Single column for the memory recall leg; side-by-side for knowledge legs.
-->
<script lang="ts">
  import { Check, Copy, ExternalLink, LoaderCircle, Microscope } from '@lucide/svelte';
  import { type Snippet } from 'svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import EvalHighlight from '$lib/features/eval/shared/EvalHighlight.svelte';
  import { fmtCost, fmtEpisodeDate } from '$lib/features/eval/shared/eval-format';
  import {
    legLabel,
    markLabel,
    markTitle,
    markVariant,
    traceableLeg
  } from '$lib/features/eval/shared/eval-display';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type {
    EvidenceRecall,
    RecalledFact
  } from '$lib/features/knowledge/shared/knowledge-events';
  import type { EvalRow } from '$lib/features/eval/shared/eval-row';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';

  interface Props {
    r: EvalRow;
    legColumns: string[];
    /** Active answer-search term (highlights the answer surface). */
    searchTerm: string;
    /** Recalled-search term (highlights inside the recalled / evidence tables; '' = no highlight). */
    recalledTerm: string;
    traces: EvalTraces;
  }
  let { r, legColumns, searchTerm, recalledTerm, traces }: Props = $props();
</script>

<div class="grid gap-4 {legColumns.length > 1 ? 'md:grid-cols-2' : ''}">
  {#each legColumns as mode, legIdx (mode)}
    {#if r.legs[mode]}
      {@const leg = r.legs[mode]}
      <div class="grid content-start gap-2">
        <!-- First line: leg meta (left) · actions trace / recall / copy (right). -->
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-sans text-xs font-semibold">{legLabel(mode)}</span>
            <Badge variant={markVariant(leg.mark)} class="font-mono" title={markTitle(leg.mark)}>{leg.mark || '—'}</Badge>
            <span class="font-mono text-xs tabular-nums text-muted-foreground">{leg.elapsed_ms}ms</span>
            {#if leg.cost_usd}
              <span class="font-mono text-xs tabular-nums text-muted-foreground">{fmtCost(leg.cost_usd)}</span>
            {/if}
            {#if r.subcategory && legIdx === 0}
              <span class="font-sans text-xs text-muted-foreground">· {r.subcategory}</span>
            {/if}
          </div>
          <div class="flex flex-wrap items-center gap-1">
            {#if traceableLeg(mode) && leg.run_id}
              <button
                type="button"
                class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5 disabled:opacity-50"
                disabled={traces.traceLoadingRunId !== null}
                onclick={() => void traces.openTrace(leg.run_id!, r.gold, leg.answer)}
                title="Open the retrieval pipeline trace"
              >
                {#if traces.traceLoadingRunId === leg.run_id}
                  <LoaderCircle size={10} class="animate-spin" aria-hidden="true" />
                {:else}
                  <Microscope size={10} aria-hidden="true" />
                {/if}
                trace
              </button>
            {/if}
            {#if leg.run_id}
              <a
                class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                href={graphRunPageUrl(leg.run_id)}
                title="{legLabel(mode)} Graph Run"
              >
                <ExternalLink size={10} aria-hidden="true" />{mode}
              </a>
            {/if}
            {#if legIdx === 0}
              <button
                type="button"
                class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5"
                onclick={() => void traces.copyRowForAI(r)}
                title="Copy a Markdown brief (answer + judge + recalled facts inline, ledger-file pointers for the full traces) to paste into your AI agent"
              >
                {#if traces.copiedRow === r.index}
                  <Check size={10} aria-hidden="true" /> Copied
                {:else}
                  <Copy size={10} aria-hidden="true" /> Copy
                {/if}
              </button>
            {/if}
          </div>
        </div>
        <!-- Full question + answer (the row above clamps both). -->
        <div class="grid gap-1.5 text-xs leading-5">
          <div class="flex flex-wrap gap-2">
            <span class="min-w-[64px] text-muted-foreground">Question</span>
            <span class="flex-1 whitespace-pre-wrap text-foreground"><EvalHighlight text={r.question} term={searchTerm} /></span>
          </div>
          <div class="flex flex-wrap gap-2">
            <span class="min-w-[64px] text-muted-foreground">Answer</span>
            {#if leg.answer}
              <span class="flex-1 whitespace-pre-wrap text-foreground"><EvalHighlight text={leg.answer} term={searchTerm} /></span>
            {:else}
              <span class="flex-1 italic text-muted-foreground">— (no answer)</span>
            {/if}
          </div>
        </div>
        <!-- Judge — its own collapsible colored section (verdict + recall sufficiency + grounded +
             reason + quoted evidence). Recall + evidence are memory-only. -->
        {#if leg.mark || leg.reason}
          <details open class="overflow-hidden rounded-md border">
            <summary class="cursor-pointer select-none px-2 py-1 font-sans text-[11px] font-semibold uppercase tracking-wide bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200">
              Judge
            </summary>
            <div class="grid gap-2 border-t px-2.5 py-2 text-xs leading-5">
              <div class="flex flex-wrap items-center gap-2">
                <span class="min-w-[64px] text-muted-foreground">Verdict</span>
                {#if leg.mark}
                  <Badge variant={markVariant(leg.mark)} class="font-mono" title={markTitle(leg.mark)}>{leg.mark} {markLabel(leg.mark)}</Badge>
                {:else}
                  <span class="text-muted-foreground">—</span>
                {/if}
              </div>
              {#if mode === 'recall'}
                <div class="flex flex-wrap items-center gap-2">
                  <span class="min-w-[64px] text-muted-foreground">Recall</span>
                  {#if leg.recall_sufficient === false}
                    <Badge variant="destructive" title="The recalled context did NOT contain what was needed — a recall miss, not an answering miss.">recall miss</Badge>
                  {:else}
                    <Badge variant="success" title="The recalled facts/entities/episodes contained what was needed to answer.">sufficient</Badge>
                  {/if}
                </div>
              {/if}
              <div class="flex flex-wrap items-center gap-2">
                <span class="min-w-[64px] text-muted-foreground">Grounded</span>
                {#if leg.grounded === false}
                  <Badge variant="warning" title="The answer was not grounded in the provided context.">ungrounded</Badge>
                {:else}
                  <Badge variant="success" title="The answer is supported by the provided context.">grounded</Badge>
                {/if}
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
            </div>
          </details>
        {/if}
        <!-- Evidence recall (memory/recall leg, LoCoMo corpora). -->
        {#if mode === 'recall' && r.evidence_recall && r.evidence_recall.total > 0}
          {@render evidenceSection(r.evidence_recall)}
        {/if}
        <!-- Recalled memories: separate collapsible Facts / Entities / Episodes. -->
        {@render recalledTable(leg.recalled ?? [])}
      </div>
    {/if}
  {/each}
</div>

<!-- Evidence recall (LoCoMo): gold evidence episodes, each matched or missed against recall. -->
{#snippet evidenceSection(ev: EvidenceRecall)}
  <details open class="overflow-hidden rounded-md border">
    <summary class="cursor-pointer select-none px-2 py-1 font-sans text-[11px] font-semibold uppercase tracking-wide bg-indigo-100 text-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-200">
      Evidence recall ({ev.matched}/{ev.total})
    </summary>
    <div class="overflow-x-auto border-t">
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
  </details>
{/snippet}

<!-- Recalled items, split by kind into Facts / Entities / Episodes. -->
{#snippet recalledTable(items: RecalledFact[])}
  {@const facts = items.filter((r) => (r.kind ?? 'fact') === 'fact')}
  {@const entities = items.filter((r) => r.kind === 'entity')}
  {@const episodes = items.filter((r) => r.kind === 'episode')}
  {#if items.length === 0}
    <p class="text-xs italic text-muted-foreground">No recalled memories.</p>
  {:else}
    <div class="grid gap-2.5">
      {#if facts.length > 0}{@render factsTable(facts)}{/if}
      {#if entities.length > 0}{@render entitiesTable(entities)}{/if}
      {#if episodes.length > 0}{@render episodesTable(episodes)}{/if}
    </div>
  {/if}
{/snippet}

<!-- Reusable collapsible section: a <details> with a COLOR-CODED summary header wrapping a table. -->
{#snippet recalledSection(title: string, count: number, headerCls: string, body: Snippet)}
  <details open class="overflow-hidden rounded-md border">
    <summary class="cursor-pointer select-none px-2 py-1 font-sans text-[11px] font-semibold uppercase tracking-wide {headerCls}">
      {title} ({count})
    </summary>
    <div class="overflow-x-auto border-t">
      <table class="w-full border-collapse font-sans text-xs">
        {@render body()}
      </table>
    </div>
  </details>
{/snippet}

{#snippet factsTable(facts: RecalledFact[])}
  {#snippet body()}
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
        <tr class="border-t align-top">
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
  {/snippet}
  {@render recalledSection('Recalled facts', facts.length, 'bg-sky-100 text-sky-800 dark:bg-sky-950/60 dark:text-sky-200', body)}
{/snippet}

{#snippet entitiesTable(entities: RecalledFact[])}
  {#snippet body()}
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
  {/snippet}
  {@render recalledSection('Recalled entities', entities.length, 'bg-violet-100 text-violet-800 dark:bg-violet-950/60 dark:text-violet-200', body)}
{/snippet}

{#snippet episodesTable(episodes: RecalledFact[])}
  {#snippet body()}
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
  {/snippet}
  {@render recalledSection('Recalled episodes', episodes.length, 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-200', body)}
{/snippet}
