/**
 * Side-effect-free derivation / projection logic for the ingest (add_episode) trace dialog.
 * Extracted from `GraphRunsIngestTraceDialog.svelte` so the stage grouping, phase mapping,
 * structured→table projection, fact-verdict prompt parsing, dedup merge-map projection and
 * entity-type resolution stay unit-testable. The dialog keeps only the Svelte glue (state,
 * `$derived`, markup) and injects component state (`entityTypeById`) into the few helpers
 * that need it.
 */
import type {
  IngestEntityType,
  IngestTraceMessage,
  IngestTraceStage
} from '$lib/api/graph-runs';
import { cell, isPlainObject } from './trace-format';

// ── Stage grouping ──────────────────────────────────────────────────────────────────────
// add_episode runs its stages in a fixed pipeline order; group the flat capture list by
// stage node and render groups in that order so it reads as a pipeline. Some nodes fire
// multiple times (e.g. `resolve_facts` once per edge), so a group can hold several calls.
export const STAGE_ORDER = [
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

export function stageRank(node: string): number {
  const i = STAGE_ORDER.indexOf(node);
  return i === -1 ? STAGE_ORDER.length : i;
}

export type StageRef = { stage: IngestTraceStage; idx: number };
export type StageGroup = { node: string; label: string; stages: StageRef[] };

export function groupStages(stages: IngestTraceStage[]): StageGroup[] {
  const byNode = new Map<string, StageRef[]>();
  stages.forEach((stage, idx) => {
    const arr = byNode.get(stage.node) ?? [];
    arr.push({ stage, idx });
    byNode.set(stage.node, arr);
  });
  return [...byNode.entries()]
    .map(([node, grouped]) => ({ node, label: grouped[0]?.stage.label ?? node, stages: grouped }))
    .sort((a, b) => stageRank(a.node) - stageRank(b.node));
}

// ── Pipeline phases (sub-tabs) ────────────────────────────────────────────────────────────
// The flat stage list spans three logical phases of add_episode. Group the node-groups into
// those phases so the Pipeline tab reads as: entities → attributes → facts (+ a catch-all).
// Every possible stage node maps to a phase (not just the ones a given episode happened to
// emit) so the sub-tabs are stable regardless of which stages fired.
export const PHASE_ORDER = ['entities', 'attributes', 'facts', 'other'] as const;
export const PHASE_TITLE: Record<string, string> = {
  entities: 'Entities',
  attributes: 'Attributes',
  facts: 'Facts',
  other: 'Other'
};
export const PHASE_HINT: Record<string, string> = {
  entities: 'extract → resolve / dedupe the people, places & things',
  attributes: 'summaries & typed attributes attached to each entity',
  facts: 'extract → date → resolve / invalidate the relationships',
  other: 'completions & uncategorized stages'
};
export const STAGE_PHASE: Record<string, string> = {
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

export type Phase = {
  phase: string;
  title: string;
  hint: string;
  groups: StageGroup[];
  idxs: number[];
};

export function buildPhases(groups: StageGroup[]): Phase[] {
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
}

// ── Structured → table projection ─────────────────────────────────────────────────────────
// Each stage's structured output (and a non-LLM stage's input) is rendered as a table by
// default — far more readable than raw JSON — with the JSON kept one click away as a fallback.
// The shape is detected, not hardcoded per stage, so it stays correct as graphiti's models
// evolve: a list (or a single list-valued field) → a rows table (one row per item, columns =
// the union of item keys); anything else → a key/value table. Scalars render inline.
export type ViewTable =
  | { kind: 'rows'; columns: string[]; rows: Record<string, string>[] }
  | { kind: 'kv'; entries: { key: string; value: string }[] }
  | { kind: 'scalar'; value: string }
  | { kind: 'empty' };

export function rowsTable(items: unknown[]): ViewTable {
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

export function toView(value: unknown): ViewTable {
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

export function messages(stage: IngestTraceStage): IngestTraceMessage[] {
  return Array.isArray(stage.input) ? (stage.input as IngestTraceMessage[]) : [];
}

export function prettyOutput(stage: IngestTraceStage): string {
  try {
    return JSON.stringify(stage.output, null, 2);
  } catch {
    return String(stage.output ?? '');
  }
}

export const outputView = (stage: IngestTraceStage): ViewTable => toView(stage.output);

/** Non-LLM stages (dedup) carry a dict input rather than prompt messages — show it as a table. */
export function inputView(stage: IngestTraceStage): ViewTable {
  if (messages(stage).length) return { kind: 'empty' };
  return toView(stage.input);
}

// ── Resolve / invalidate facts ────────────────────────────────────────────────────────────
// The EdgeDuplicate output is bare idx arrays (`{duplicate_facts, contradicted_facts}`) that
// only resolve against the prompt's two fact lists. We recover NEW FACT + the candidate facts
// (idx → text) from the captured prompt and join them to the indices into a verdict table.
// graphiti renders the lists as Python `str()` of dicts — single-quoted keys, per-string quote
// style — so the item regex accepts either quote style. Any parse miss → caller falls back to
// the generic table (+ Raw JSON is always available), so a prompt drift degrades, never breaks.
export type FactCandidate = {
  idx: number;
  origin: string;
  fact: string;
  decision: 'duplicate' | 'contradicted' | 'none';
};
export type ResolveFactsView = {
  newFact: string;
  candidates: FactCandidate[];
  dupCount: number;
  contraCount: number;
};

export function tagBlock(text: string, tag: string): string {
  const re = new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`);
  return re.exec(text)?.[1]?.trim() ?? '';
}

export function parseFactItems(block: string): { idx: number; fact: string }[] {
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

export function resolveFactsView(stage: IngestTraceStage): ResolveFactsView | null {
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
export type Brief = { name?: string; entity_type?: string; summary?: string; uuid?: string };
export type Merge = { from: Brief; into: Brief; idx: number };

export function dedupMerges(group: StageGroup): Merge[] {
  return group.stages.map(({ stage, idx }) => ({
    idx,
    from: (stage.input ?? {}) as Brief,
    into: ((stage.output as { merged_into?: Brief })?.merged_into ?? {}) as Brief
  }));
}

export const briefName = (b: Brief): string => b.name || '—';
export const briefType = (b: Brief): string => b.entity_type || '';

/** Raw JSON for a whole dedup group (the merge list) — its collapsible fallback. */
export function dedupJson(group: StageGroup): string {
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
export type ExtractedEntityRow = { name: string; typeName: string; description: string };

export function buildEntityTypeMap(types: IngestEntityType[]): Map<number, IngestEntityType> {
  const m = new Map<number, IngestEntityType>();
  for (const t of types) m.set(t.id, t);
  return m;
}

export function extractedEntities(
  stage: IngestTraceStage,
  entityTypeById: Map<number, IngestEntityType>
): ExtractedEntityRow[] | null {
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

export function stageMeta(stage: IngestTraceStage): string {
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
export function stageCount(
  stage: IngestTraceStage,
  node: string,
  entityTypeById: Map<number, IngestEntityType>
): number | null {
  if (node === 'extract_entities') return extractedEntities(stage, entityTypeById)?.length ?? null;
  if (node === 'resolve_facts') return resolveFactsView(stage)?.candidates.length ?? null;
  const ov = outputView(stage);
  return ov.kind === 'rows' ? ov.rows.length : null;
}
