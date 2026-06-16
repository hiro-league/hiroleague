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
    IngestEntityType,
    IngestTraceEdge,
    IngestTraceMessage,
    IngestTraceNode,
    IngestTraceRecord,
    IngestTraceStage
  } from '$lib/api/graph-runs';
  import { shortGraphId } from './graph-runs-pure';

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
  let collapsed = $state<Set<number>>(new Set());
  let promptOpen = $state<Set<number>>(new Set());
  let jsonOpen = $state<Set<number>>(new Set());

  // The config/stats line (episode · chunk · tokens …) is collapsed by default behind the
  // header gear so the header stays compact — mirrors the recall (retrieval) trace dialog.
  let settingsOpen = $state(false);

  // Reset transient view state on a new trace, but PRESERVE the active tab so arrow-nav between
  // episodes keeps you on the same tab (the tabKeys effect below re-validates / initialises it).
  $effect(() => {
    void trace;
    collapsed = new Set();
    promptOpen = new Set();
    jsonOpen = new Set();
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

  function toggleStage(index: number): void {
    const next = new Set(collapsed);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    collapsed = next;
  }

  function togglePrompt(index: number): void {
    const next = new Set(promptOpen);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    promptOpen = next;
  }

  function toggleJson(index: number): void {
    const next = new Set(jsonOpen);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    jsonOpen = next;
  }

  const isCollapsed = (index: number): boolean => collapsed.has(index);
  const isPromptOpen = (index: number): boolean => promptOpen.has(index);
  const isJsonOpen = (index: number): boolean => jsonOpen.has(index);

  // ── Stage grouping ──────────────────────────────────────────────────────────────────────
  // add_episode runs its stages in a fixed pipeline order; group the flat capture list by
  // stage node and render groups in that order so it reads as a pipeline. Some nodes fire
  // multiple times (e.g. `resolve_facts` once per edge), so a group can hold several calls.
  const STAGE_ORDER = [
    'extract_entities',
    'resolve_entities',
    'dedup_entities_auto',
    'extract_facts',
    'date_facts',
    'resolve_facts',
    'summarize_entities',
    'extract_attributes',
    'completion',
    'other'
  ];

  function stageRank(node: string): number {
    const i = STAGE_ORDER.indexOf(node);
    return i === -1 ? STAGE_ORDER.length : i;
  }

  type StageRef = { stage: IngestTraceStage; idx: number };
  type StageGroup = { node: string; label: string; stages: StageRef[] };

  const groups = $derived.by<StageGroup[]>(() => {
    if (!trace) return [];
    const byNode = new Map<string, StageRef[]>();
    trace.stages.forEach((stage, idx) => {
      const arr = byNode.get(stage.node) ?? [];
      arr.push({ stage, idx });
      byNode.set(stage.node, arr);
    });
    return [...byNode.entries()]
      .map(([node, stages]) => ({ node, label: stages[0]?.stage.label ?? node, stages }))
      .sort((a, b) => stageRank(a.node) - stageRank(b.node));
  });

  // ── Pipeline phases (sub-tabs) ────────────────────────────────────────────────────────────
  // The flat stage list spans three logical phases of add_episode. Group the node-groups into
  // those phases so the Pipeline tab reads as: entities → attributes → facts (+ a catch-all).
  // Every possible stage node maps to a phase (not just the ones a given episode happened to
  // emit) so the sub-tabs are stable regardless of which stages fired.
  const PHASE_ORDER = ['entities', 'attributes', 'facts', 'other'] as const;
  const PHASE_TITLE: Record<string, string> = {
    entities: 'Entities',
    attributes: 'Attributes',
    facts: 'Facts',
    other: 'Other'
  };
  const PHASE_HINT: Record<string, string> = {
    entities: 'extract → resolve / dedupe the people, places & things',
    attributes: 'summaries & typed attributes attached to each entity',
    facts: 'extract → date → resolve / invalidate the relationships',
    other: 'completions & uncategorized stages'
  };
  const STAGE_PHASE: Record<string, string> = {
    extract_entities: 'entities',
    resolve_entities: 'entities',
    dedup_entities_auto: 'entities',
    summarize_entities: 'attributes',
    extract_attributes: 'attributes',
    extract_facts: 'facts',
    date_facts: 'facts',
    resolve_facts: 'facts',
    completion: 'other',
    other: 'other'
  };

  type Phase = { phase: string; title: string; hint: string; groups: StageGroup[]; idxs: number[] };

  const phases = $derived.by<Phase[]>(() => {
    const byPhase = new Map<string, StageGroup[]>();
    for (const group of groups) {
      const phase = STAGE_PHASE[group.node] ?? 'other';
      const arr = byPhase.get(phase) ?? [];
      arr.push(group);
      byPhase.set(phase, arr);
    }
    return PHASE_ORDER.filter((p) => byPhase.has(p)).map((p) => {
      const grps = byPhase.get(p) ?? [];
      return {
        phase: p,
        title: PHASE_TITLE[p] ?? p,
        hint: PHASE_HINT[p] ?? '',
        groups: grps,
        idxs: grps.flatMap((g) => g.stages.map((s) => s.idx))
      };
    });
  });

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

  /** Expand / collapse all stage cards in the ACTIVE phase (mirrors the retrieval dialog). */
  function expandActive(): void {
    if (!activePhaseObj) return;
    const next = new Set(collapsed);
    for (const i of activePhaseObj.idxs) next.delete(i);
    collapsed = next;
  }

  function collapseActive(): void {
    if (!activePhaseObj) return;
    const next = new Set(collapsed);
    for (const i of activePhaseObj.idxs) next.add(i);
    collapsed = next;
  }

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

  // ── Formatting ────────────────────────────────────────────────────────────────────────────
  function messages(stage: IngestTraceStage): IngestTraceMessage[] {
    return Array.isArray(stage.input) ? (stage.input as IngestTraceMessage[]) : [];
  }

  function prettyOutput(stage: IngestTraceStage): string {
    try {
      return JSON.stringify(stage.output, null, 2);
    } catch {
      return String(stage.output ?? '');
    }
  }

  // ── Structured → table projection ─────────────────────────────────────────────────────────
  // Each stage's structured output (and a non-LLM stage's input) is rendered as a table by
  // default — far more readable than raw JSON — with the JSON kept one click away as a fallback.
  // The shape is detected, not hardcoded per stage, so it stays correct as graphiti's models
  // evolve: a list (or a single list-valued field) → a rows table (one row per item, columns =
  // the union of item keys); anything else → a key/value table. Scalars render inline.
  type ViewTable =
    | { kind: 'rows'; columns: string[]; rows: Record<string, string>[] }
    | { kind: 'kv'; entries: { key: string; value: string }[] }
    | { kind: 'scalar'; value: string }
    | { kind: 'empty' };

  function isPlainObject(v: unknown): v is Record<string, unknown> {
    return typeof v === 'object' && v !== null && !Array.isArray(v);
  }

  /** A single value as a compact cell — scalars verbatim, nested structures as compact JSON. */
  function cell(v: unknown): string {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'string') return v;
    if (typeof v === 'number' || typeof v === 'boolean') return String(v);
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }

  function prettyKey(key: string): string {
    return key.replace(/_/g, ' ');
  }

  function rowsTable(items: unknown[]): ViewTable {
    if (items.length === 0) return { kind: 'empty' };
    // Scalar list (e.g. `duplicate_facts: [int]`) → a single-column "value" table.
    if (!items.some(isPlainObject)) {
      return { kind: 'rows', columns: ['value'], rows: items.map((it) => ({ value: cell(it) })) };
    }
    const columns: string[] = [];
    for (const it of items) {
      if (isPlainObject(it)) for (const k of Object.keys(it)) if (!columns.includes(k)) columns.push(k);
    }
    const rows = items.map((it) => {
      const row: Record<string, string> = {};
      for (const c of columns) row[c] = isPlainObject(it) ? cell(it[c]) : '';
      return row;
    });
    return { kind: 'rows', columns, rows };
  }

  function toView(value: unknown): ViewTable {
    if (value === null || value === undefined) return { kind: 'empty' };
    if (Array.isArray(value)) return rowsTable(value);
    if (isPlainObject(value)) {
      const keys = Object.keys(value);
      if (keys.length === 0) return { kind: 'empty' };
      // A dict whose ONLY field is a list of objects (the common graphiti shape, e.g.
      // `{extracted_entities: [...]}`) → render that list as the table directly.
      const arrayKeys = keys.filter((k) => Array.isArray(value[k]));
      if (arrayKeys.length === 1 && (value[arrayKeys[0]] as unknown[]).some(isPlainObject)) {
        return rowsTable(value[arrayKeys[0]] as unknown[]);
      }
      return { kind: 'kv', entries: keys.map((k) => ({ key: k, value: cell(value[k]) })) };
    }
    return { kind: 'scalar', value: cell(value) };
  }

  const outputView = (stage: IngestTraceStage): ViewTable => toView(stage.output);

  /** Non-LLM stages (dedup) carry a dict input rather than prompt messages — show it as a table. */
  function inputView(stage: IngestTraceStage): ViewTable {
    if (messages(stage).length) return { kind: 'empty' };
    return toView(stage.input);
  }

  // ── Human-readable dates ──────────────────────────────────────────────────────────────────
  // graphiti stores microsecond ISO timestamps (`2213-11-30T08:00:00.000000Z`) and the eval
  // corpus uses far-future years, so we format by regex (not `Date`, which chokes on 6-digit
  // fractional seconds) into `30 Nov 2213, 08:00 UTC`. Raw ISO stays in the tooltip + Raw JSON.
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/;

  const isISO = (v: unknown): v is string => typeof v === 'string' && ISO_RE.test(v);

  function fmtDate(iso: string | null | undefined, withTime = true): string {
    if (!iso) return '';
    const m = ISO_RE.exec(String(iso));
    if (!m) return String(iso);
    const [, y, mo, d, hh, mm] = m;
    const month = MONTHS[Number(mo) - 1] ?? mo;
    let out = `${Number(d)} ${month} ${y}`;
    if (withTime && hh !== undefined) out += `, ${hh}:${mm} UTC`;
    return out;
  }

  // ── Resolve / invalidate facts (option A) ───────────────────────────────────────────────────
  // The EdgeDuplicate output is bare idx arrays (`{duplicate_facts, contradicted_facts}`) that
  // only resolve against the prompt's two fact lists. We recover NEW FACT + the candidate facts
  // (idx → text) from the captured prompt and join them to the indices into a verdict table.
  // graphiti renders the lists as Python `str()` of dicts — single-quoted keys, per-string quote
  // style — so the item regex accepts either quote style. Any parse miss → caller falls back to
  // the generic table (+ Raw JSON is always available), so a prompt drift degrades, never breaks.
  type FactCandidate = { idx: number; origin: string; fact: string; decision: 'duplicate' | 'contradicted' | 'none' };
  type ResolveFactsView = { newFact: string; candidates: FactCandidate[]; dupCount: number; contraCount: number };

  function tagBlock(text: string, tag: string): string {
    const re = new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`);
    return re.exec(text)?.[1]?.trim() ?? '';
  }

  function parseFactItems(block: string): { idx: number; fact: string }[] {
    const out: { idx: number; fact: string }[] = [];
    const re = /'idx':\s*(\d+),\s*'fact':\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(block)) !== null) {
      const raw = m[2] ?? m[3] ?? '';
      const fact = raw.replace(/\\(["'\\])/g, '$1');
      out.push({ idx: Number(m[1]), fact });
    }
    return out;
  }

  function resolveFactsView(stage: IngestTraceStage): ResolveFactsView | null {
    const text = messages(stage)
      .map((m) => m.content ?? '')
      .join('\n');
    if (!text.includes('<NEW FACT>')) return null;
    const newFact = tagBlock(text, 'NEW FACT');
    const existing = parseFactItems(tagBlock(text, 'EXISTING FACTS')).map((it) => ({
      ...it,
      origin: 'Existing fact'
    }));
    const invalidation = parseFactItems(tagBlock(text, 'FACT INVALIDATION CANDIDATES')).map((it) => ({
      ...it,
      origin: 'Invalidation candidate'
    }));
    const out = (stage.output ?? {}) as { duplicate_facts?: number[]; contradicted_facts?: number[] };
    const dups = new Set(out.duplicate_facts ?? []);
    const contras = new Set(out.contradicted_facts ?? []);
    const candidates: FactCandidate[] = [...existing, ...invalidation]
      .sort((a, b) => a.idx - b.idx)
      .map(({ idx, fact, origin }) => ({
        idx,
        fact,
        origin,
        decision: contras.has(idx) ? 'contradicted' : dups.has(idx) ? 'duplicate' : 'none'
      }));
    if (!newFact && candidates.length === 0) return null;
    return {
      newFact,
      candidates,
      dupCount: out.duplicate_facts?.length ?? 0,
      contraCount: out.contradicted_facts?.length ?? 0
    };
  }

  // ── Dedupe entities (non-LLM auto-merges) ───────────────────────────────────────────────────
  // Each stage in the group is one auto-merge (`input` = the freshly-extracted entity; `output`
  // = `{merged_into, decision}`). Collapse the whole group into one "merge map" table so it reads
  // as "what collapsed into what" instead of N key/value blobs.
  type Brief = { name?: string; entity_type?: string; summary?: string; uuid?: string };
  type Merge = { from: Brief; into: Brief; idx: number };

  function dedupMerges(group: StageGroup): Merge[] {
    return group.stages.map(({ stage, idx }) => ({
      idx,
      from: (stage.input ?? {}) as Brief,
      into: ((stage.output as { merged_into?: Brief })?.merged_into ?? {}) as Brief
    }));
  }

  const briefName = (b: Brief): string => b.name || '—';
  const briefType = (b: Brief): string => b.entity_type || '';

  /** Raw JSON for a whole dedup group (the merge list) — its collapsible fallback. */
  function dedupJson(group: StageGroup): string {
    const payload = group.stages.map(({ stage }) => ({ input: stage.input, output: stage.output }));
    try {
      return JSON.stringify(payload, null, 2);
    } catch {
      return String(payload);
    }
  }

  // ── Extracted entities (resolve type ids) ───────────────────────────────────────────────────
  // graphiti's `extract_entities` output is `{extracted_entities: [{name, entity_type_id, …}]}`
  // where `entity_type_id` is a bare integer index into the ontology. The trace carries the
  // active ontology legend (id → name + description), so we render the ACTUAL type name and its
  // description instead of the opaque number. Missing legend (older sidecar) → `#id` fallback.
  const entityTypeById = $derived.by<Map<number, IngestEntityType>>(() => {
    const m = new Map<number, IngestEntityType>();
    for (const t of trace?.entity_types ?? []) m.set(t.id, t);
    return m;
  });

  type ExtractedEntityRow = { name: string; typeName: string; description: string };

  function extractedEntities(stage: IngestTraceStage): ExtractedEntityRow[] | null {
    const out = stage.output as { extracted_entities?: unknown } | null;
    const list = out && Array.isArray(out.extracted_entities) ? out.extracted_entities : null;
    if (!list) return null;
    return list.map((raw) => {
      const e = (raw ?? {}) as { name?: string; entity_type_id?: number };
      const t = e.entity_type_id != null ? entityTypeById.get(e.entity_type_id) : undefined;
      return {
        name: e.name || '—',
        typeName: t?.name ?? (e.entity_type_id != null ? `#${e.entity_type_id}` : '—'),
        description: t?.description ?? ''
      };
    });
  }

  function stageMeta(stage: IngestTraceStage): string {
    const parts: string[] = [];
    if (stage.operation) parts.push(stage.operation);
    if (stage.model_id) parts.push(stage.model_id);
    if (stage.input_tokens || stage.output_tokens) {
      parts.push(`${stage.input_tokens}i/${stage.output_tokens}o`);
    }
    if (Number.isFinite(stage.elapsed_ms) && stage.elapsed_ms > 0) {
      parts.push(`${stage.elapsed_ms.toFixed(1)}ms`);
    }
    return parts.join(' · ');
  }

  // Count pill for a stage header (mirrors the recall dialog): how many items the stage
  // produced, when that's a meaningful number. List-shaped outputs (extracted entities, table
  // rows, resolved-fact candidates) → their length; key/value / scalar outputs → null (no pill).
  function stageCount(stage: IngestTraceStage, node: string): number | null {
    if (node === 'extract_entities') return extractedEntities(stage)?.length ?? null;
    if (node === 'resolve_facts') return resolveFactsView(stage)?.candidates.length ?? null;
    const ov = outputView(stage);
    return ov.kind === 'rows' ? ov.rows.length : null;
  }

  const isCurrent = (e: IngestTraceEdge): boolean => !(e.invalid_at || e.expired_at);

  function temporalTitle(e: IngestTraceEdge): string {
    const lines: string[] = [];
    if (e.valid_at) lines.push(`became true: ${e.valid_at}`);
    if (e.invalid_at) lines.push(`stopped being true: ${e.invalid_at}`);
    if (e.expired_at) lines.push(`system-expired: ${e.expired_at}`);
    return lines.length ? lines.join('\n') : 'no temporal bounds';
  }

  const nodes = $derived<IngestTraceNode[]>(trace?.persisted_nodes ?? []);
  const edges = $derived<IngestTraceEdge[]>(trace?.persisted_edges ?? []);
</script>

<!-- Renders a projected stage view (structured output / dedup input) as a readable table.
     `rows` = one row per item (columns = union of keys); `kv` = a two-column key/value table;
     `scalar` = a lone value. Declared top-level so it's a local snippet, not a Dialog prop. -->
{#snippet viewTable(view: ViewTable)}
  {#if view.kind === 'rows'}
    <div class="trace-table-wrap">
      <table class="trace-table out-table">
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
      </table>
    </div>
  {:else if view.kind === 'kv'}
    <div class="trace-table-wrap">
      <table class="trace-table out-table">
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
      </table>
    </div>
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
      <div class="trace-table-wrap">
        <table class="trace-table out-table">
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
        </table>
      </div>
    {:else}
      <p class="trace-empty">No candidate facts — added directly as new.</p>
    {/if}
  </div>
{/snippet}

<!-- Extract-entities output: each entity with its RESOLVED ontology type (name + description)
     rather than the raw numeric entity_type_id graphiti emits. Top-level local snippet. -->
{#snippet entitiesTable(rows: ExtractedEntityRow[])}
  <div class="trace-table-wrap">
    <table class="trace-table out-table">
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
    </table>
  </div>
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
        <div class="trace-tabs trace-subtabs" role="tablist" aria-label="Ingest trace views">
          {#each phases as phase (phase.phase)}
            <button
              type="button"
              role="tab"
              class="trace-tab"
              class:trace-tab--active={activeTab === phase.phase}
              aria-selected={activeTab === phase.phase}
              onclick={() => (activeTab = phase.phase)}
            >
              {phase.title}
              <span class="trace-tab__count">{phase.idxs.length}</span>
            </button>
          {/each}
          <button
            type="button"
            role="tab"
            class="trace-tab"
            class:trace-tab--active={activeTab === RESULT_TAB}
            aria-selected={activeTab === RESULT_TAB}
            onclick={() => (activeTab = RESULT_TAB)}
          >
            Result
            <span class="trace-tab__count">{nodes.length + edges.length}</span>
          </button>
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
                  <div class="stage-card" data-source="dedup">
                    <header class="stage-card__head">
                      <button
                        type="button"
                        class="stage-card__titlebtn"
                        aria-expanded={!isCollapsed(gidx)}
                        title={isCollapsed(gidx) ? 'Expand' : 'Collapse'}
                        onclick={() => toggleStage(gidx)}
                      >
                        <span class="stage-card__caret">{isCollapsed(gidx) ? '\u25B8' : '\u25BE'}</span>
                        <span class="stage-card__label">
                          Merge map<span class="stage-card__badge">dedup</span>
                        </span>
                        <span class="stage-card__pill" title="Auto-merges">{merges.length}</span>
                      </button>
                      <span class="stage-card__meta">auto-merges · deterministic (no LLM)</span>
                    </header>
                    {#if !isCollapsed(gidx)}
                      <div class="stage-card__body">
                        <p class="phase-hint">
                          Exact-name / fuzzy MinHash collapses — each freshly-extracted entity reused an
                          existing node without an LLM call.
                        </p>
                        <div class="trace-table-wrap">
                          <table class="trace-table out-table">
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
                          </table>
                        </div>
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
                      </div>
                    {/if}
                  </div>
                {:else}
                  {#each group.stages as { stage, idx } (idx)}
                    {@const ov = outputView(stage)}
                    {@const iv = inputView(stage)}
                    {@const rfv = group.node === 'resolve_facts' ? resolveFactsView(stage) : null}
                    {@const ee = group.node === 'extract_entities' ? extractedEntities(stage) : null}
                    {@const count = stageCount(stage, group.node)}
                    <div class="stage-card" data-source={stage.source}>
                      <header class="stage-card__head">
                        <button
                          type="button"
                          class="stage-card__titlebtn"
                          aria-expanded={!isCollapsed(idx)}
                          title={isCollapsed(idx) ? 'Expand stage' : 'Collapse stage'}
                          onclick={() => toggleStage(idx)}
                        >
                          <span class="stage-card__caret">{isCollapsed(idx) ? '\u25B8' : '\u25BE'}</span>
                          <span class="stage-card__label">
                            {stage.label}
                            {#if stage.source !== 'llm'}<span class="stage-card__badge">{stage.source}</span>{/if}
                          </span>
                          {#if count !== null}<span class="stage-card__pill" title="Items produced by this stage">{count}</span>{/if}
                        </button>
                        <span class="stage-card__meta">{stageMeta(stage)}</span>
                      </header>

                      {#if !isCollapsed(idx)}
                        <div class="stage-card__body">
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
                        </div>
                      {/if}
                    </div>
                  {/each}
                {/if}
              </section>
            {/each}
        {:else if activeTab === RESULT_TAB}
          <!-- Result tab: what actually landed in the graph (AddEpisodeResults). -->
          <section class="result-section">
            <h3 class="stage-group__title">Entities ({nodes.length})</h3>
            {#if nodes.length}
              <div class="trace-table-wrap">
                <table class="trace-table">
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
                </table>
              </div>
            {:else}
              <p class="trace-empty">No entities persisted.</p>
            {/if}

            <h3 class="stage-group__title">Facts ({edges.length})</h3>
            {#if edges.length}
              <div class="trace-table-wrap">
                <table class="trace-table">
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
                          <span
                            class="vpill"
                            class:vpill--ok={isCurrent(e)}
                            class:vpill--bad={!isCurrent(e)}
                            title={temporalTitle(e)}
                          >
                            {isCurrent(e) ? '\u2713' : '\u2717'}
                          </span>
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
                </table>
              </div>
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

  .trace-tabs {
    display: flex;
    gap: 4px;
    flex: none;
  }

  /* Pipeline phase sub-tabs sit in the scroll body (not the header) with a divider under. */
  .trace-subtabs {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--background);
    border-bottom: 1px solid color-mix(in srgb, var(--muted-foreground) 18%, transparent);
    padding-bottom: 2px;
  }

  .trace-tab__count {
    margin-left: 5px;
    font-size: 10px;
    font-weight: 600;
    color: var(--muted-foreground);
    font-variant-numeric: tabular-nums;
  }

  .phase-hint {
    margin: 0;
    font-size: 11px;
    color: var(--muted-foreground);
  }

  .trace-tab {
    appearance: none;
    border: none;
    background: transparent;
    padding: 6px 12px;
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

  .trace-tab:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
    border-radius: 4px;
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

  .stage-card {
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 18%, transparent);
    border-radius: 8px;
    overflow: hidden;
  }

  /* Non-LLM dedup stages get a distinct accent so they read as "observed, not model-driven". */
  .stage-card[data-source='dedup'] {
    border-color: color-mix(in srgb, #f59e0b 45%, transparent);
  }

  .stage-card__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 10px;
    background: color-mix(in srgb, var(--muted-foreground) 8%, transparent);
  }

  /* Whole title row is the toggle — caret + label + count pill, all clickable (mirrors recall). */
  .stage-card__titlebtn {
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

  .stage-card__titlebtn:hover .stage-card__label {
    color: var(--primary);
  }

  .stage-card__titlebtn:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
    border-radius: 4px;
  }

  .stage-card__caret {
    flex: none;
    width: 14px;
    font-size: 11px;
    line-height: 1;
    color: var(--muted-foreground);
  }

  .stage-card__label {
    min-width: 0;
    font-weight: 600;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  /* Count pill after the stage title: how many items the stage produced (mirrors recall). */
  .stage-card__pill {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 17px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--muted-foreground);
    background: color-mix(in srgb, var(--muted-foreground) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 24%, transparent);
  }

  .stage-card__badge {
    font-size: 10px;
    font-weight: 600;
    padding: 0 5px;
    border-radius: 3px;
    background: color-mix(in srgb, #f59e0b 20%, transparent);
    border: 1px solid color-mix(in srgb, #f59e0b 50%, transparent);
  }

  .stage-card__meta {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    color: var(--muted-foreground);
    text-align: right;
    word-break: break-word;
  }

  .stage-card__body {
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

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

  /* Structured stage output rendered as a table. Cells wrap (facts/summaries can be long); the
     leading # / key column stays compact. */
  .out-table .cell {
    white-space: pre-wrap;
    word-break: break-word;
    max-width: 520px;
  }

  .out-table .kv-key {
    white-space: nowrap;
    font-weight: 600;
    color: var(--muted-foreground);
    vertical-align: top;
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

  /* Dedup merge map: dim the entity type + center the → arrow column. */
  .type-dim {
    color: var(--muted-foreground);
    font-weight: 400;
  }

  .out-table .arrow-col {
    text-align: center;
    color: var(--muted-foreground);
    width: 1.5rem;
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
</style>
