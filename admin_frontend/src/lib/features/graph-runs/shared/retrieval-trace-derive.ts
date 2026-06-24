/**
 * Side-effect-free derivation logic for the retrieval (Graphiti fact-search) trace dialog.
 * Extracted from `GraphRunsRetrievalTraceDialog.svelte` so the lane model, search-highlight
 * matching, provenance and per-column sort logic stay unit-testable. The dialog keeps the
 * Svelte glue (state, `$derived`, markup) and injects its `search` text / `sortByStage`
 * overrides into the helpers that need them, so markup call sites stay thin.
 */
import type {
  RetrievalTraceItem,
  RetrievalTraceStage
} from '$lib/api/graph-runs';
import { matchesQuery } from '$lib/search/match';
import { isCurrent } from './trace-format';

// ── Lane model ────────────────────────────────────────────────────────────────────────
// The pipeline runs one independent sub-pipeline per entity type. We group the flat stage
// list into lanes so a human reads it as: candidates (parallel legs) → fuse/rank → (temporal)
// → kept, once per type. The shared `embed` stage (lane `query`) is shown as a thin header.
export const LANE_ORDER = ['edge', 'node', 'episode'] as const;
export const LANE_TITLE: Record<string, string> = {
  edge: 'Facts',
  node: 'Entities',
  episode: 'Episodes'
};
export const LANE_HINT: Record<string, string> = {
  edge: 'relationship triples (subject → relation → object)',
  node: 'entity attribute memories (name · type · summary)',
  episode: 'raw recalled turns / chunks (BM25)'
};

export type StageRef = { stage: RetrievalTraceStage; idx: number };
export type Leg = { tag: string; cls: string; uuids: Set<string> };
export type FlowSeg = {
  label: string;
  count: number;
  emphasis: 'leg' | 'rank' | 'final';
  /** Index in `trace.stages` so a pill can scroll to (and expand) its stage. */
  idx: number;
};
export type Lane = {
  lane: string;
  title: string;
  hint: string;
  stages: StageRef[];
  legs: Leg[];
  flow: FlowSeg[];
  /** uuids of the lane's terminal stage (temporal for edges, rank otherwise) = the result. */
  finalUuids: Set<string>;
};

export function legTag(stage: RetrievalTraceStage): { tag: string; cls: string } {
  if (stage.kind === 'hop') return { tag: 'hop', cls: 'hop' };
  const method = String(stage.meta?.method ?? '');
  if (method === 'bm25') return { tag: 'BM25', cls: 'kw' };
  if (method === 'cosine_similarity') return { tag: 'cosine', cls: 'mean' };
  return { tag: stage.label, cls: 'kw' };
}

export function rerankerLabel(stage: RetrievalTraceStage): string {
  const r = stage.meta?.reranker;
  if (typeof r === 'string' && r) return r;
  const parts = stage.label.split('·');
  return (parts[1] ?? stage.label).trim();
}

export function findEmbedStage(stages: RetrievalTraceStage[]): RetrievalTraceStage | null {
  return stages.find((s) => s.kind === 'embed' || s.lane === 'query') ?? null;
}

