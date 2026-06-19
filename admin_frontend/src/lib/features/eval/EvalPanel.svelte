<!--
  Eval panel — composition root. A shared corpus selector + sticky section sub-tabs (Execute /
  Corpus / Questions-Answers / Report) over one pane per section. Track divergence (memory vs
  knowledge) is read declaratively from `trackConfig`; every screen-concern lives in its own pane
  under features/eval/{execute,corpus,answers,report}. Cross-pane trace/copy/export orchestration
  lives in the eval-traces controller; the trace + clear dialogs are hosted here.

  Hosted on its own top-level Eval page (moved out of the Knowledge tabs). The model lifecycle
  (subscribe + replay run state + corpus scan) is owned by the host Eval page; this is a view.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { afterNavigate } from '$app/navigation';
  import { FolderSearch, LoaderCircle, RefreshCw } from '@lucide/svelte';
  import AdminSubtabStrip from '$lib/components/page/AdminSubtabStrip.svelte';
  import type { AdminSubtabDescriptor } from '$lib/components/page/tab-types';
  import { ADMIN_SHELL_STICKY_BLEED } from '$lib/styling/admin-tokens';
  import { setupStickyHeightVar } from '$lib/styling/sticky-height';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import { createEvalSubtabPreferences } from '$lib/preferences/eval-preferences.svelte';
  import type { EvalSubtabPreference } from '$lib/preferences/keys';
  import Button from '$lib/components/ui/button.svelte';
  import EvalCorpusReview from '$lib/features/eval/view/EvalCorpusReview.svelte';
  import EvalClearResultsConfirmDialog from '$lib/features/eval/view/EvalClearResultsConfirmDialog.svelte';
  import EvalExecutePane from '$lib/features/eval/execute/EvalExecutePane.svelte';
  import EvalCorpusPane from '$lib/features/eval/corpus/EvalCorpusPane.svelte';
  import EvalAnswersPane from '$lib/features/eval/answers/EvalAnswersPane.svelte';
  import EvalReportPane from '$lib/features/eval/report/EvalReportPane.svelte';
  import GraphRunsRetrievalTraceDialog from '$lib/features/graph-runs/GraphRunsRetrievalTraceDialog.svelte';
  import GraphRunsIngestTraceDialog from '$lib/features/graph-runs/GraphRunsIngestTraceDialog.svelte';
  import { ingestState } from '$lib/features/eval/shared/eval-display';
  import { aiEngineLine } from '$lib/features/eval/shared/eval-engine-params';
  import { trackConfig } from '$lib/features/eval/shared/eval-tracks';
  import { createEvalTraces } from '$lib/features/eval/state/eval-traces.svelte';
  import { getPreferences, type WorkspacePreferences } from '$lib/api/preferences';
  import type { EvalModel } from '$lib/features/eval/state/eval-model.svelte';

  interface Props {
    /** Eval model (track state, run lifecycle, corpus picker) — created and
     *  init/torn-down by the host Eval page; this component is a pure view. */
    eval_: EvalModel;
  }
  let { eval_ }: Props = $props();

  // Per-track capability table (memory vs knowledge): the single declarative source for every
  // track divergence the panes render.
  const cfg = $derived(trackConfig(eval_.track));
  const isBusy = $derived(eval_.status === 'starting' || eval_.status === 'running');

  // Engine prefs — read-only, loaded once. Drives the Execute settings columns + the Copy-for-AI
  // engine line (consumed by the traces controller via getAiEngine).
  let prefs = $state<WorkspacePreferences | null>(null);
  const aiEngine = $derived(aiEngineLine(prefs));
  async function loadPrefs() {
    try {
      const res = await getPreferences();
      prefs = res.data.preferences;
    } catch {
      prefs = null; // non-fatal — the panes still work without the params strip
    }
  }

  // Cross-pane trace / copy / LoCoMo-export orchestration (dialogs hosted below). The model
  // instance is stable (the host page creates it once), so a getter is enough — and it keeps
  // Svelte from flagging a bare prop read in this non-reactive call.
  const traces = createEvalTraces({
    get eval_() {
      return eval_;
    },
    getAiEngine: () => aiEngine
  });

  // Label for the dialogs' optional "Corpus" tab (empty = no tab) — memory track, episodes loaded.
  const corpusTabLabel = $derived(
    cfg.hasCorpusReview && eval_.corpusEpisodes.length > 0
      ? `Corpus (${eval_.corpusEpisodes.length})`
      : ''
  );

  // --- Sticky section sub-tabs (Execute / Corpus / Questions-Answers / Report) --------------
  // Synced via the shared tab-preferences factory on the `?sub=` param (+ sessionStorage) so a
  // refresh / deep-link reopens the same sub-tab; it coexists with the page-level track `?tab=`.
  // The validity effect below snaps back if the active tab disappears (Corpus is memory-only), so
  // a stale `?sub=corpus` self-heals on the knowledge track.
  const subPrefs = createEvalSubtabPreferences();
  const activeSubtab = $derived(subPrefs.activeTab);
  const selectSubtab = (id: EvalSubtabPreference) => void subPrefs.setActiveTab(id);
  afterNavigate(() => subPrefs.syncActiveTabFromUrl());
  const subtabs = $derived<AdminSubtabDescriptor<EvalSubtabPreference>[]>([
    { id: 'execute', label: 'Execute' },
    ...(cfg.hasCorpusReview
      ? [{ id: 'corpus' as const, label: 'Corpus', count: eval_.selectedCorpus?.item_count }]
      : []),
    {
      id: 'answers',
      label: 'Questions/Answers',
      countText: eval_.questions.length ? `${eval_.rows.length}/${eval_.questions.length}` : undefined
    },
    { id: 'report', label: 'Reports' }
  ]);
  $effect(() => {
    if (!subtabs.some((t) => t.id === activeSubtab)) void subPrefs.setActiveTab('execute');
  });
  // Load benchmark results when the Report tab opens; reload if the selected benchmark changes.
  $effect(() => {
    if (activeSubtab === 'report' && cfg.hasBenchmarks) {
      void eval_.selectedBenchmarkId;
      void eval_.loadBenchmarkResults();
    }
  });

  // Sticky sub-tab bar element — its height is published as a CSS var so the panes' sticky toolbars
  // and the results table's sticky thead can offset beneath it.
  let subtabsEl = $state<HTMLDivElement | null>(null);

  onMount(() => {
    subPrefs.initialize();
    void loadPrefs();
    if (!subtabsEl) return;
    return setupStickyHeightVar(subtabsEl, '--admin-eval-subtabs-h');
  });

  // The shared knowledge SSE is paused while this browser tab is hidden; a run keeps progressing
  // server-side, so on refocus we re-pull the authoritative run state to backfill missed events.
  function onVisibilityChange(): void {
    if (document.visibilityState === 'visible') void eval_.resync();
  }

  // Clear guard: the memory-track clear PERMANENTLY deletes saved results from disk, so it's gated
  // behind a confirm. The knowledge-track "Clear" only resets in-view run state (non-destructive).
  let clearConfirmOpen = $state(false);
  function requestClear() {
    if (cfg.persistsResults) clearConfirmOpen = true;
    else void eval_.clear();
  }
