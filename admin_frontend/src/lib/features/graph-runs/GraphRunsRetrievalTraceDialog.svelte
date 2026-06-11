<script lang="ts">
  import {
    ChevronDown,
    ChevronsDownUp,
    ChevronsUpDown,
    ChevronUp,
    Search,
    Settings2
  } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type {
    RetrievalTraceItem,
    RetrievalTraceRecord,
    RetrievalTraceStage
  } from '$lib/api/graph-runs';
  import { shortGraphId } from './graph-runs-pure';

  let {
    trace,
    onClose,
    // Optional eval context — when this dialog is opened from the knowledge eval (per-leg
    // retrieval trace), the question's ideal answer and the model's answer are surfaced in the
    // header so the recalled facts can be read against the expected/produced answer. Absent on
    // the plain Graph-Runs path (a bare pipeline trace with no eval to compare against).
    idealAnswer = '',
    llmAnswer = '',
    // Optional extra tab (eval: the source corpus, searchable) rendered after the lane tabs.
    // Decoupled via a snippet so this Graph-Runs component stays generic — the caller owns the
    // content. Both props must be set for the tab to appear.
    extraTabLabel = '',
    extraTab
  }: {
    trace: RetrievalTraceRecord | null;
    onClose: () => void;
    idealAnswer?: string;
    llmAnswer?: string;
    extraTabLabel?: string;
    // Receives the dialog's top-search text so the extra (corpus) tab filters off the same input
    // instead of carrying its own search box.
    extraTab?: import('svelte').Snippet<[string]>;
  } = $props();

  // Sentinel lane key for the optional extra (caller-provided) tab.
  const EXTRA_TAB = '__extra__';
  const hasExtraTab = $derived(!!extraTab && !!extraTabLabel);

  // Per-stage collapse state, keyed by the stage's index in `trace.stages` (stable across
  // the lane grouping). Every stage starts COLLAPSED (all tables in all tabs folded by default);
  // re-seeded whenever a different trace opens.
  let collapsed = $state<Set<number>>(new Set());

  // When on, rows NOT in their lane's final result set (the last stage) are struck through —
  // so candidate/hop/rank rows that didn't survive to the result are visually demoted. On by
  // default so dropped rows read as dropped without first toggling.
  let strikeDropped = $state(true);

  // Free-text filter highlight: typed text is <mark>-ed wherever it appears in a stage table
  // (and the stage labels), and each tab shows how many distinct items in its lane match.
  let search = $state('');

  // The config/settings line (recipe · temporal · top_k …) is collapsed by default to save
  // header space; the disclosure below it expands the line on demand.
  let settingsOpen = $state(false);

  // Which long summary/content cells the user expanded past the 3-line clamp, keyed by
  // `${stageIdx}:${uuid}:${col}` so each cell toggles independently.
  let expandedCells = $state<Set<string>>(new Set());

  $effect(() => {
    void trace;
    // Seed every stage index as collapsed → all tables fold by default on open.
    collapsed = new Set(trace ? trace.stages.map((_, i) => i) : []);
    strikeDropped = true;
    search = '';
    settingsOpen = false;
    expandedCells = new Set();
    sortByStage = new Map();
  });

  const cellKey = (index: number, uuid: string, col: string): string => `${index}:${uuid}:${col}`;
  const isCellOpen = (key: string): boolean => expandedCells.has(key);

  function toggleCell(key: string): void {
    const next = new Set(expandedCells);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    expandedCells = next;
  }

  // Only offer the more/less toggle when the text is long enough to actually clamp (~3 lines);
  // short summaries render in full with no dangling control.
  const isLongText = (text: string | null | undefined): boolean => (text?.length ?? 0) > 140;

  // ── Text-search highlight ───────────────────────────────────────────────────────────────
  // Split a cell's plain text into matched / unmatched segments so matches can be wrapped in
  // <mark> without ever touching {@html} (the text stays data-bound, so it can't inject markup).
  function splitHL(text: string | null | undefined): { text: string; hit: boolean }[] {
    const value = text ?? '';
    const q = search.trim();
    if (!q || !value) return [{ text: value, hit: false }];
    const haystack = value.toLowerCase();
    const needle = q.toLowerCase();
    const out: { text: string; hit: boolean }[] = [];
    let i = 0;
    while (i < value.length) {
      const at = haystack.indexOf(needle, i);
      if (at === -1) {
        out.push({ text: value.slice(i), hit: false });
        break;
      }
      if (at > i) out.push({ text: value.slice(i, at), hit: false });
      out.push({ text: value.slice(at, at + needle.length), hit: true });
      i = at + needle.length;
    }
    return out;
  }

  /** The searchable text of an item, by lane (the same columns the table renders). */
  function itemText(item: RetrievalTraceItem, lane: string): string {
    if (lane === 'edge') return [item.fact, item.name, item.uuid].filter(Boolean).join(' ');
    if (lane === 'node')
      return [item.name, item.entity_type, item.summary, item.uuid].filter(Boolean).join(' ');
    return [item.content, item.source, item.uuid].filter(Boolean).join(' ');
  }

  /** Per-lane count of DISTINCT matching items (by uuid) — shown next to each tab while searching. */
  const laneMatchCounts = $derived.by<Map<string, number>>(() => {
    const m = new Map<string, number>();
    const q = search.trim().toLowerCase();
    if (!q) return m;
    for (const lane of lanes) {
      const hits = new Set<string>();
      for (const { stage } of lane.stages) {
        for (const item of stage.items) {
          if (itemText(item, lane.lane).toLowerCase().includes(q)) hits.add(item.uuid);
        }
      }
      m.set(lane.lane, hits.size);
    }
    return m;
  });

  const searching = $derived(search.trim().length > 0);

  /** How many of a stage's rows match the current search (drives the highlighted count pill). */
  function stageMatchCount(stage: RetrievalTraceStage, laneKey: string): number {
    const q = search.trim().toLowerCase();
    if (!q) return 0;
    let n = 0;
    for (const item of stage.items) {
      if (itemText(item, laneKey).toLowerCase().includes(q)) n++;
    }
    return n;
  }

  /** Stage header label — the temporal lens spells out that rows are ordered by date, not score. */
  function stageHeadLabel(stage: RetrievalTraceStage): string {
    return stage.kind === 'temporal' ? 'Temporal lens (ordered by date)' : stage.label;
  }

  function toggleStage(index: number): void {
    const next = new Set(collapsed);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    collapsed = next;
  }

  const isCollapsed = (index: number): boolean => collapsed.has(index);

  // ── Lane model ────────────────────────────────────────────────────────────────────────
  // The pipeline runs one independent sub-pipeline per entity type. We group the flat stage
  // list into lanes so a human reads it as: candidates (parallel legs) → fuse/rank → (temporal)
  // → kept, once per type. The shared `embed` stage (lane `query`) is shown as a thin header.
  const LANE_ORDER = ['edge', 'node', 'episode'] as const;
  const LANE_TITLE: Record<string, string> = {
    edge: 'Facts',
    node: 'Entities',
    episode: 'Episodes'
  };
  const LANE_HINT: Record<string, string> = {
    edge: 'relationship triples (subject → relation → object)',
    node: 'entity attribute memories (name · type · summary)',
    episode: 'raw recalled turns / chunks (BM25)'
  };

  type StageRef = { stage: RetrievalTraceStage; idx: number };
  type Leg = { tag: string; cls: string; uuids: Set<string> };
  type FlowSeg = {
    label: string;
    count: number;
    emphasis: 'leg' | 'rank' | 'final';
    /** Index in `trace.stages` so a pill can scroll to (and expand) its stage. */
    idx: number;
  };
  type Lane = {
    lane: string;
    title: string;
    hint: string;
    stages: StageRef[];
    legs: Leg[];
    flow: FlowSeg[];
    /** uuids of the lane's terminal stage (temporal for edges, rank otherwise) = the result. */
    finalUuids: Set<string>;
  };

  function legTag(stage: RetrievalTraceStage): { tag: string; cls: string } {
    if (stage.kind === 'hop') return { tag: 'hop', cls: 'hop' };
    const method = String(stage.meta?.method ?? '');
    if (method === 'bm25') return { tag: 'BM25', cls: 'kw' };
    if (method === 'cosine_similarity') return { tag: 'cosine', cls: 'mean' };
    return { tag: stage.label, cls: 'kw' };
  }

  function rerankerLabel(stage: RetrievalTraceStage): string {
    const r = stage.meta?.reranker;
    if (typeof r === 'string' && r) return r;
    const parts = stage.label.split('·');
    return (parts[1] ?? stage.label).trim();
  }

  const embedStage = $derived.by<RetrievalTraceStage | null>(() => {
    if (!trace) return null;
    return trace.stages.find((s) => s.kind === 'embed' || s.lane === 'query') ?? null;
  });

  const lanes = $derived.by<Lane[]>(() => {
    if (!trace) return [];
    const out: Lane[] = [];
    for (const laneKey of LANE_ORDER) {
      const stages: StageRef[] = [];
      trace.stages.forEach((stage, idx) => {
        if (stage.lane === laneKey && stage.kind !== 'embed') stages.push({ stage, idx });
      });
      if (stages.length === 0) continue;

      // Candidate + hop stages double as the provenance legs for the rank stage.
      const legs: Leg[] = stages
        .filter(({ stage }) => stage.kind === 'candidate' || stage.kind === 'hop')
        .map(({ stage }) => {
          const { tag, cls } = legTag(stage);
          return { tag, cls, uuids: new Set(stage.items.map((it) => it.uuid)) };
        });

      // Funnel: each leg's yield → rank → (temporal kept). Counts use item arrays (robust).
      // Each segment carries its stage idx so the pill can jump to that stage's table.
      const flow: FlowSeg[] = [];
      for (const { stage, idx } of stages) {
        if (stage.kind === 'candidate' || stage.kind === 'hop') {
          flow.push({ label: legTag(stage).tag, count: stage.items.length, emphasis: 'leg', idx });
        } else if (stage.kind === 'rank') {
          flow.push({ label: rerankerLabel(stage), count: stage.items.length, emphasis: 'rank', idx });
        } else if (stage.kind === 'temporal') {
          flow.push({ label: 'kept', count: stage.items.length, emphasis: 'final', idx });
        }
      }

      // Final result set = the last stage's items (whatever ends the lane: temporal for edges,
      // rank for nodes/episodes). Robust to pipeline shape — no hardcoded terminal kind.
      const finalStage = stages[stages.length - 1]?.stage;
      const finalUuids = new Set<string>((finalStage?.items ?? []).map((it) => it.uuid));

      out.push({
        lane: laneKey,
        title: LANE_TITLE[laneKey] ?? laneKey,
        hint: LANE_HINT[laneKey] ?? '',
        stages,
        legs,
        flow,
        finalUuids
      });
    }
    return out;
  });

  // ── Active tab ──────────────────────────────────────────────────────────────────────────
  // One tab per present lane (Facts / Entities / Episodes). Kept valid as lanes change.
  let activeTab = $state<string>('');

  $effect(() => {
    const keys = lanes.map((l) => l.lane);
    // Keep the active tab valid as lanes change — but allow the caller's extra tab to stay
    // selected (it isn't a lane). Only snap back to the first lane on a genuinely stale key.
    if (!keys.includes(activeTab) && !(hasExtraTab && activeTab === EXTRA_TAB)) {
      activeTab = keys[0] ?? '';
    }
  });

  const activeLane = $derived<Lane | null>(
    lanes.find((l) => l.lane === activeTab) ?? lanes[0] ?? null
  );

  /** Expand/Collapse apply to the ACTIVE tab's stages only (per-tab, not global). */
  function expandActive(): void {
    if (!activeLane) return;
    const next = new Set(collapsed);
    for (const { idx } of activeLane.stages) next.delete(idx);
    collapsed = next;
  }

  function collapseActive(): void {
    if (!activeLane) return;
    const next = new Set(collapsed);
    for (const { idx } of activeLane.stages) next.add(idx);
    collapsed = next;
  }

  const stageDomId = (idx: number): string => `trace-stage-${idx}`;

  /** Pill click → ensure the stage is expanded, then smooth-scroll it into view. */
  function jumpToStage(idx: number): void {
    if (collapsed.has(idx)) {
      const next = new Set(collapsed);
      next.delete(idx);
      collapsed = next;
    }
    requestAnimationFrame(() => {
      document
        .getElementById(stageDomId(idx))
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  /** For a ranked item, which candidate/hop legs contributed it (drives fusion badges). */
  function provenance(item: RetrievalTraceItem, lane: Lane): Leg[] {
    return lane.legs.filter((leg) => leg.uuids.has(item.uuid));
  }

  function isRankStage(stage: RetrievalTraceStage): boolean {
    return stage.kind === 'rank';
  }

  // ── Cell formatting ─────────────────────────────────────────────────────────────────────
  function scoreCell(item: RetrievalTraceItem): string {
    return item.score === null || item.score === undefined ? '—' : item.score.toFixed(4);
  }

  // A fact is "current" iff neither the event-time end (`invalid_at`) nor the system expiry
  // (`expired_at`) is set. In graphiti 0.29.1 these are always set together (see edges.py),
  // so either one flips the fact to superseded. Drives the green/red validity pill.
  const isCurrent = (item: RetrievalTraceItem): boolean => !(item.invalid_at || item.expired_at);

  /** Full bi-temporal detail (incl. the system expired_at) for the validity pill tooltip. */
  function temporalTitle(item: RetrievalTraceItem): string {
    const lines: string[] = [];
    if (item.valid_at) lines.push(`became true: ${item.valid_at}`);
    if (item.invalid_at) lines.push(`stopped being true: ${item.invalid_at}`);
    if (item.expired_at) lines.push(`system-expired: ${item.expired_at}`);
    return lines.length ? lines.join('\n') : 'no temporal bounds';
  }

  function shortDate(iso: string | null | undefined): string {
    return iso ? String(iso).slice(0, 10) : '';
  }

  function episodeSource(item: RetrievalTraceItem): string {
    const src = (item.source ?? '').replace(/^EpisodeType\./, '');
    return src || '—';
  }

  /** Compact metadata line per stage (counts / limits / timings), order-stable. */
  function stageMetaSummary(stage: RetrievalTraceStage): string {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(stage.meta ?? {})) {
      if (v === null || v === undefined || v === '') continue;
      parts.push(`${k}=${v}`);
    }
    if (Number.isFinite(stage.elapsed_ms) && stage.elapsed_ms > 0) {
      parts.push(`${stage.elapsed_ms.toFixed(1)}ms`);
    }
    return parts.join(' · ');
  }

  const hasItems = (stage: RetrievalTraceStage): boolean =>
    Array.isArray(stage.items) && stage.items.length > 0;

  /** The caller-anchored BFS candidate leg (origins passed into the search, not derived). */
  const isExplicitBfsLeg = (stage: RetrievalTraceStage): boolean =>
    stage.kind === 'candidate' && stage.meta?.method === 'bfs';

  // ── Per-column sort ─────────────────────────────────────────────────────────────────────
  // Click a column header to sort that stage's rows: asc → desc → original (tri-state). Keyed
  // by the stage's idx so each table sorts independently. Reset when a new trace opens. The
  // temporal lane arrives pre-sorted by valid_at from the backend; this lets the user override
  // that (or any other table) per column.
  type SortDir = 1 | -1;
  let sortByStage = $state<Map<number, { key: string; dir: SortDir }>>(new Map());

  function toggleSort(index: number, key: string): void {
    const next = new Map(sortByStage);
    const cur = next.get(index);
    if (!cur || cur.key !== key) next.set(index, { key, dir: 1 });
    else if (cur.dir === 1) next.set(index, { key, dir: -1 });
    else next.delete(index); // third click restores the stage's original (backend) order
    sortByStage = next;
  }

  // The effective sort shown in the headers: the user's explicit per-column override, else the
  // stage's implicit order. The temporal lens arrives pre-sorted by valid_at (ascending) from the
  // backend, so we surface that as a Valid-column arrow even with no override — otherwise the
  // header looks unsorted when it isn't. (Matches `displayItems`, which leaves that order as-is.)
  function effectiveSort(index: number): { key: string; dir: SortDir } | null {
    const cur = sortByStage.get(index);
    if (cur) return cur;
    if (trace?.stages[index]?.kind === 'temporal') return { key: 'valid', dir: 1 };
    return null;
  }

  /** Header arrow for the active sort column: ▲ asc, ▼ desc, '' when this column isn't sorted. */
  function sortArrow(index: number, key: string): string {
    const cur = effectiveSort(index);
    if (!cur || cur.key !== key) return '';
    return cur.dir === 1 ? '▲' : '▼';
  }

  function ariaSort(index: number, key: string): 'ascending' | 'descending' | 'none' {
    const cur = effectiveSort(index);
    if (!cur || cur.key !== key) return 'none';
    return cur.dir === 1 ? 'ascending' : 'descending';
  }

  /** Comparable value for a column key. Strings lowercased; missing values sort to an extreme. */
  function sortValue(item: RetrievalTraceItem, key: string): string | number {
    switch (key) {
      case 'score':
        return item.score ?? Number.NEGATIVE_INFINITY;
      case 'v':
        return isCurrent(item) ? 1 : 0;
      case 'eps':
        return item.episodes?.length ?? 0;
      case 'valid':
      case 'when':
        return item.valid_at ?? '';
      case 'invalid':
        return item.invalid_at ?? '';
      case 'fact':
        return (item.fact ?? '').toLowerCase();
      case 'rel':
        return (item.name ?? '').toLowerCase();
      case 'entity':
        return (item.name ?? '').toLowerCase();
      case 'type':
        return (item.entity_type ?? '').toLowerCase();
      case 'summary':
        return (item.summary ?? '').toLowerCase();
      case 'content':
        return (item.content ?? '').toLowerCase();
      case 'source':
        return (item.source ?? '').toLowerCase();
      case 'uuid':
        return item.uuid;
      default:
        return '';
    }
  }

  /** A stage's rows in display order — the active per-column sort, else the stored order. */
  function displayItems(stage: RetrievalTraceStage, index: number): RetrievalTraceItem[] {
    const cur = sortByStage.get(index);
    if (!cur) return stage.items;
    const { key, dir } = cur;
    return [...stage.items].sort((a, b) => {
      const av = sortValue(a, key);
      const bv = sortValue(b, key);
      if (av < bv) return -dir;
      if (av > bv) return dir;
      return 0;
    });
  }
</script>

<!-- Highlight the active search text inside a plain-text cell. Splits on the query (no {@html},
     so it's injection-safe) and wraps matches in <mark>. Top-level so it's a local snippet. -->
{#snippet hl(text: string | null | undefined)}{#each splitHL(text) as seg, i (i)}{#if seg.hit}<mark class="search-hit">{seg.text}</mark>{:else}{seg.text}{/if}{/each}{/snippet}

<!-- A potentially-long cell (entity summary / episode content): clamped to 3 lines with a
     more/less toggle, search matches still highlighted. Top-level local snippet. -->
{#snippet clampCell(text: string, key: string)}
  <div class="clamp" class:clamp--open={isCellOpen(key)}>{@render hl(text)}</div>
  {#if isLongText(text)}
    <button type="button" class="clamp-toggle" onclick={() => toggleCell(key)}>
      {#if isCellOpen(key)}<ChevronUp size={11} aria-hidden="true" />less{:else}<ChevronDown size={11} aria-hidden="true" />more{/if}
    </button>
  {/if}
{/snippet}

<!-- Sortable column header: click to cycle asc → desc → original order (per stage). Declared at
     the top level so it's a local snippet, not a prop of <Dialog.Content>. -->
{#snippet sortTh(index: number, key: string, label: string, cls: string, title: string)}
  <th
    class={cls ? `${cls} sortable` : 'sortable'}
    {title}
    aria-sort={ariaSort(index, key)}
    onclick={() => toggleSort(index, key)}
  >
    {label}<span class="th-arrow">{sortArrow(index, key)}</span>
  </th>
{/snippet}

<Dialog.Root open={trace !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content
    class="retrieval-trace-content sm:max-w-[min(96vw,1200px)] flex flex-col h-[90vh]"
  >
    <Dialog.Header>
      <!-- Title · search · actions all share one line to keep the header compact. -->
      <div class="trace-head-row">
        <Dialog.Title>Retrieval pipeline trace</Dialog.Title>
        {#if trace}
          <div class="trace-search">
            <Search size={14} aria-hidden="true" class="trace-search__icon" />
            <input
              type="search"
              class="trace-search__input"
              placeholder="Search facts, entities, episodes…"
              bind:value={search}
            />
          </div>
        {/if}
        {#if trace && activeLane}
          <div class="trace-head-actions">
            <Button
              variant="outline"
              size="sm"
              title="Strike through rows not in the final result set (per tab)"
              aria-pressed={strikeDropped}
              onclick={() => (strikeDropped = !strikeDropped)}
            >
              <span class="dropped-label" class:dropped-label--on={strikeDropped}>Dropped</span>
            </Button>
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
        <!-- Question → Answer → Ideal (the eval context); only the question is always present. -->
        <div class="trace-answers">
          <div class="trace-answer">
            <span class="trace-answer__label trace-answer__label--q">Question</span>
            <span class="trace-answer__text">{@render hl(trace.query)}</span>
          </div>
          {#if llmAnswer}
            <div class="trace-answer">
              <span class="trace-answer__label trace-answer__label--llm">Answer</span>
              <span class="trace-answer__text">{@render hl(llmAnswer)}</span>
            </div>
          {/if}
          {#if idealAnswer}
            <div class="trace-answer">
              <span class="trace-answer__label trace-answer__label--ideal">Ideal</span>
              <span class="trace-answer__text">{@render hl(idealAnswer)}</span>
            </div>
          {/if}
        </div>
        <!-- Config line — toggled by the Settings (gear) button in the header actions; only takes
             a line when expanded, so the collapsed state costs no header height. -->
        {#if settingsOpen}
          <span class="trace-config">
            recipe={trace.recipe} · temporal={trace.temporal} · top_k={trace.num_results} ·
            candidate_limit=2×top_k={2 * trace.num_results} · sim_min_score={trace.sim_min_score} ·
            k_hop={trace.k_hop} · group={trace.group_id}
            {#if embedStage}· embed {embedStage.elapsed_ms.toFixed(1)}ms{/if}
          </span>
        {/if}
      {/if}
    </Dialog.Header>

    {#if trace}
      <!-- One tab per present lane; the workflow pills + stage tables render the active lane. -->
      <div class="trace-tabs" role="tablist" aria-label="Retrieval lanes">
        {#each lanes as lane (lane.lane)}
          <button
            type="button"
            role="tab"
            class="trace-tab"
            class:trace-tab--active={lane.lane === activeTab}
            aria-selected={lane.lane === activeTab}
            onclick={() => (activeTab = lane.lane)}
          >
            {lane.title}
            {#if searching}<span class="trace-tab__count">({laneMatchCounts.get(lane.lane) ?? 0})</span>{/if}
          </button>
        {/each}
        {#if hasExtraTab}
          <button
            type="button"
            role="tab"
            class="trace-tab"
            class:trace-tab--active={activeTab === EXTRA_TAB}
            aria-selected={activeTab === EXTRA_TAB}
            onclick={() => (activeTab = EXTRA_TAB)}
          >
            {extraTabLabel}
          </button>
        {/if}
      </div>

      {#if hasExtraTab && activeTab === EXTRA_TAB}
        <!-- Caller-provided tab (eval: the source corpus) — driven by the dialog's top search. -->
        <div class="trace-lanes">
          <div class="p-4">{@render extraTab?.(search)}</div>
        </div>
      {:else if activeLane}
        {@const lane = activeLane}
        <div class="trace-lanes">
          <section class="lane" data-lane={lane.lane}>
            <p class="lane__hint">{lane.hint}</p>

            <!-- Workflow pills: parallel legs → rank → temporal lens. Click to jump to a stage. -->
            <nav class="flow" aria-label={`${lane.title} stages`}>
              {#each lane.flow as seg, fi (fi)}
                {#if fi > 0}<span class="flow__arrow">→</span>{/if}
                <button
                  type="button"
                  class="flow__seg flow__seg--{seg.emphasis}"
                  title={`Jump to ${seg.label}`}
                  onclick={() => jumpToStage(seg.idx)}
                >
                  <span class="flow__count">{seg.count}</span>
                  <span class="flow__label">{seg.label}</span>
                </button>
              {/each}
            </nav>

            {#each lane.stages as { stage, idx } (idx)}
              <div class="trace-stage" id={stageDomId(idx)} data-kind={stage.kind}>
                <header class="trace-stage__head">
                  <!-- Whole title row toggles the section (not just the caret). -->
                  <button
                    type="button"
                    class="trace-stage__titlebtn"
                    aria-expanded={!isCollapsed(idx)}
                    title={isCollapsed(idx) ? 'Expand stage' : 'Collapse stage'}
                    onclick={() => toggleStage(idx)}
                  >
                    <span class="trace-stage__caret">{isCollapsed(idx) ? '\u25B8' : '\u25BE'}</span>
                    <span class="trace-stage__label">{@render hl(stageHeadLabel(stage))}</span>
                    <span class="trace-stage__pill" title="Rows returned by this stage">
                      {stage.items.length}
                    </span>
                    {#if searching}
                      {@const mc = stageMatchCount(stage, lane.lane)}
                      {#if mc > 0}
                        <span class="trace-stage__pill trace-stage__pill--hit" title="Search matches in this stage">
                          {mc}
                        </span>
                      {/if}
                    {/if}
                  </button>
                  <span class="trace-stage__meta">{stageMetaSummary(stage)}</span>
                </header>

                {#if !isCollapsed(idx)}
                  {#if isExplicitBfsLeg(stage)}
                    <p class="trace-stage__note">
                      Origins for this leg are supplied by the search caller; with none passed (a
                      plain query), it stays empty and graph expansion falls back to the hop BFS
                      below.
                    </p>
                  {/if}
                  {#if stage.kind === 'temporal'}
                    <p class="trace-stage__note">
                      Echo of the rerank result — this stage applies no further filtering or
                      ranking. Rows are re-sorted by <strong>Valid</strong> (the date the fact
                      became true) so the set reads as a timeline; the answer itself uses the
                      rerank order above. Click any column header to re-sort.
                    </p>
                  {/if}
                  {#if hasItems(stage)}
                    <div class="trace-table-wrap">
                      <table class="trace-table">
                        <thead>
                          {#if lane.lane === 'edge'}
                            <tr>
                              <th class="num">#</th>
                              {@render sortTh(idx, 'score', 'Score', 'num', '')}
                              {@render sortTh(idx, 'v', 'v', 'vstate', 'Validity: current (✓) vs superseded (✗)')}
                              {@render sortTh(idx, 'fact', 'Fact', '', '')}
                              {@render sortTh(idx, 'rel', 'Relation', '', '')}
                              {@render sortTh(idx, 'valid', 'Valid', '', '')}
                              {@render sortTh(idx, 'invalid', 'Invalid', '', '')}
                              {@render sortTh(idx, 'eps', 'Eps', 'num', 'Supporting episodes (chunk_ids the fact was extracted from)')}
                              {#if isRankStage(stage)}<th>From</th>{/if}
                              {@render sortTh(idx, 'uuid', 'UUID', '', '')}
                            </tr>
                          {:else if lane.lane === 'node'}
                            <tr>
                              <th class="num">#</th>
                              {@render sortTh(idx, 'score', 'Score', 'num', '')}
                              {@render sortTh(idx, 'entity', 'Entity', '', '')}
                              {@render sortTh(idx, 'type', 'Type', '', '')}
                              {@render sortTh(idx, 'summary', 'Summary', '', '')}
                              {#if isRankStage(stage)}<th>From</th>{/if}
                              {@render sortTh(idx, 'uuid', 'UUID', '', '')}
                            </tr>
                          {:else}
                            <tr>
                              <th class="num">#</th>
                              {@render sortTh(idx, 'score', 'Score', 'num', '')}
                              {@render sortTh(idx, 'content', 'Content', '', '')}
                              {@render sortTh(idx, 'when', 'When', '', '')}
                              {@render sortTh(idx, 'source', 'Source', '', '')}
                              {#if isRankStage(stage)}<th>From</th>{/if}
                              {@render sortTh(idx, 'uuid', 'UUID', '', '')}
                            </tr>
                          {/if}
                        </thead>
                        <tbody>
                          {#each displayItems(stage, idx) as item, ii (item.uuid + ':' + ii)}
                            <tr class:struck={strikeDropped && !lane.finalUuids.has(item.uuid)}>
                              <td class="num">{ii + 1}</td>
                              <td class="num">{scoreCell(item)}</td>
                              {#if lane.lane === 'edge'}
                                <td class="vstate">
                                  <span
                                    class="vpill"
                                    class:vpill--ok={isCurrent(item)}
                                    class:vpill--bad={!isCurrent(item)}
                                    title={temporalTitle(item)}
                                  >
                                    {isCurrent(item) ? '\u2713' : '\u2717'}
                                  </span>
                                </td>
                                <td class="fact">{@render hl(item.fact)}</td>
                                <td class="rel">{#if item.name}{@render hl(item.name)}{:else}—{/if}</td>
                                <td class="temporal">{shortDate(item.valid_at) || '—'}</td>
                                <td class="temporal">{shortDate(item.invalid_at) || '—'}</td>
                                <td class="num">{item.episodes?.length ?? 0}</td>
                              {:else if lane.lane === 'node'}
                                <td class="entity">{#if item.name}{@render hl(item.name)}{:else}—{/if}</td>
                                <td class="rel">{#if item.entity_type}{@render hl(item.entity_type)}{:else}—{/if}</td>
                                <td class="fact">{#if item.summary}{@render clampCell(item.summary, cellKey(idx, item.uuid, 'summary'))}{:else}—{/if}</td>
                              {:else}
                                <td class="fact">{#if item.content}{@render clampCell(item.content, cellKey(idx, item.uuid, 'content'))}{:else}—{/if}</td>
                                <td class="temporal">{shortDate(item.valid_at) || '—'}</td>
                                <td class="rel">{@render hl(episodeSource(item))}</td>
                              {/if}
                              {#if isRankStage(stage)}
                                <td class="from">
                                  {#each provenance(item, lane) as leg (leg.tag)}
                                    <span class="leg-badge leg-badge--{leg.cls}">{leg.tag}</span>
                                  {/each}
                                </td>
                              {/if}
                              <td class="uuid" title={item.uuid}>{@render hl(shortGraphId(item.uuid))}</td>
                            </tr>
                          {/each}
                        </tbody>
                      </table>
                    </div>
                  {:else}
                    <p class="trace-stage__empty">No items at this stage.</p>
                  {/if}
                {/if}
              </div>
            {/each}
          </section>
        </div>
      {/if}
    {/if}

    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<style>
  .trace-config {
    display: block;
    margin-top: 6px;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    color: var(--muted-foreground);
  }

  /* Single scroll region for the whole lane list. It flex-grows to fill the fixed-height
     dialog (`h-[90vh]` on Dialog.Content), so the outer height stays constant regardless of
     which tab is active — only this region scrolls. `min-height: 0` lets it shrink below its
     content so the overflow actually scrolls. Children must NOT shrink (flex: none), otherwise
     the bounded-height flex column squishes each stage to ~1 row (the old double-scroll). */
  .trace-lanes {
    display: flex;
    flex-direction: column;
    gap: 20px;
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding-right: 4px;
  }

  .lane {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* Tab bar: one tab per present lane (Facts / Entities / Episodes). */
  .trace-tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid color-mix(in srgb, var(--muted-foreground) 22%, transparent);
  }

  .trace-tab {
    appearance: none;
    border: none;
    background: transparent;
    padding: 8px 14px;
    margin-bottom: -1px;
    border-bottom: 2px solid transparent;
    font-size: 13px;
    font-weight: 600;
    color: var(--muted-foreground);
    cursor: pointer;
  }

  .trace-tab:hover {
    color: var(--foreground);
  }

  .trace-tab--active {
    color: var(--foreground);
    border-bottom-color: var(--primary);
  }

  .trace-tab__count {
    margin-left: 4px;
    font-size: 11px;
    font-weight: 700;
    color: var(--primary);
    font-variant-numeric: tabular-nums;
  }

  .trace-tab:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
    border-radius: 4px;
  }

  .lane__hint {
    margin: 0 0 2px;
    font-size: 12px;
    color: var(--muted-foreground);
  }

  /* Funnel strip — the at-a-glance mental model of the lane. Sticky so the clickable stage
     pills stay reachable while scrolling the tables; opaque bg + z-index so rows pass under it. */
  .flow {
    position: sticky;
    top: 0;
    z-index: 2;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 6px 0;
    background: var(--popover);
    border-bottom: 1px solid color-mix(in srgb, var(--muted-foreground) 16%, transparent);
  }

  .flow__arrow {
    color: var(--muted-foreground);
    font-size: 12px;
  }

  .flow__seg {
    display: inline-flex;
    align-items: baseline;
    gap: 5px;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 25%, transparent);
    background: color-mix(in srgb, var(--muted-foreground) 8%, transparent);
    font-size: 11px;
    cursor: pointer;
    transition:
      transform 0.08s ease,
      box-shadow 0.08s ease,
      background 0.08s ease;
  }

  .flow__seg:hover {
    background: color-mix(in srgb, var(--muted-foreground) 16%, transparent);
    transform: translateY(-1px);
  }

  .flow__seg:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 1px;
  }

  .flow__seg--rank {
    border-color: color-mix(in srgb, var(--primary) 45%, transparent);
    background: color-mix(in srgb, var(--primary) 12%, transparent);
  }

  .flow__seg--final {
    border-color: color-mix(in srgb, var(--primary) 70%, transparent);
    background: color-mix(in srgb, var(--primary) 22%, transparent);
    font-weight: 600;
  }

  .flow__count {
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--foreground);
  }

  .flow__label {
    color: var(--muted-foreground);
  }

  .trace-stage {
    flex: none;
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 18%, transparent);
    border-radius: 8px;
    overflow: hidden;
  }

  /* Title row carries the expand/collapse-all actions on the right; pad past the absolute
     close (X) button so they never overlap it. */
  .trace-head-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-right: 2.25rem;
  }

  .trace-head-actions {
    display: flex;
    gap: 6px;
    flex: none;
  }

  /* "Dropped" toggle: when on, the label itself reads as struck-through (the action it applies to
     dropped rows) and tints to primary — replacing the old filled-button highlight. */
  .dropped-label--on {
    text-decoration: line-through;
    text-decoration-thickness: 2px;
    color: var(--primary);
  }

  /* Header search box — shares the title line (flex-grows in the middle) to save header space;
     highlights matches in the tables and drives the per-tab / per-stage hit counts. */
  .trace-search {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1 1 auto;
    min-width: 120px;
    max-width: 380px;
    padding: 4px 8px;
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 25%, transparent);
    border-radius: 6px;
    background: color-mix(in srgb, var(--muted-foreground) 6%, transparent);
  }

  .trace-search :global(.trace-search__icon) {
    flex: none;
    color: var(--muted-foreground);
  }

  .trace-search__input {
    flex: 1;
    min-width: 0;
    appearance: none;
    border: none;
    background: transparent;
    outline: none;
    font-size: 12px;
    color: var(--foreground);
  }

  /* Search matches wrapped in <mark> — yellow-ish, theme-aware, readable on hovered rows. */
  .search-hit {
    background: color-mix(in srgb, #facc15 55%, transparent);
    color: inherit;
    border-radius: 2px;
    padding: 0 1px;
  }

  /* Question → Answer → Ideal. Question is always present; Answer/Ideal only in eval context. */
  .trace-answers {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 6px;
  }

  .trace-answer {
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 12px;
  }

  .trace-answer__label {
    flex: none;
    width: 58px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground);
  }

  .trace-answer__label--q {
    color: var(--foreground);
  }

  .trace-answer__label--llm {
    color: var(--primary);
  }

  .trace-answer__label--ideal {
    color: #16a34a;
  }

  .trace-answer__text {
    color: var(--foreground);
    white-space: pre-wrap;
    word-break: break-word;
  }

  .trace-stage__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 10px;
    background: color-mix(in srgb, var(--muted-foreground) 8%, transparent);
  }

  /* Whole title row is the toggle — caret + label + count pills, all clickable. */
  .trace-stage__titlebtn {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--foreground);
    cursor: pointer;
    text-align: left;
  }

  .trace-stage__titlebtn:hover .trace-stage__label {
    color: var(--primary);
  }

  .trace-stage__titlebtn:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
    border-radius: 4px;
  }

  .trace-stage__caret {
    flex: none;
    width: 14px;
    font-size: 11px;
    line-height: 1;
    color: var(--muted-foreground);
  }

  .trace-stage__label {
    min-width: 0;
    font-weight: 600;
    font-size: 13px;
  }

  /* Count pills after the stage title: neutral = rows returned; --hit = search matches (eye-catch). */
  .trace-stage__pill {
    flex: none;
    display: inline-flex;
    align-items: center;
    min-width: 18px;
    height: 17px;
    padding: 0 6px;
    justify-content: center;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--muted-foreground);
    background: color-mix(in srgb, var(--muted-foreground) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 24%, transparent);
  }

  .trace-stage__pill--hit {
    color: #92400e;
    background: color-mix(in srgb, #facc15 60%, transparent);
    border-color: color-mix(in srgb, #facc15 80%, transparent);
  }

  .trace-stage__meta {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    color: var(--muted-foreground);
    text-align: right;
    word-break: break-word;
  }

  .trace-stage__empty {
    margin: 0;
    padding: 8px 10px;
    font-size: 12px;
    color: var(--muted-foreground);
  }

  .trace-stage__note {
    margin: 0;
    padding: 8px 10px;
    font-size: 11px;
    font-style: italic;
    color: var(--muted-foreground);
    border-bottom: 1px solid color-mix(in srgb, var(--muted-foreground) 12%, transparent);
  }

  .trace-table-wrap {
    overflow-x: auto;
  }

  .trace-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }

  .trace-table th,
  .trace-table td {
    text-align: left;
    padding: 5px 8px;
    border-top: 1px solid color-mix(in srgb, var(--muted-foreground) 12%, transparent);
    vertical-align: top;
  }

  .trace-table th {
    border-top: none;
    font-size: 11px;
    color: var(--muted-foreground);
    font-weight: 600;
    white-space: nowrap;
  }

  /* Sortable headers: click to cycle asc → desc → original. The arrow marks the active column. */
  .trace-table th.sortable {
    cursor: pointer;
    user-select: none;
  }

  .trace-table th.sortable:hover {
    color: var(--foreground);
  }

  .th-arrow {
    margin-left: 3px;
    font-size: 9px;
    color: var(--primary);
  }

  /* Wide rows are hard to track across the table — highlight the whole row on hover. */
  .trace-table tbody tr:hover td {
    background: color-mix(in srgb, var(--primary) 24%, transparent);
  }

  .trace-table .num {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .trace-table .fact {
    min-width: 240px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* Long entity summaries / episode content: clamp to 3 lines until the user expands them. */
  .clamp {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    overflow: hidden;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .clamp--open {
    display: block;
    -webkit-line-clamp: unset;
    line-clamp: unset;
    overflow: visible;
  }

  .clamp-toggle {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    margin-top: 2px;
    padding: 0;
    appearance: none;
    border: none;
    background: transparent;
    font-size: 10px;
    font-weight: 600;
    color: var(--primary);
    cursor: pointer;
  }

  .clamp-toggle:hover {
    text-decoration: underline;
  }

  .trace-table .entity {
    font-weight: 600;
    white-space: nowrap;
  }

  .trace-table .rel,
  .trace-table .temporal,
  .trace-table .uuid {
    white-space: nowrap;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
  }

  .trace-table .from {
    white-space: nowrap;
  }

  .leg-badge {
    display: inline-block;
    padding: 0 5px;
    margin-right: 3px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    line-height: 16px;
    border: 1px solid transparent;
  }

  .leg-badge--kw {
    background: color-mix(in srgb, #3b82f6 18%, transparent);
    border-color: color-mix(in srgb, #3b82f6 45%, transparent);
  }

  .leg-badge--mean {
    background: color-mix(in srgb, #a855f7 18%, transparent);
    border-color: color-mix(in srgb, #a855f7 45%, transparent);
  }

  .leg-badge--hop {
    background: color-mix(in srgb, #f59e0b 20%, transparent);
    border-color: color-mix(in srgb, #f59e0b 50%, transparent);
  }

  /* Validity pill — subtle current (✓ green) vs superseded (✗ red) marker before the fact. */
  .trace-table .vstate {
    text-align: center;
    white-space: nowrap;
  }

  .vpill {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    line-height: 1;
    border: 1px solid transparent;
  }

  .vpill--ok {
    color: #16a34a;
    background: color-mix(in srgb, #16a34a 16%, transparent);
    border-color: color-mix(in srgb, #16a34a 45%, transparent);
  }

  .vpill--bad {
    color: #dc2626;
    background: color-mix(in srgb, #dc2626 16%, transparent);
    border-color: color-mix(in srgb, #dc2626 45%, transparent);
  }

  /* "Strike dropped" toggle — rows that didn't survive to the lane's final result set.
     Orthogonal to the `v` validity pill (this is retrieval drop-out, not temporal validity). */
  .trace-table tr.struck td {
    color: var(--muted-foreground);
    text-decoration: line-through;
    text-decoration-color: color-mix(in srgb, var(--muted-foreground) 55%, transparent);
  }

  /* Keep the validity pill legible even on a struck row. */
  .trace-table tr.struck .vpill {
    text-decoration: none;
  }
</style>