export function buildLanes(stages: RetrievalTraceStage[]): Lane[] {
  const out: Lane[] = [];
  for (const laneKey of LANE_ORDER) {
    const laneStages: StageRef[] = [];
    stages.forEach((stage, idx) => {
      if (stage.lane === laneKey && stage.kind !== 'embed') laneStages.push({ stage, idx });
    });
    if (laneStages.length === 0) continue;

    // Candidate + hop stages double as the provenance legs for the rank stage.
    const legs: Leg[] = laneStages
      .filter(({ stage }) => stage.kind === 'candidate' || stage.kind === 'hop')
      .map(({ stage }) => {
        const { tag, cls } = legTag(stage);
        return { tag, cls, uuids: new Set(stage.items.map((it) => it.uuid)) };
      });

    // Funnel: each leg's yield → rank → (temporal kept). Counts use item arrays (robust).
    // Each segment carries its stage idx so the pill can jump to that stage's table.
    const flow: FlowSeg[] = [];
    for (const { stage, idx } of laneStages) {
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
    const finalStage = laneStages[laneStages.length - 1]?.stage;
    const finalUuids = new Set<string>((finalStage?.items ?? []).map((it) => it.uuid));

    out.push({
      lane: laneKey,
      title: LANE_TITLE[laneKey] ?? laneKey,
      hint: LANE_HINT[laneKey] ?? '',
      stages: laneStages,
      legs,
      flow,
      finalUuids
    });
  }
  return out;
}

// ── Text-search highlight ───────────────────────────────────────────────────────────────
/** The searchable text of an item, by lane (the same columns the table renders). */
export function itemText(item: RetrievalTraceItem, lane: string): string {
  if (lane === 'edge') return [item.fact, item.name, item.uuid].filter(Boolean).join(' ');
  if (lane === 'node')
    return [item.name, item.entity_type, item.summary, item.uuid].filter(Boolean).join(' ');
  return [item.content, item.source, item.uuid].filter(Boolean).join(' ');
}

/** Per-lane count of DISTINCT matching items (by uuid) — shown next to each tab while searching. */
export function laneMatchCounts(lanes: Lane[], query: string): Map<string, number> {
  const m = new Map<string, number>();
  if (!query.trim()) return m;
  for (const lane of lanes) {
    const hits = new Set<string>();
    for (const { stage } of lane.stages) {
      for (const item of stage.items) {
        if (matchesQuery(itemText(item, lane.lane), query)) hits.add(item.uuid);
      }
    }
    m.set(lane.lane, hits.size);
  }
  return m;
}

/** How many of a stage's rows match the current search (drives the highlighted count pill). */
export function stageMatchCount(stage: RetrievalTraceStage, laneKey: string, query: string): number {
  if (!query.trim()) return 0;
  let n = 0;
  for (const item of stage.items) {
    if (matchesQuery(itemText(item, laneKey), query)) n++;
  }
  return n;
}

/** Stage header label — the temporal lens spells out that rows are ordered by date, not score. */
export function stageHeadLabel(stage: RetrievalTraceStage): string {
  return stage.kind === 'temporal' ? 'Temporal lens (ordered by date)' : stage.label;
}

/** For a ranked item, which candidate/hop legs contributed it (drives fusion badges). */
export function provenance(item: RetrievalTraceItem, lane: Lane): Leg[] {
  return lane.legs.filter((leg) => leg.uuids.has(item.uuid));
}

export function isRankStage(stage: RetrievalTraceStage): boolean {
  return stage.kind === 'rank';
}

export const hasItems = (stage: RetrievalTraceStage): boolean =>
  Array.isArray(stage.items) && stage.items.length > 0;

/** The caller-anchored BFS candidate leg (origins passed into the search, not derived). */
export const isExplicitBfsLeg = (stage: RetrievalTraceStage): boolean =>
  stage.kind === 'candidate' && stage.meta?.method === 'bfs';

/** Compact metadata line per stage (counts / limits / timings), order-stable. */
export function stageMetaSummary(stage: RetrievalTraceStage): string {
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

// ── Per-column sort ─────────────────────────────────────────────────────────────────────
// Click a column header to sort a stage's rows: asc → desc → original (tri-state). The
// temporal lane arrives pre-sorted by valid_at from the backend; the override lets the user
// re-sort that (or any other table) per column.
export type SortDir = 1 | -1;
export type SortState = { key: string; dir: SortDir };

/** Comparable value for a column key. Strings lowercased; missing values sort to an extreme. */
export function sortValue(item: RetrievalTraceItem, key: string): string | number {
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
export function sortItems(
  items: RetrievalTraceItem[],
  sort: SortState | undefined
): RetrievalTraceItem[] {
  if (!sort) return items;
  const { key, dir } = sort;
  return [...items].sort((a, b) => {
    const av = sortValue(a, key);
    const bv = sortValue(b, key);
    if (av < bv) return -dir;
    if (av > bv) return dir;
    return 0;
  });
}

// The effective sort shown in the headers: the user's explicit per-column override, else the
// stage's implicit order. The temporal lens arrives pre-sorted by valid_at (ascending) from the
// backend, so we surface that as a Valid-column arrow even with no override — otherwise the
// header looks unsorted when it isn't. (Matches `sortItems`, which leaves that order as-is.)
export function resolveEffectiveSort(
  override: SortState | undefined,
  stageKind: string | undefined
): SortState | null {
  if (override) return override;
  if (stageKind === 'temporal') return { key: 'valid', dir: 1 };
  return null;
}

/** Header arrow for the active sort column: ▲ asc, ▼ desc, '' when this column isn't sorted. */
export function sortArrowGlyph(sort: SortState | null, key: string): string {
  if (!sort || sort.key !== key) return '';
  return sort.dir === 1 ? '▲' : '▼';
}

export function ariaSortValue(
  sort: SortState | null,
  key: string
): 'ascending' | 'descending' | 'none' {
  if (!sort || sort.key !== key) return 'none';
  return sort.dir === 1 ? 'ascending' : 'descending';
}