</script>

<svelte:document onvisibilitychange={onVisibilityChange} />

<section class="grid gap-4">
  <!-- Error banners — above the sub-tabs so transport/scan failures stay visible. -->
  {#if eval_.status === 'failed' && eval_.failureMessage}
    <InlineDestructiveAlert title="Eval run failed" message={eval_.failureMessage} />
  {/if}
  {#if eval_.corpusesError}
    <InlineDestructiveAlert message={eval_.corpusesError} />
  {/if}

  <!-- Corpus selector — shared context for every sub-tab. Scrolls away normally; only the sub-tab
       bar pins (sticky). -->
  <div class="flex flex-wrap items-center gap-3">
    <div class="flex items-center gap-1.5 font-sans text-sm">
      <span class="text-muted-foreground">Folder</span>
      <input
        class="h-8 w-64 rounded-md border bg-background px-2 text-sm"
        placeholder="Folder to scan for corpuses"
        value={eval_.folder}
        oninput={(e) => eval_.setFolder(e.currentTarget.value)}
        onchange={() => void eval_.scanCorpuses()}
        disabled={isBusy}
      />
      <Button
        type="button"
        variant="outline"
        class="h-8"
        onclick={() => void eval_.browseFolder()}
        disabled={isBusy || eval_.pickingFolder}
        title="Pick a folder"
      >
        {#if eval_.pickingFolder}
          <LoaderCircle size={14} class="animate-spin" />
        {:else}
          <FolderSearch size={14} />
        {/if}
      </Button>
      <Button
        type="button"
        variant="outline"
        class="h-8"
        onclick={() => void eval_.scanCorpuses()}
        disabled={isBusy || eval_.corpusesLoading}
        title="Rescan folder"
      >
        <RefreshCw size={14} class={eval_.corpusesLoading ? 'animate-spin' : ''} />
      </Button>
    </div>
    {#if eval_.benchmarks.length > 0}
      <label class="flex select-none items-center gap-2 font-sans text-sm">
        <span class="text-muted-foreground">Benchmark</span>
        <select
          class="h-8 min-w-40 rounded-md border bg-background px-2 text-sm disabled:opacity-50"
          value={eval_.selectedBenchmarkId}
          onchange={(e) => eval_.selectBenchmark(e.currentTarget.value)}
          disabled={isBusy}
        >
          {#each eval_.benchmarks as b (b.id)}
            <option value={b.id}>{b.label}</option>
          {/each}
        </select>
      </label>
    {/if}
    <label class="flex select-none items-center gap-2 font-sans text-sm">
      <span class="text-muted-foreground">Corpus</span>
      <select
        class="h-8 min-w-48 rounded-md border bg-background px-2 text-sm disabled:opacity-50"
        value={eval_.selectedCorpusId}
        onchange={(e) => eval_.selectCorpus(e.currentTarget.value)}
        disabled={isBusy || eval_.visibleCorpuses.length === 0}
      >
        {#if eval_.visibleCorpuses.length === 0}
          <option value="">No corpuses found</option>
        {:else if cfg.tracksIngestion}
          {#each eval_.visibleCorpuses as c (c.id)}
            <option value={c.id} title={ingestState(c).word}>
              {ingestState(c).dot} {c.label ?? c.name}
            </option>
          {/each}
        {:else}
          {#each eval_.visibleCorpuses as c (c.id)}
            <option value={c.id}>{c.label ?? c.name}</option>
          {/each}
        {/if}
      </select>
    </label>
  </div>

  <!-- Sticky section sub-tabs — pin directly under the page header. -->
  <div
    bind:this={subtabsEl}
    class="sticky z-10 bg-background/95 py-1 backdrop-blur supports-[backdrop-filter]:bg-background/85 {ADMIN_SHELL_STICKY_BLEED}"
    style="top: calc(4rem + var(--admin-page-header-h, 0px) + var(--admin-page-sticky-toolbar-h, 0px));"
  >
    <AdminSubtabStrip
      ariaLabel="Eval section"
      tabs={subtabs}
      active={activeSubtab}
      onSelect={selectSubtab}
    />
  </div>

  {#if activeSubtab === 'execute'}
    <EvalExecutePane {eval_} {cfg} {prefs} {traces} />
  {:else if activeSubtab === 'corpus'}
    <EvalCorpusPane {eval_} {cfg} {traces} />
  {:else if activeSubtab === 'answers'}
    <EvalAnswersPane {eval_} {cfg} {traces} />
  {:else if activeSubtab === 'report'}
    <EvalReportPane {eval_} {cfg} onRequestClear={requestClear} />
  {/if}
</section>

<!-- ===== Cross-pane trace / export banners + dialogs ===== -->
{#if traces.traceError}
  <InlineDestructiveAlert message={traces.traceError} class="mt-2" />
{/if}
{#if traces.copyError}
  <InlineDestructiveAlert message="Copy for AI failed: {traces.copyError}" class="mt-2" />
{/if}
{#if traces.locomoExportError}
  <InlineDestructiveAlert message="LoCoMo export failed: {traces.locomoExportError}" class="mt-2" />
{/if}
{#if traces.locomoExportNotice}
  <!-- Success/primary notice (not destructive) — no blessed inline primitive for this transient
       confirmation yet, so it stays hand-rolled. (Candidate for a toast in a follow-up.) -->
  <div class="mt-2 rounded-md border border-primary/30 bg-primary/10 px-3 py-2 font-sans text-sm text-primary" role="status">
    {traces.locomoExportNotice}
  </div>
{/if}
{#if traces.ingestTraceError}
  <InlineDestructiveAlert message={traces.ingestTraceError} class="mt-2" />
{/if}

<!-- Corpus tab for the ingest trace dialog: built-in search box (that dialog has no top search). -->
{#snippet corpusTab()}
  <EvalCorpusReview episodes={eval_.corpusEpisodes} compact />
{/snippet}
<!-- Corpus tab for the retrieval trace dialog: filtering is driven by the dialog's top search. -->
{#snippet corpusTabWired(dialogSearch: string)}
  <EvalCorpusReview
    episodes={eval_.corpusEpisodes}
    search={dialogSearch}
    showSearch={false}
    showCount
    compact
  />
{/snippet}
<GraphRunsRetrievalTraceDialog
  trace={traces.activeTrace}
  idealAnswer={traces.activeTraceIdeal}
  llmAnswer={traces.activeTraceAnswer}
  onClose={traces.closeTrace}
  extraTabLabel={corpusTabLabel}
  extraTab={corpusTabLabel ? corpusTabWired : undefined}
/>
<GraphRunsIngestTraceDialog
  trace={traces.activeIngestTrace}
  onClose={traces.closeIngestTrace}
  hasPrev={traces.ingestTraceIndex > 0}
  hasNext={traces.ingestTraceIndex < traces.ingestTraces.length - 1}
  onPrev={() => traces.stepIngestTrace(-1)}
  onNext={() => traces.stepIngestTrace(1)}
  navIndex={traces.ingestTraces.length ? traces.ingestTraceIndex + 1 : 0}
  navTotal={traces.ingestTraces.length}
  extraTabLabel={corpusTabLabel}
  extraTab={corpusTabLabel ? corpusTab : undefined}
/>

<!-- Clear-results confirm — gates the memory track's destructive on-disk delete of saved results. -->
<EvalClearResultsConfirmDialog
  bind:open={clearConfirmOpen}
  corpusName={eval_.selectedCorpus?.name ?? ''}
  savedCount={eval_.savedCount}
  onConfirm={() => {
    clearConfirmOpen = false;
    void eval_.clear();
  }}
/>
