<!--
  Detail dialog for one chat memory recall (a `memory_recall` node): Overview (question + the
  retrieval agent's draft answer) / Trajectory / Facts / Entities / Episodes, plus its time, cost and
  the retrieval pipeline trace. Opened from the node's ⓘ marker in the run's node table.

  Recalled tables (Facts/Entities/Episodes) render via RecalledTable so they mirror what the reply
  saw: ordered by score, capped-out items struck through, text trimmed to the caps (toggleable). A
  header search box filters + highlights across all tables.
-->
<script lang="ts">
  import { LoaderCircle, Microscope, Scissors } from '@lucide/svelte';
  import SearchInput from '$kit/ui/search-input.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import Highlight from '$kit/search/highlight.svelte';
  import TraceTabs, { type TraceTab } from '$kit/memory/trace/trace-tabs.svelte';
  import { formatCost } from '$lib/features/graph-runs/graph-runs-pure';
  import type { RetrievalTraceDialogController } from '$kit/memory/trace/state/retrieval-trace-controller.svelte';
  import type { RecalledFact } from '$lib/api/graph-runs';
  import RecalledTable from './RecalledTable.svelte';
  import RecallTrajectory from './RecallTrajectory.svelte';
  import { DEFAULT_RECALL_RENDER, recalledTabCount } from './recall-render';
  import type { ChatRecall } from './chat-recall';

  interface Props {
    /** The recall to show, or null when the dialog is closed. */
    recall: ChatRecall | null;
    /** Opens the (stacked) retrieval pipeline trace dialog for the run or one of its sub-queries. */
    traces: RetrievalTraceDialogController;
    onClose: () => void;
  }
  let { recall, traces, onClose }: Props = $props();

  type TabKey = 'overview' | 'facts' | 'entities' | 'episodes' | 'trajectory';

  let activeTab = $state<TabKey>('overview');
  // Search-id highlight driven from the Trajectory tab (dims non-matching facts).
  let trajectorySearchId = $state<number | null>(null);
  // Dialog-local search (filters + highlights the recalled tables), cleared when a new recall opens.
  let q = $state('');
  // Trim each recalled item's text to its cap (default ON = what the reply saw) vs. full text.
  let trimmed = $state(true);

  $effect(() => {
    void recall;
    q = '';
    activeTab = 'overview';
    trajectorySearchId = null;
  });

  function recalledOf(items: RecalledFact[]) {
    return {
      facts: items.filter((x) => (x.kind ?? 'fact') === 'fact'),
      entities: items.filter((x) => x.kind === 'entity'),
      episodes: items.filter((x) => x.kind === 'episode')
    };
  }

  const recalled = $derived(recalledOf(recall?.recalled ?? []));
  const render = $derived(recall?.render ?? DEFAULT_RECALL_RENDER);

  // Order: Overview, then Trajectory (the retrieval story), then the recalled-set tabs.
  const tabs = $derived.by((): TraceTab[] => {
    const cap = render.max_elements_per_kind;
    const out: TraceTab[] = [{ key: 'overview', label: 'Overview' }];
    if (recall?.loop) out.push({ key: 'trajectory', label: 'Trajectory', count: `${recall.loop.agent_turns}` });
    if (recalled.facts.length > 0)
      out.push({ key: 'facts', label: 'Facts', count: recalledTabCount(recalled.facts, cap, q) });
    if (recalled.entities.length > 0)
      out.push({ key: 'entities', label: 'Entities', count: recalledTabCount(recalled.entities, cap, q) });
    if (recalled.episodes.length > 0)
      out.push({ key: 'episodes', label: 'Episodes', count: recalledTabCount(recalled.episodes, cap, q) });
    return out;
  });
  const active = $derived<TabKey>(tabs.some((t) => t.key === activeTab) ? activeTab : 'overview');
</script>

<Dialog.Root open={recall !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="flex h-[90vh] flex-col sm:max-w-[min(96vw,1100px)]">
    {#if recall}
      {@const r = recall}
      <!-- Header row: question · search (filters + highlights the tables) · trimmed/full toggle. -->
      <Dialog.Header class="border-b border-border pb-3">
        <div class="flex items-center gap-3 pr-8">
          <Dialog.Title class="line-clamp-2 min-w-0 flex-1">{r.question}</Dialog.Title>
          <SearchInput
            variant="inline"
            class="w-56 shrink-0 border-input bg-muted/30 shadow-none"
            inputClass="text-xs text-foreground"
            bind:value={q}
            placeholder="Search facts, entities, episodes…"
          />
          <Button
            variant="outline"
            size="sm"
            class="shrink-0"
            aria-pressed={trimmed}
            title={trimmed
              ? 'Showing trimmed item text (as sent to the reply). Click to show full text.'
              : 'Showing full item text. Click to trim it to the caps (as sent to the reply).'}
            onclick={() => (trimmed = !trimmed)}
          >
            <Scissors size={14} aria-hidden="true" />
            <span class="text-xs">{trimmed ? 'Trimmed' : 'Full text'}</span>
          </Button>
        </div>
      </Dialog.Header>

      <div class="grid flex-1 content-start gap-2 overflow-y-auto pr-1">
        <!-- Tabs (left) · time, cost and the pipeline trace (right), then the active tab below. -->
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
          <TraceTabs
            {tabs}
            {active}
            onSelect={(k) => (activeTab = k as TabKey)}
            ariaLabel="Recall detail tabs"
            variant="lanes"
          />
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-mono text-xs tabular-nums text-muted-foreground">{r.elapsedMs}ms</span>
            {#if r.costUsd}
              <span class="font-mono text-xs tabular-nums text-muted-foreground">{formatCost(r.costUsd)}</span>
            {/if}
            <button
              type="button"
              class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/5 disabled:opacity-50"
              disabled={traces.traceLoadingRunId !== null}
              onclick={() => void traces.openTrace(r.runId, r.answer, r.question)}
              title="Open the retrieval pipeline trace"
            >
              {#if traces.traceLoadingRunId === r.runId}
                <LoaderCircle size={10} class="animate-spin" aria-hidden="true" />
              {:else}
                <Microscope size={10} aria-hidden="true" />
              {/if}
              trace
            </button>
          </div>
        </div>
        {#if active === 'overview'}
          <div class="grid gap-2 text-xs leading-5">
            <div class="flex flex-wrap gap-2">
              <span class="min-w-[64px] text-muted-foreground">Question</span>
              <span class="flex-1 whitespace-pre-wrap text-foreground"><Highlight text={r.question} query={q} /></span>
            </div>
            <div class="flex flex-wrap gap-2">
              <span class="min-w-[64px] text-muted-foreground">Draft answer</span>
              {#if r.answer}
                <span class="flex-1 whitespace-pre-wrap text-foreground"><Highlight text={r.answer} query={q} /></span>
              {:else}
                <span class="flex-1 italic text-muted-foreground">— (no answer)</span>
              {/if}
            </div>
          </div>
        {:else if active === 'facts'}
          <RecalledTable rows={recalled.facts} kind="fact" {render} {trimmed} search={q} dimSearchId={trajectorySearchId} />
        {:else if active === 'entities'}
          <RecalledTable rows={recalled.entities} kind="entity" {render} {trimmed} search={q} />
        {:else if active === 'episodes'}
          <RecalledTable rows={recalled.episodes} kind="episode" {render} {trimmed} search={q} />
        {:else if active === 'trajectory' && r.loop}
          <RecallTrajectory
            loop={r.loop}
            facts={recalled.facts}
            onSearchSelect={(sid) => (trajectorySearchId = sid)}
            onOpenTrace={(sid) => void traces.openTraceForSubQuery(r.runId, sid, r.answer)}
            loadingSid={traces.traceLoadingSid}
          />
        {/if}
      </div>

      <Dialog.Footer>
        <Button variant="outline" onclick={onClose}>Close</Button>
      </Dialog.Footer>
    {/if}
  </Dialog.Content>
</Dialog.Root>
