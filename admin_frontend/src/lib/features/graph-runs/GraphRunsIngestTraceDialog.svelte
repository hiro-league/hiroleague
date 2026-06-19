<script lang="ts">
  import {
    ChevronLeft,
    ChevronRight,
    ChevronsDownUp,
    ChevronsUpDown,
    Settings2
  } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type {
    IngestTraceEdge,
    IngestTraceNode,
    IngestTraceRecord,
    IngestTraceStage
  } from '$lib/api/graph-runs';
  import { shortGraphId } from '$lib/format/short-graph-id';
  import StageCard from './shared/StageCard.svelte';
  import TraceTable from './shared/TraceTable.svelte';
  import TraceTabs, { type TraceTab } from './shared/TraceTabs.svelte';
  import ValidityPill from './shared/ValidityPill.svelte';
  import { createToggleSet } from './shared/use-toggle-set.svelte';
  import {
    fmtDate,
    isCurrent,
    isISO,
    prettyKey,
    temporalTitle
  } from './shared/trace-format';
  import {
    briefName,
    briefType,
    buildEntityTypeMap,
    buildPhases,
    dedupJson,
    dedupMerges,
    extractedEntities as extractedEntitiesFor,
    groupStages,
    inputView,
    messages,
    outputView,
    prettyOutput,
    resolveFactsView,
    stageCount as stageCountFor,
    stageMeta,
    type ExtractedEntityRow,
    type Phase,
    type ResolveFactsView,
    type ViewTable
  } from './shared/ingest-trace-derive';

  let {
    trace,
    onClose,
    // Prev/next episode navigation (header arrows + ←/→ keys). Optional so the generic
    // graph-runs caller can omit them; disabled at the ends via hasPrev/hasNext.
    hasPrev = false,
    hasNext = false,
    onPrev,
    onNext,
    // Position of the current trace within the run's episode list (1-based) — shown between the
    // arrows. The per-trace episode_index/total is 1/1 for the eval's single-episode ingests, so
    // the caller supplies the real run position here; falls back to episode_index/total when unset.
    navIndex = 0,
    navTotal = 0,
    // Optional extra tab (eval: the searchable source corpus) — decoupled via a snippet so this
    // Graph-Runs component stays generic. Both props must be set for the tab to appear.
    extraTabLabel = '',
    extraTab
  }: {
    trace: IngestTraceRecord | null;
    onClose: () => void;
    hasPrev?: boolean;
    hasNext?: boolean;
    onPrev?: () => void;
    onNext?: () => void;
    navIndex?: number;
    navTotal?: number;
    extraTabLabel?: string;
    extraTab?: import('svelte').Snippet;
  } = $props();

  const hasExtraTab = $derived(!!extraTab && !!extraTabLabel);

  // ── Tabs ────────────────────────────────────────────────────────────────────────────────
  // One flat tab row: a tab per pipeline phase (Entities / Attributes / Facts / Other) — the
  // per-stage journey — then Result (what landed in the graph: persisted nodes + edges), then
  // the caller's optional Corpus tab. Sentinels keep the last two distinct from phase keys.
  const RESULT_TAB = '__result__';
  const EXTRA_TAB = '__extra__';
  let activeTab = $state<string>('');

  // Per-stage collapse, keyed by the stage's index in `trace.stages`. Separate disclosures for
  // the (large, repetitive) prompt and the raw-JSON fallback — both collapsed by default since
  // the structured table is the primary view. All reset on a new trace.
  const collapsed = createToggleSet<number>();
  const promptOpen = createToggleSet<number>();
  const jsonOpen = createToggleSet<number>();

  // The config/stats line (episode · chunk · tokens …) is collapsed by default behind the
  // header gear so the header stays compact — mirrors the recall (retrieval) trace dialog.
  let settingsOpen = $state(false);

  // Reset transient view state on a new trace, but PRESERVE the active tab so arrow-nav between
  // episodes keeps you on the same tab (the tabKeys effect below re-validates / initialises it).
  $effect(() => {
    void trace;
    collapsed.clear();
    promptOpen.clear();
    jsonOpen.clear();
    settingsOpen = false;
  });

  // ←/→ navigate to the prev/next episode trace (mirrors the header arrows). Guarded so it never
  // fires while typing in an input/textarea, when a modifier is held, or when the dialog is closed.
  function onArrowNavKey(ev: KeyboardEvent): void {
    if (trace === null) return;
    if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    const t = ev.target as HTMLElement | null;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (ev.key === 'ArrowLeft' && hasPrev) {
      ev.preventDefault();
      onPrev?.();
    } else if (ev.key === 'ArrowRight' && hasNext) {
      ev.preventDefault();
      onNext?.();
    }
  }

  const toggleStage = (index: number): void => collapsed.toggle(index);
  const togglePrompt = (index: number): void => promptOpen.toggle(index);
  const toggleJson = (index: number): void => jsonOpen.toggle(index);

  const isCollapsed = (index: number): boolean => collapsed.has(index);
  const isPromptOpen = (index: number): boolean => promptOpen.has(index);
  const isJsonOpen = (index: number): boolean => jsonOpen.has(index);

  // ── Stage grouping + pipeline phases (sub-tabs) ───────────────────────────────────────────
  // Pure derivation lives in `shared/ingest-trace-derive`; here we just feed it the trace.
  const groups = $derived(trace ? groupStages(trace.stages) : []);
  const phases = $derived<Phase[]>(buildPhases(groups));

  // The flat tab order: each present phase, then Result, then the optional Corpus tab.
  const tabKeys = $derived<string[]>([
    ...phases.map((p) => p.phase),
    RESULT_TAB,
    ...(hasExtraTab ? [EXTRA_TAB] : [])
  ]);

  // Keep the active tab valid as the trace (and thus its phases) changes.
  $effect(() => {
    if (!tabKeys.includes(activeTab)) activeTab = tabKeys[0] ?? RESULT_TAB;
  });

  // The active phase, or null when the active tab is Result / Corpus (no per-stage cards).
  const activePhaseObj = $derived<Phase | null>(
    phases.find((p) => p.phase === activeTab) ?? null
  );

  // Tab strip model for <TraceTabs>: a tab per phase (count = stages), then Result (count =
  // persisted nodes + edges), then the optional caller tab. `.by` defers nodes/edges (below).
  const ingestTabs = $derived.by<TraceTab[]>(() => [
    ...phases.map((p) => ({ key: p.phase, label: p.title, count: String(p.idxs.length) })),
    { key: RESULT_TAB, label: 'Result', count: String(nodes.length + edges.length) },
    ...(hasExtraTab ? [{ key: EXTRA_TAB, label: extraTabLabel, count: null }] : [])
  ]);

  /** Expand / collapse all stage cards in the ACTIVE phase (mirrors the retrieval dialog). */
  const expandActive = (): void => {
    if (activePhaseObj) collapsed.remove(activePhaseObj.idxs);
  };
  const collapseActive = (): void => {
    if (activePhaseObj) collapsed.add(activePhaseObj.idxs);
  };

  // ── Totals (for the header) ───────────────────────────────────────────────────────────────
  const totals = $derived.by(() => {
    let inTok = 0;
    let outTok = 0;
    let ms = 0;
    for (const s of trace?.stages ?? []) {
      inTok += s.input_tokens ?? 0;
      outTok += s.output_tokens ?? 0;
      ms += s.elapsed_ms ?? 0;
    }
    return { inTok, outTok, ms, calls: trace?.stages.length ?? 0 };
  });

  // ── Stage formatting / projection ─────────────────────────────────────────────────────────
  // Pure helpers (table projection, fact-verdict parsing, dedup merge map, entity-type
  // resolution, date formatting, validity) live in `shared/ingest-trace-derive` +
  // `shared/trace-format`. Only the two helpers that need component state — the ontology
  // legend — get thin wrappers here so markup call sites stay unchanged.
  const entityTypeById = $derived(buildEntityTypeMap(trace?.entity_types ?? []));

  const extractedEntities = (stage: IngestTraceStage): ExtractedEntityRow[] | null =>
    extractedEntitiesFor(stage, entityTypeById);

  const stageCount = (stage: IngestTraceStage, node: string): number | null =>
    stageCountFor(stage, node, entityTypeById);

  const nodes = $derived<IngestTraceNode[]>(trace?.persisted_nodes ?? []);
  const edges = $derived<IngestTraceEdge[]>(trace?.persisted_edges ?? []);
