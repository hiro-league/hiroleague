<!--
  Execute pane — configure + launch a run, in two parts: Ingestion (build options + read-only
  ingestion settings) and Question answering (answer/recall options + read-only settings). Each
  part's button row owns its run action (Ingest / Eval Questions) + the Cancel control while in
  flight. Below: the Cost strip and the live Activity terminal. The corpus selector lives in the
  router (shared by all panes); settings are editable via the Graph engine link.
-->
<script lang="ts">
  import { base } from '$app/paths';
  import { Download, LoaderCircle, Play, Settings2, Square } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import KnowledgeCollapsibleSectionCard from '$lib/features/knowledge/shared/KnowledgeCollapsibleSectionCard.svelte';
  import EvalTerminal from '$lib/features/eval/view/EvalTerminal.svelte';
  import EvalRebuildConfirmDialog from '$lib/features/eval/view/EvalRebuildConfirmDialog.svelte';
  import EvalCostStrip from '$lib/features/eval/execute/EvalCostStrip.svelte';
  import { activityHeaderLine, buildActivityLines } from '$lib/features/eval/shared/eval-activity';
  import { legLabel } from '$lib/features/eval/shared/eval-display';
  import { preferenceTabHref } from '$lib/features/preferences/shared/preferences-tabs';
  import {
    answerPromptLabelFor,
    answerPromptOptions as answerPromptOptionsFn,
    ingestKnobs as ingestKnobsFn,
    modelLines as modelLinesFn,
    recallKnobs as recallKnobsFn,
    type ModelLine,
    type Param
  } from '$lib/features/eval/shared/eval-engine-params';
  import { EVAL_ALL_LEGS, type EvalModel } from '$lib/features/eval/state/eval-model.svelte';
  import type { EvalTrackConfig } from '$lib/features/eval/shared/eval-tracks';
  import type { EvalTraces } from '$lib/features/eval/state/eval-traces.svelte';
  import type { WorkspacePreferences } from '$lib/api/preferences';
  import { ADMIN_INPUT, ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  interface Props {
    eval_: EvalModel;
    cfg: EvalTrackConfig;
    /** Loaded once by the router (shared with the Copy-for-AI engine line); read-only here. */
    prefs: WorkspacePreferences | null;
    /** For the Cost strip's "Ingest pipeline" trace button. */
    traces: EvalTraces;
  }
  let { eval_, cfg, prefs, traces }: Props = $props();

  // --- Engine params (read-only Settings columns) -------------------------------------------
  const answerPromptOptions = $derived(answerPromptOptionsFn(prefs));
  const answerPromptLabel = $derived(answerPromptLabelFor(answerPromptOptions, eval_.answerPromptId));
  const modelLines = $derived<ModelLine[]>(prefs ? modelLinesFn(prefs, cfg) : []);
  const ingestModels = $derived(modelLines.filter((m) => m.group === 'ingest'));
  const recallModels = $derived(modelLines.filter((m) => m.group === 'recall'));
  const ingestKnobs = $derived<Param[]>(prefs ? ingestKnobsFn(prefs, cfg) : []);
  const recallKnobs = $derived<Param[]>(prefs ? recallKnobsFn(prefs, cfg, answerPromptLabel) : []);

  // --- Live activity feed -------------------------------------------------------------------
  const activityInput = $derived({
    setupEvents: eval_.setupEvents,
    rows: eval_.rows,
    status: eval_.status,
    totalQuestions: eval_.totalQuestions,
    summaryGate: eval_.summary?.gate ?? null,
    summaryElapsedMs: eval_.summary?.elapsed_ms ?? null,
    failureMessage: eval_.failureMessage
  });
  const activityLines = $derived(buildActivityLines(activityInput));
  const currentActivityLine = $derived(activityHeaderLine(activityInput));

  // --- Run actions --------------------------------------------------------------------------
  const canRun = $derived(
    eval_.status === 'idle' ||
      eval_.status === 'completed' ||
      eval_.status === 'failed' ||
      eval_.status === 'cancelled'
  );
  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  const ingestDisabled = $derived(!canRun || !eval_.selectedCorpus);
  const evalDisabled = $derived(!canRun || !eval_.selectedCorpus || eval_.selectedCount === 0);
  const ingestTitle = $derived(!eval_.selectedCorpus ? 'Pick a corpus first' : cfg.ingestHint);
  const evalTitle = $derived(
    !eval_.selectedCorpus
      ? 'Pick a corpus first'
      : eval_.selectedCount === 0
        ? 'Select at least one question to evaluate'
        : 'Answer the selected questions against the existing graph'
  );

  // Which action is in flight (drives the spinner + Cancel placement). null for a run we only
  // learned about via hydration (mid-run navigation) → Cancel defaults to the Question section.
  let runningIntent = $state<'ingest' | 'questions' | null>(null);
  $effect(() => {
    if (!isBusy) runningIntent = null;
  });

  // Wipe guard: an INGEST run that will WIPE an existing graph opens a confirm dialog first.
  let confirmOpen = $state(false);
  function requestIngest() {
    runningIntent = 'ingest';
    const wipes = cfg.track === 'memory' ? eval_.clearBefore : eval_.rebuildChecked;
    if (wipes && eval_.selectedCorpusHasGraph) confirmOpen = true;
    else void eval_.start('ingest');
  }
  function requestEval() {
    runningIntent = 'questions';
    void eval_.start('questions');
  }
</script>

<div class="grid gap-4 rounded-md border bg-muted/10 px-3 py-3">
  <!-- Ingestion: build options + the Ingest button (left); read-only ingestion settings (right). -->
  <div class="grid gap-2">
    <p class="font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Ingestion</p>
    <div class="grid gap-4 md:grid-cols-2">
      <div class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center gap-3">
          {@render ingestionOptions()}
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <Button disabled={ingestDisabled} onclick={requestIngest} title={ingestTitle}>
            {#if isBusy && runningIntent === 'ingest'}
              <LoaderCircle size={14} class="animate-spin" />
            {:else}
              <Download size={14} />
            {/if}
            Ingest
          </Button>
          {#if isBusy && runningIntent === 'ingest'}{@render cancelButton()}{/if}
        </div>
      </div>
      {@render settingsColumn(ingestModels, ingestKnobs)}
    </div>
  </div>

  <!-- Question answering: answer/recall options + selected count + Eval button (left); settings (right). -->
  <div class="grid gap-2 border-t pt-3">
    <p class="font-sans text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Question answering</p>
    <div class="grid gap-4 md:grid-cols-2">
      <div class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center gap-3">
          {@render answeringOptions()}
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-sans text-xs text-muted-foreground" title="Questions selected to evaluate">
            <span class="font-mono tabular-nums text-foreground">{eval_.selectedCount}</span>
            {eval_.selectedCount === 1 ? 'question' : 'questions'} selected
          </span>
          <Button disabled={evalDisabled} onclick={requestEval} title={evalTitle}>
            {#if isBusy && runningIntent !== 'ingest'}
              <LoaderCircle size={14} class="animate-spin" />
            {:else}
              <Play size={14} />
            {/if}
            Eval Questions
          </Button>
          {#if isBusy && runningIntent !== 'ingest'}{@render cancelButton()}{/if}
        </div>
      </div>
      {@render settingsColumn(recallModels, recallKnobs)}
    </div>
  </div>
</div>

<EvalCostStrip {eval_} {cfg} {traces} />

<!-- Activity section — only once processing starts (or has data to replay). -->
{#if isBusy || eval_.setupEvents.length > 0 || eval_.rows.length > 0}
  <KnowledgeCollapsibleSectionCard
    title="Activity"
    bodyId="knowledge-eval-activity"
    defaultExpanded={false}
    collapsedSummary={currentActivityLine}
  >
    <EvalTerminal lines={activityLines} />
  </KnowledgeCollapsibleSectionCard>
{/if}

<!-- Rebuild-graph wipe confirm — gates the Ingest button when a wipe is armed on a graphed corpus. -->
<EvalRebuildConfirmDialog
  bind:open={confirmOpen}
  track={eval_.track}
  corpusName={eval_.selectedCorpus?.name ?? ''}
  onConfirm={() => {
    confirmOpen = false;
    void eval_.start('ingest');
  }}
/>

<!-- Read-only settings block (models one-per-line + a dense knob chip row). -->
{#snippet settingsBlock(models: ModelLine[], knobs: Param[])}
  <div class="grid gap-y-0.5 font-sans text-xs">
    {#each models as m (m.label)}
      <div class="flex flex-wrap items-baseline gap-x-2">
        <span class="w-20 shrink-0 text-muted-foreground">{m.label}</span>
        <span class="font-mono text-foreground">{m.model}</span>
        {#if m.tuning}<span class="text-muted-foreground">· {m.tuning}</span>{/if}
      </div>
    {/each}
  </div>
  {#if knobs.length > 0}
    <div class="flex flex-wrap gap-x-3 gap-y-0.5 font-sans text-xs">
      {#each knobs as p (p.label)}
        <span class="text-muted-foreground">{p.label}: <span class="font-mono text-foreground">{p.value}</span></span>
      {/each}
    </div>
  {/if}
{/snippet}

<!-- Right-hand settings column: a "Settings" label + gear link to edit in Graph engine. -->
{#snippet settingsColumn(models: ModelLine[], knobs: Param[])}
  <div class="min-w-0">
    <div class="mb-1 flex items-center justify-between gap-2">
      <span class="font-sans text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70">Settings</span>
      <a
        href={preferenceTabHref('graph-engine', base)}
        title="Edit these settings in Graph engine"
        aria-label="Edit settings"
        class="inline-flex items-center rounded border p-1 text-primary hover:bg-primary/5"
      >
        <Settings2 size={14} aria-hidden="true" />
      </a>
    </div>
    {#if prefs}
      {@render settingsBlock(models, knobs)}
    {:else}
      <p class="font-sans text-xs text-muted-foreground">Settings unavailable.</p>
    {/if}
  </div>
{/snippet}

<!-- Cancel control for an in-flight run — shown in whichever button row owns the running action. -->
{#snippet cancelButton()}
  <Button
    variant="destructive"
    disabled={eval_.cancelling}
    onclick={() => void eval_.cancel()}
    title="Stop the running job"
  >
    {#if eval_.cancelling}
      <LoaderCircle size={14} class="animate-spin" />
    {:else}
      <Square size={14} />
    {/if}
    {eval_.cancelling ? 'Cancelling…' : 'Cancel'}
  </Button>
{/snippet}

<!-- Ingestion options — memory: episode window + Clear Graph; knowledge: Rebuild graph. -->
{#snippet ingestionOptions()}
  {#if !cfg.hasEpisodeWindow}
    <label
      class="flex select-none items-center gap-2 font-sans text-sm {isBusy ? 'opacity-50' : 'cursor-pointer'}"
      title="Wipe this corpus's prior graph, then rebuild it from the ingested chunks. Leave off to reuse the existing graph."
    >
      <input type="checkbox" class="size-4" bind:checked={eval_.buildGraph} disabled={isBusy} />
      <span>Rebuild graph</span>
    </label>
  {:else}
    <div
      class="flex items-center gap-1.5 font-sans text-sm {isBusy ? 'opacity-50' : ''}"
      title="Ingest episodes From..To this run (1-based, inclusive — episode 1 is the first turn). To = 0 means to the end. Auto-advances after each batch."
    >
      <span class="text-muted-foreground">Episodes</span>
      <input
        type="number"
        min="1"
        class={cn(ADMIN_INPUT, 'h-8 w-20')}
        value={eval_.episodeFrom}
        oninput={(e) => (eval_.episodeFrom = e.currentTarget.valueAsNumber)}
        disabled={isBusy}
        title="From episode (1-based, inclusive)"
      />
      <span class="text-muted-foreground">to</span>
      <input
        type="number"
        min="0"
        class={cn(ADMIN_INPUT, 'h-8 w-20')}
        value={eval_.episodeTo}
        oninput={(e) => (eval_.episodeTo = e.currentTarget.valueAsNumber)}
        disabled={isBusy}
        title="To episode (1-based, inclusive; 0 = to the end)"
      />
    </div>
    <label
      class="flex select-none items-center gap-2 font-sans text-sm {isBusy || !eval_.selectedCorpusHasGraph ? 'opacity-50' : 'cursor-pointer'}"
      title={eval_.selectedCorpusHasGraph
        ? 'Clear the graph before ingesting (WARNING: deletes every previously ingested episode for this corpus)'
        : 'No graph to clear yet — ingest first'}
    >
      <input
        type="checkbox"
        class="size-4"
        bind:checked={eval_.clearBefore}
        disabled={isBusy || !eval_.selectedCorpusHasGraph}
      />
      <span>Clear Graph</span>
    </label>
  {/if}
{/snippet}

<!-- Answering options — knowledge: leg selector; both: optional LLM judge; memory: parallel cap +
     answer-prompt profile. Judge + parallel only matter once questions are selected (dimmed until). -->
{#snippet answeringOptions()}
  {#if cfg.hasLegSelector}
    <div class="flex items-center gap-2 font-sans text-sm">
      <span class="text-muted-foreground">Legs</span>
      <div class="flex gap-1" role="group" aria-label="Legs to compare">
        {#each EVAL_ALL_LEGS as mode (mode)}
          <button
            type="button"
            class="rounded-md border px-2 py-1 text-xs {eval_.isModeSelected(mode)
              ? 'border-primary bg-primary/10 text-primary'
              : 'text-muted-foreground hover:bg-muted'}"
            aria-pressed={eval_.isModeSelected(mode)}
            disabled={isBusy}
            title={mode === 'graphiti'
              ? 'Graph facts only (by-id passages, no query hybrid)'
              : 'No graph — flat Qdrant hybrid'}
            onclick={() => eval_.toggleMode(mode)}
          >
            {legLabel(mode)}
          </button>
        {/each}
      </div>
    </div>
  {/if}
  <label
    class="flex select-none items-center gap-2 font-sans text-sm {isBusy || eval_.selectedCount === 0 ? 'opacity-50' : 'cursor-pointer'}"
    title={eval_.selectedCount === 0
      ? 'Select questions to enable the LLM judge'
      : 'Grade each answer against the ideal with the LLM judge (off = recall results only)'}
  >
    <input
      type="checkbox"
      class="size-4"
      bind:checked={eval_.judge}
      disabled={isBusy || eval_.selectedCount === 0}
    />
    <span>LLM Judge Answers</span>
  </label>
  {#if cfg.hasQuestionConcurrency}
    <div
      class="flex items-center gap-1.5 font-sans text-sm {isBusy || eval_.selectedCount === 0 ? 'opacity-50' : ''}"
      title="Questions evaluated in parallel (1 = one at a time). Higher is faster but per-question times include waiting, and aggressive caps can hit LLM provider rate limits."
    >
      <span class="text-muted-foreground">Parallel</span>
      <input
        type="number"
        min="1"
        max={eval_.questionConcurrencyMax}
        class={cn(ADMIN_INPUT, 'h-8 w-16')}
        value={eval_.questionConcurrency}
        oninput={(e) => (eval_.questionConcurrency = e.currentTarget.valueAsNumber)}
        disabled={isBusy || eval_.selectedCount === 0}
      />
    </div>
  {/if}
  {#if cfg.hasAnswerPrompt}
    <div
      class="flex items-center gap-1.5 font-sans text-sm {isBusy ? 'opacity-50' : ''}"
      title="Named answer-prompt profile driving the answer step (edit profiles in Preferences → Graph Engine). Remembered per corpus."
    >
      <span class="text-muted-foreground">Answer prompt</span>
      <select
        class={cn(ADMIN_SELECT, 'h-8')}
        value={eval_.answerPromptId}
        onchange={(e) => (eval_.answerPromptId = e.currentTarget.value)}
        disabled={isBusy}
      >
        {#each answerPromptOptions as opt (opt.id)}
          <option value={opt.id}>{opt.label}</option>
        {/each}
      </select>
    </div>
  {/if}
{/snippet}