</script>

<!-- Renders a projected stage view (structured output / dedup input) as a readable table.
     `rows` = one row per item (columns = union of keys); `kv` = a two-column key/value table;
     `scalar` = a lone value. Declared top-level so it's a local snippet, not a Dialog prop. -->
{#snippet viewTable(view: ViewTable)}
  {#if view.kind === 'rows'}
    <TraceTable out>
        <thead>
          <tr>
            <th class="num">#</th>
            {#each view.columns as col (col)}<th>{prettyKey(col)}</th>{/each}
          </tr>
        </thead>
        <tbody>
          {#each view.rows as row, ri (ri)}
            <tr>
              <td class="num">{ri + 1}</td>
              {#each view.columns as col (col)}
                <td class="cell">
                  {#if isISO(row[col])}<span title={row[col]}>{fmtDate(row[col])}</span>{:else}{row[col]}{/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
    </TraceTable>
  {:else if view.kind === 'kv'}
    <TraceTable out>
        <tbody>
          {#each view.entries as entry (entry.key)}
            <tr>
              <td class="kv-key">{prettyKey(entry.key)}</td>
              <td class="cell">
                {#if isISO(entry.value)}<span title={entry.value}>{fmtDate(entry.value)}</span>{:else}{entry.value}{/if}
              </td>
            </tr>
          {/each}
        </tbody>
    </TraceTable>
  {:else if view.kind === 'scalar'}
    <p class="out-scalar">{view.value}</p>
  {/if}
{/snippet}

<!-- Resolve/invalidate facts: the NEW FACT being added + how each candidate fact was judged.
     `duplicate` ⇒ the new fact already exists (edge reused); `contradicted` ⇒ the new fact
     supersedes it (that edge gets invalidated). Recovered from the prompt + idx output. -->
{#snippet factVerdict(rfv: ResolveFactsView)}
  <div class="fact-verdict">
    <div class="fact-new">
      <span class="output-block__label">New fact</span>
      <p class="fact-new__text">{rfv.newFact || '—'}</p>
    </div>
    <p class="fact-summary">
      {#if rfv.contraCount}<span class="fact-badge fact-badge--contra">{rfv.contraCount} contradicted → invalidated</span>{/if}
      {#if rfv.dupCount}<span class="fact-badge fact-badge--dup">{rfv.dupCount} duplicate</span>{/if}
      {#if !rfv.contraCount && !rfv.dupCount}<span class="fact-badge fact-badge--new">added as new — no duplicate or contradiction</span>{/if}
    </p>
    {#if rfv.candidates.length}
      <TraceTable out>
          <thead>
            <tr><th class="num">idx</th><th>Origin</th><th>Candidate fact</th><th>Decision</th></tr>
          </thead>
          <tbody>
            {#each rfv.candidates as c (c.idx)}
              <tr class:fact-row--hit={c.decision !== 'none'}>
                <td class="num">{c.idx}</td>
                <td class="rel">{c.origin}</td>
                <td class="cell">{c.fact}</td>
                <td>
                  {#if c.decision === 'contradicted'}
                    <span class="fact-badge fact-badge--contra">contradicted → invalidated</span>
                  {:else if c.decision === 'duplicate'}
                    <span class="fact-badge fact-badge--dup">duplicate</span>
                  {:else}
                    <span class="fact-dim">—</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
      </TraceTable>
    {:else}
      <p class="trace-empty">No candidate facts — added directly as new.</p>
    {/if}
  </div>
{/snippet}

<!-- Extract-entities output: each entity with its RESOLVED ontology type (name + description)
     rather than the raw numeric entity_type_id graphiti emits. Top-level local snippet. -->
{#snippet entitiesTable(rows: ExtractedEntityRow[])}
  <TraceTable out>
      <thead>
        <tr>
          <th class="num">#</th>
          <th>Entity</th>
          <th>Type</th>
          <th>Type description</th>
        </tr>
      </thead>
      <tbody>
        {#each rows as row, ri (ri)}
          <tr>
            <td class="num">{ri + 1}</td>
            <td class="entity">{row.name}</td>
            <td><span class="type-chip">{row.typeName}</span></td>
            <td class="cell type-desc">{row.description || '—'}</td>
          </tr>
        {/each}
      </tbody>
  </TraceTable>
{/snippet}

<svelte:window onkeydown={onArrowNavKey} />

<Dialog.Root open={trace !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="ingest-trace-content sm:max-w-[min(96vw,1200px)] flex flex-col h-[90vh]">
    <Dialog.Header>
      <div class="trace-head-row">
        <Dialog.Title>Ingest pipeline trace</Dialog.Title>
        {#if trace}
          <div class="trace-head-actions">
            <Button
              variant="outline"
              size="sm"
              title="Previous episode (Left arrow)"
              aria-label="Previous episode"
              disabled={!hasPrev}
              onclick={() => onPrev?.()}
            >
              <ChevronLeft size={14} aria-hidden="true" />
            </Button>
            <span class="trace-nav-pos" title="Episode position in this run">
              {navTotal > 0 ? `${navIndex}/${navTotal}` : `${trace.episode_index}/${trace.total}`}
            </span>
            <Button
              variant="outline"
              size="sm"
              title="Next episode (Right arrow)"
              aria-label="Next episode"
              disabled={!hasNext}
              onclick={() => onNext?.()}
            >
              <ChevronRight size={14} aria-hidden="true" />
            </Button>
            {#if activePhaseObj}
              <Button
                variant="outline"
                size="sm"
                title="Expand all sections"
                aria-label="Expand all sections"
                onclick={expandActive}
              >
                <ChevronsUpDown size={14} aria-hidden="true" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                title="Collapse all sections"
                aria-label="Collapse all sections"
                onclick={collapseActive}
              >
                <ChevronsDownUp size={14} aria-hidden="true" />
              </Button>
            {/if}
            <Button
              variant="outline"
              size="sm"
              title={settingsOpen ? 'Hide settings' : 'Show settings'}
              aria-label="Settings"
              aria-pressed={settingsOpen}
              onclick={() => (settingsOpen = !settingsOpen)}
            >
              <Settings2 size={14} aria-hidden="true" />
            </Button>
          </div>
        {/if}
      </div>
      {#if trace}
        <Dialog.Description>
          <span class="trace-query">{trace.name || trace.chunk_id}</span>
          <!-- Ingested source text inline (compact, no card) right under the title — the thing
               every stage was extracted from. -->
          {#if trace.text}
            <span class="trace-ingested">
              <span class="trace-ingested__label">Ingested text:</span>
              {trace.text}
            </span>
          {/if}
          <!-- Config / stats line — toggled by the header gear; collapsed by default to keep the
               header compact (mirrors the recall trace dialog). -->
          {#if settingsOpen}
            <span class="trace-config">
              episode {trace.episode_index}/{trace.total} · chunk {shortGraphId(trace.chunk_id)} ·
              group={trace.group_id}
              {#if trace.reference_time}· <span title={trace.reference_time}>t={fmtDate(trace.reference_time, false)}</span>{/if}
              · stages={totals.calls} · {totals.inTok}i/{totals.outTok}o · {totals.ms.toFixed(0)}ms
              · persisted {nodes.length} entities / {edges.length} facts
              {#if trace.invalidated_count}· invalidated={trace.invalidated_count}{/if}
            </span>
          {/if}
        </Dialog.Description>
      {/if}
    </Dialog.Header>

    {#if trace}
      <div class="trace-body">
        <!-- One flat tab row: a tab per pipeline phase (Entities / Attributes / Facts / Other),
             then Result (what landed in the graph), then the caller's optional Corpus tab. -->
        <TraceTabs
          tabs={ingestTabs}
          active={activeTab}
          onSelect={(key) => (activeTab = key)}
          ariaLabel="Ingest trace views"
          variant="subtabs"
          countTone="muted"
        />

        {#if activePhaseObj}
          {@const phase = activePhaseObj}
          {#if phase.hint}<p class="phase-hint">{phase.hint}</p>{/if}

            {#each phase.groups as group (group.node)}
              <section class="stage-group">
                <h3 class="stage-group__title">
                  {group.label}
                  {#if group.stages.length > 1}<span class="stage-group__count">×{group.stages.length}</span>{/if}
                </h3>

                {#if group.node === 'dedup_entities_auto'}
                  <!-- Consolidated "merge map": all non-LLM auto-merges in one scannable table. -->
                  {@const gidx = group.stages[0].idx}
                  {@const merges = dedupMerges(group)}
                  <StageCard
                    collapsed={isCollapsed(gidx)}
                    onToggle={() => toggleStage(gidx)}
                    accent="dedup"
                    badge="dedup"
                    pills={[{ value: merges.length, title: 'Auto-merges' }]}
                    expandTitle="Expand"
                    collapseTitle="Collapse"
                    bodyPadded
                  >
                    {#snippet label()}Merge map{/snippet}
                    {#snippet meta()}auto-merges · deterministic (no LLM){/snippet}
                        <p class="phase-hint">
                          Exact-name / fuzzy MinHash collapses — each freshly-extracted entity reused an
                          existing node without an LLM call.
                        </p>
                        <TraceTable out>
                            <thead>
                              <tr>
                                <th class="num">#</th>
                                <th>Extracted entity</th>
                                <th class="arrow-col"></th>
                                <th>Merged into (kept)</th>
                                <th>Kept summary</th>
                              </tr>
                            </thead>
                            <tbody>
                              {#each merges as mg, mi (mg.idx)}
                                <tr>
                                  <td class="num">{mi + 1}</td>
                                  <td class="entity">
                                    {briefName(mg.from)}
                                    {#if briefType(mg.from)}<span class="type-dim">· {briefType(mg.from)}</span>{/if}
                                  </td>
                                  <td class="arrow-col">→</td>
                                  <td class="entity">
                                    {briefName(mg.into)}
                                    {#if briefType(mg.into)}<span class="type-dim">· {briefType(mg.into)}</span>{/if}
                                  </td>
                                  <td class="cell">{mg.into.summary || '—'}</td>
                                </tr>
                              {/each}
                            </tbody>
                        </TraceTable>
                        <button
                          type="button"
                          class="prompt-toggle"
                          aria-expanded={isJsonOpen(gidx)}
                          onclick={() => toggleJson(gidx)}
                        >
                          {isJsonOpen(gidx) ? '\u25BE' : '\u25B8'} Raw JSON
                        </button>
                    {#if isJsonOpen(gidx)}
                      <pre class="output-block__json">{dedupJson(group)}</pre>
                    {/if}
                  </StageCard>
                {:else}
                  {#each group.stages as { stage, idx } (idx)}
                    {@const ov = outputView(stage)}
                    {@const iv = inputView(stage)}
                    {@const rfv = group.node === 'resolve_facts' ? resolveFactsView(stage) : null}
                    {@const ee = group.node === 'extract_entities' ? extractedEntities(stage) : null}
                    {@const count = stageCount(stage, group.node)}
                    <StageCard
                      collapsed={isCollapsed(idx)}
                      onToggle={() => toggleStage(idx)}
                      accent={stage.source}
                      badge={stage.source !== 'llm' ? stage.source : undefined}
                      pills={count !== null ? [{ value: count, title: 'Items produced by this stage' }] : []}
                      bodyPadded
                    >
                      {#snippet label()}{stage.label}{/snippet}
                      {#snippet meta()}{stageMeta(stage)}{/snippet}
                          {#if iv.kind !== 'empty'}
                            <div class="output-block">
                              <span class="output-block__label">Input — what this stage was given</span>
                              {@render viewTable(iv)}
                            </div>
                          {/if}

                          <div class="output-block">
                            {#if rfv}
                              {@render factVerdict(rfv)}
                            {:else if ee}
                              {@render entitiesTable(ee)}
                            {:else if ov.kind === 'empty'}
                              <p class="trace-empty">No structured output.</p>
                            {:else}
                              {@render viewTable(ov)}
                            {/if}

                            <!-- Prompt sits right before the Raw JSON fallback — both are the
                                 raw, click-to-reveal detail behind the structured view above. -->
                            {#if messages(stage).length}
                              <button
                                type="button"
                                class="prompt-toggle"
                                aria-expanded={isPromptOpen(idx)}
                                onclick={() => togglePrompt(idx)}
                              >
                                {isPromptOpen(idx) ? '▾' : '▸'} Prompt ({messages(stage).length} messages) — the context this stage ran on
                              </button>
                              {#if isPromptOpen(idx)}
                                <div class="prompt-list">
                                  {#each messages(stage) as msg, mi (mi)}
                                    <div class="prompt-msg">
                                      <span class="prompt-msg__role">{msg.role}</span>
                                      <pre class="prompt-msg__content">{msg.content}</pre>
                                    </div>
                                  {/each}
                                </div>
                              {/if}
                            {/if}

                            <button
                              type="button"
                              class="prompt-toggle"
                              aria-expanded={isJsonOpen(idx)}
                              onclick={() => toggleJson(idx)}
                            >
                              {isJsonOpen(idx) ? '\u25BE' : '\u25B8'} Raw JSON
                            </button>
                            {#if isJsonOpen(idx)}
                              <pre class="output-block__json">{prettyOutput(stage)}</pre>
                            {/if}
                          </div>
                    </StageCard>
                  {/each}
                {/if}
              </section>
            {/each}
        {:else if activeTab === RESULT_TAB}
          <!-- Result tab: what actually landed in the graph (AddEpisodeResults). -->
          <section class="result-section">
            <h3 class="stage-group__title">Entities ({nodes.length})</h3>
            {#if nodes.length}
              <TraceTable>
                  <thead>
                    <tr>
                      <th class="num">#</th>
                      <th>Entity</th>
                      <th>Type</th>
                      <th>Summary</th>
                      <th>UUID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each nodes as n, ni (n.uuid + ':' + ni)}
                      <tr>
                        <td class="num">{ni + 1}</td>
                        <td class="entity">{n.name || '—'}</td>
                        <td class="rel">{n.entity_type || '—'}</td>
                        <td class="fact">{n.summary || '—'}</td>
                        <td class="uuid" title={n.uuid}>{shortGraphId(n.uuid)}</td>
                      </tr>
                    {/each}
                  </tbody>
              </TraceTable>
            {:else}
              <p class="trace-empty">No entities persisted.</p>
            {/if}

            <h3 class="stage-group__title">Facts ({edges.length})</h3>
            {#if edges.length}
              <TraceTable>
                  <thead>
                    <tr>
                      <th class="num">#</th>
                      <th class="vstate" title="Validity: current (✓) vs superseded (✗)">v</th>
                      <th>Fact</th>
                      <th>Relation</th>
                      <th>Valid</th>
                      <th>Invalid</th>
                      <th class="num" title="Supporting episodes (chunk_ids)">Eps</th>
                      <th>UUID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each edges as e, ei (e.uuid + ':' + ei)}
                      <tr>
                        <td class="num">{ei + 1}</td>
                        <td class="vstate">
                          <ValidityPill current={isCurrent(e)} title={temporalTitle(e)} />
                        </td>
                        <td class="fact">{e.fact}</td>
                        <td class="rel">{e.name || '—'}</td>
                        <td class="temporal" title={e.valid_at ?? ''}>{fmtDate(e.valid_at, false) || '—'}</td>
                        <td class="temporal" title={e.invalid_at ?? ''}>{fmtDate(e.invalid_at, false) || '—'}</td>
                        <td class="num">{e.episodes?.length ?? 0}</td>
                        <td class="uuid" title={e.uuid}>{shortGraphId(e.uuid)}</td>
                      </tr>
                    {/each}
                  </tbody>
              </TraceTable>
            {:else}
              <p class="trace-empty">No facts persisted.</p>
            {/if}
          </section>
        {:else if activeTab === EXTRA_TAB && extraTab}
          <!-- Caller-provided tab (eval: the searchable source corpus). -->
          <section class="result-section">
            {@render extraTab()}
          </section>
        {/if}
      </div>
    {/if}

    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<style>
  .trace-query {
    display: block;
    font-weight: 600;
    color: var(--foreground);
    margin-bottom: 2px;
  }

  .trace-config {
    display: block;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    color: var(--muted-foreground);
  }

  .trace-head-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-right: 2.25rem;
  }

  .trace-head-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: none;
  }

  /* Episode position between the prev/next arrows (e.g. "23/50"). */
  .trace-nav-pos {
    font-size: 11px;
    font-weight: 600;
    color: var(--muted-foreground);
    font-variant-numeric: tabular-nums;
    min-width: 2.75rem;
    text-align: center;
    white-space: nowrap;
  }

  /* Tab strip moved to <TraceTabs>; phase hint stays here (rendered by this dialog). */
  .phase-hint {
    margin: 0;
    font-size: 11px;
    color: var(--muted-foreground);
  }

  .trace-body {
    display: flex;
    flex-direction: column;
    gap: 16px;
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding-right: 4px;
  }

  .trace-empty {
    margin: 0;
    font-size: 12px;
    color: var(--muted-foreground);
  }

  /* Ingested source text — inline under the title, compact (clamped to 2 lines, no card). */
  .trace-ingested {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
    margin-top: 2px;
    font-size: 12px;
    color: var(--foreground);
    white-space: pre-wrap;
    word-break: break-word;
  }

  .trace-ingested__label {
    font-weight: 600;
    color: var(--muted-foreground);
  }

  .stage-group {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .stage-group__title {
    margin: 4px 0 0;
    font-size: 13px;
    font-weight: 700;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }

  .stage-group__count {
    font-size: 11px;
    font-weight: 600;
    color: var(--muted-foreground);
  }

  /* `.stage-card*` styles moved to <StageCard>. */

  .prompt-toggle {
    align-self: flex-start;
    appearance: none;
    border: none;
    background: transparent;
    padding: 0;
    font-size: 11px;
    font-weight: 600;
    color: var(--muted-foreground);
    cursor: pointer;
  }

  .prompt-toggle:hover {
    color: var(--foreground);
  }

  .prompt-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .prompt-msg {
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 14%, transparent);
    border-radius: 6px;
    overflow: hidden;
  }

  .prompt-msg__role {
    display: block;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground);
    background: color-mix(in srgb, var(--muted-foreground) 8%, transparent);
  }

  .prompt-msg__content,
  .output-block__json {
    margin: 0;
    padding: 8px;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 320px;
    overflow: auto;
  }

  .output-block__label {
    display: block;
    font-size: 11px;
    font-weight: 600;
    color: var(--muted-foreground);
    margin-bottom: 4px;
  }

  .output-block__json {
    border: 1px solid color-mix(in srgb, var(--primary) 25%, transparent);
    border-radius: 6px;
    background: color-mix(in srgb, var(--primary) 6%, transparent);
    margin-top: 6px;
  }

  .output-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .out-scalar {
    margin: 0;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* Extract-entities table: the resolved ontology type as a chip + its muted description. */
  .type-chip {
    display: inline-block;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
    background: color-mix(in srgb, var(--primary) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--primary) 40%, transparent);
  }

  .type-desc {
    color: var(--muted-foreground);
  }

  /* Dedup merge map: dim the entity type (the → arrow column is styled by <TraceTable>). */
  .type-dim {
    color: var(--muted-foreground);
    font-weight: 400;
  }

  /* Resolve/invalidate facts verdict view. */
  .fact-verdict {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .fact-new__text {
    margin: 2px 0 0;
    font-size: 12px;
    font-weight: 600;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .fact-summary {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .fact-badge {
    display: inline-flex;
    align-items: center;
    font-size: 11px;
    font-weight: 600;
    padding: 1px 7px;
    border-radius: 999px;
    border: 1px solid transparent;
    white-space: nowrap;
  }

  .fact-badge--contra {
    color: #b45309;
    background: color-mix(in srgb, #f59e0b 16%, transparent);
    border-color: color-mix(in srgb, #f59e0b 45%, transparent);
  }

  .fact-badge--dup {
    color: #2563eb;
    background: color-mix(in srgb, #2563eb 14%, transparent);
    border-color: color-mix(in srgb, #2563eb 40%, transparent);
  }

  .fact-badge--new {
    color: #16a34a;
    background: color-mix(in srgb, #16a34a 14%, transparent);
    border-color: color-mix(in srgb, #16a34a 40%, transparent);
  }

  .fact-row--hit td {
    background: color-mix(in srgb, #f59e0b 8%, transparent);
  }

  .fact-dim {
    color: var(--muted-foreground);
  }

  .result-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* `.trace-table*` shell + cell styling moved to <TraceTable>. */
</style>
