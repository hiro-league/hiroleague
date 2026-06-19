/**
 * Side-effect-free helpers for the Memories admin feature (long-term Graphiti facts):
 * row field access over the flat/`metadata` shape, bi-temporal validity, entity/relation
 * structure, provenance chunk ids, search + filter predicates, and date display.
 *
 * Carved out of the old shared `graph-runs/graph-runs-pure.ts` when Memories became its
 * own feature. Kept separate from the Svelte components so parsing/formatting stay
 * unit-testable.
 */
import type { ChatChannelRow } from '$lib/api/chat-channels';
import type { CharacterRow } from '$lib/api/characters';
import type { TableSortDirection } from '$lib/components/page/table/table-sort-utils';
import { formatCompactDateTime, parseFlexibleDate } from '$lib/format/compact-datetime';
import { shortGraphId } from '$lib/format/short-graph-id';

export function memoryPrimaryText(m: Record<string, unknown>): string {
  const raw = m.memory ?? m.text ?? m.content ?? m['data'];
  if (typeof raw === 'string') return raw;
  if (raw !== null && typeof raw === 'object') return JSON.stringify(raw);
  return raw === null || raw === undefined ? '' : String(raw);
}

export function memoryStableKey(m: Record<string, unknown>, index: number): string {
  const id = m.id ?? m.memory_id;
  if (typeof id === 'string' && id.length > 0) return id;
  if (typeof id === 'number' && Number.isFinite(id)) return String(id);
  return `mem-${index}`;
}

export function memoryId(row: Record<string, unknown>): string {
  const raw = row.id ?? row.memory_id;
  return raw === null || raw === undefined ? '' : String(raw).trim();
}

export function memoryMetadata(row: Record<string, unknown>): Record<string, unknown> {
  const metadata = row.metadata;
  return metadata && typeof metadata === 'object' && !Array.isArray(metadata)
    ? (metadata as Record<string, unknown>)
    : {};
}

export function memoryField(row: Record<string, unknown>, ...keys: string[]): unknown {
  const metadata = memoryMetadata(row);
  for (const key of keys) {
    const direct = row[key];
    if (direct !== null && direct !== undefined && direct !== '') return direct;
    const meta = metadata[key];
    if (meta !== null && meta !== undefined && meta !== '') return meta;
  }
  return null;
}

/** Flexible epoch/ISO timestamp parsing (shared compact-datetime util). */
export const parseMemoryDate = parseFlexibleDate;

export function memoryUpdatedRaw(row: Record<string, unknown>): unknown {
  return memoryField(row, 'updated_at', 'updatedAt', 'updated');
}

export function memoryCreatedRaw(row: Record<string, unknown>): unknown {
  return memoryField(row, 'created_at', 'createdAt', 'created');
}

export function memorySortSeconds(row: Record<string, unknown>): number {
  const updated = parseMemoryDate(memoryUpdatedRaw(row));
  const created = parseMemoryDate(memoryCreatedRaw(row));
  return (updated ?? created)?.getTime() ?? 0;
}

/** Compact date/time cell formatting (shared compact-datetime util). */
export const memoryDateDisplay = formatCompactDateTime;

export function memoryChannelId(row: Record<string, unknown>): number | null {
  const raw = memoryField(row, 'channel_id', 'chat_channel_id');
  if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) return raw;
  if (typeof raw === 'string') {
    const numeric = Number(raw.trim());
    if (Number.isFinite(numeric) && numeric > 0) return numeric;
  }
  return null;
}

export function memoryChannel(
  row: Record<string, unknown>,
  channelById: Map<number, ChatChannelRow>
): ChatChannelRow | undefined {
  const id = memoryChannelId(row);
  return id === null ? undefined : channelById.get(id);
}

export function memoryChannelName(
  row: Record<string, unknown>,
  channelById: Map<number, ChatChannelRow>
): string {
  const id = memoryChannelId(row);
  if (id === null) return '—';
  const name = channelById.get(id)?.name?.trim();
  return name || `Channel ${id}`;
}

export function memoryAgentId(row: Record<string, unknown>): string {
  return String(memoryField(row, 'agent_id', 'character_id') ?? '').trim();
}

export function memoryCharacter(
  row: Record<string, unknown>,
  characterMap: Record<string, CharacterRow>,
  channelById: Map<number, ChatChannelRow>
): { name: string; photo: string | null } {
  const agentId = memoryAgentId(row);
  const ch = memoryChannel(row, channelById);
  const character = agentId ? characterMap[agentId] : undefined;
  const name = character?.name?.trim() || ch?.character?.name?.trim() || (agentId || '—');
  const photo = character?.photo_data_url || ch?.photo_data_url || null;
  return { name, photo };
}

export function memorySharedLabel(row: Record<string, unknown>): string {
  const raw = memoryField(row, 'shared');
  if (typeof raw === 'boolean') return raw ? 'Yes' : 'No';
  if (typeof raw === 'string') {
    const lower = raw.trim().toLowerCase();
    if (['true', '1', 'yes'].includes(lower)) return 'Yes';
    if (['false', '0', 'no'].includes(lower)) return 'No';
  }
  return '—';
}

export function memorySourceLabel(row: Record<string, unknown>): string {
  const source = String(memoryField(row, 'source') ?? '').trim();
  return source || '—';
}

// ── Graph-structure accessors (Memories table columns) ──────────────────────
// These expose the graph shape behind each remembered fact: its kind (relation edge vs
// entity attribute summary), bi-temporal validity, the entities/relation it encodes, the
// partition it lives in, and its provenance chunk_ids. All read fields the backend now
// enriches onto each row (see graphiti_service._edge_to_memory/_node_to_memory).

export type MemoryKind = 'relation' | 'summary' | '';

/** 'relation' = a fact edge between two entities; 'summary' = an entity attribute summary. */
export function memoryKind(row: Record<string, unknown>): MemoryKind {
  const k = String(row.kind ?? '').trim().toLowerCase();
  return k === 'relation' || k === 'summary' ? k : '';
}

export function memoryKindLabel(row: Record<string, unknown>): string {
  const k = memoryKind(row);
  if (k === 'relation') return 'Relation';
  if (k === 'summary') return 'Summary';
  return '—';
}

export type MemoryValidity = {
  /** A fact is no longer current once it has an invalid_at (stopped being true) or expired_at. */
  expired: boolean;
  invalidAt: unknown;
  expiredAt: unknown;
  validAt: unknown;
};

/** Bi-temporal status of a fact. Summaries are always current (no invalid_at). */
export function memoryValidity(row: Record<string, unknown>): MemoryValidity {
  const invalidAt = memoryField(row, 'invalid_at', 'invalidAt');
  const expiredAt = memoryField(row, 'expired_at', 'expiredAt');
  const validAt = memoryCreatedRaw(row); // created_at IS the edge's valid_at
  return { expired: invalidAt != null || expiredAt != null, invalidAt, expiredAt, validAt };
}

export type MemoryEntities =
  | { kind: 'relation'; source: string; relation: string; target: string }
  | { kind: 'summary'; entity: string; type: string }
  | null;

/** The structured entities/relation a fact encodes: `Source —[REL]→ Target` for relations,
 *  `Entity (Type)` for summaries. Endpoint names fall back to a short uuid when unresolved. */
export function memoryEntities(row: Record<string, unknown>): MemoryEntities {
  const k = memoryKind(row);
  if (k === 'relation') {
    const source =
      String(memoryField(row, 'source_name') ?? '').trim() ||
      shortGraphId(String(row.source_id ?? ''));
    const target =
      String(memoryField(row, 'target_name') ?? '').trim() ||
      shortGraphId(String(row.target_id ?? ''));
    const relation = String(memoryField(row, 'relation') ?? '').trim();
    if (!source && !target && !relation) return null;
    return { kind: 'relation', source, relation, target };
  }
  if (k === 'summary') {
    const entity = String(memoryField(row, 'entity_name') ?? '').trim();
    const type = String(memoryField(row, 'entity_type') ?? '').trim();
    if (!entity && !type) return null;
    return { kind: 'summary', entity, type };
  }
  return null;
}

export function memoryGroupId(row: Record<string, unknown>): string {
  return String(memoryField(row, 'group_id', 'groupId') ?? '').trim();
}

/** Supporting episode/message ids (provenance) — the turns a fact was extracted from. */
export function memoryChunkIds(row: Record<string, unknown>): string[] {
  const raw = row.chunk_ids;
  if (!Array.isArray(raw)) return [];
  return raw.map((c) => String(c ?? '').trim()).filter(Boolean);
}

/** Case-insensitive substring match across common memory row fields (Memories search). */
export function memoryRowMatchesSearchNeedle(
  row: Record<string, unknown>,
  needleLower: string,
  characterMap: Record<string, CharacterRow>,
  channelById: Map<number, ChatChannelRow>
): boolean {
  if (!needleLower) return true;
  const primary = memoryPrimaryText(row).toLowerCase();
  const id = memoryId(row).toLowerCase();
  const src = String(memoryField(row, 'source') ?? '').toLowerCase();
  const chName = memoryChannelName(row, channelById).toLowerCase();
  const charName = memoryCharacter(row, characterMap, channelById).name.toLowerCase();
  return (
    primary.includes(needleLower) ||
    id.includes(needleLower) ||
    src.includes(needleLower) ||
    chName.includes(needleLower) ||
    charName.includes(needleLower)
  );
}

export type MemoryRowFilterOpts = {
  characterId: string;
  sourceFilter: string;
  searchNeedle: string;
  // Date-range scope (ms epoch, NaN when unset) — also defines a delete scope on the pane.
  dateFromMs: number;
  dateToMs: number;
  characterMap: Record<string, CharacterRow>;
  channelById: Map<number, ChatChannelRow>;
};

export function memoryRowPassesFilters(row: Record<string, unknown>, opts: MemoryRowFilterOpts): boolean {
  const charF = opts.characterId.trim();
  if (charF && memoryAgentId(row) !== charF) return false;

  // Date-range filter by the memory's effective timestamp (valid_at / created). Undated
  // rows fall outside any explicit range so a date scope never silently deletes them.
  if (Number.isFinite(opts.dateFromMs) || Number.isFinite(opts.dateToMs)) {
    const ts = memorySortSeconds(row);
    if (ts === 0) return false;
    if (Number.isFinite(opts.dateFromMs) && ts < opts.dateFromMs) return false;
    if (Number.isFinite(opts.dateToMs) && ts > opts.dateToMs) return false;
  }

  const srcF = opts.sourceFilter;
  if (srcF === '__empty__') {
    if (String(memoryField(row, 'source') ?? '').trim() !== '') return false;
  } else if (srcF.trim()) {
    const rowSrc = String(memoryField(row, 'source') ?? '').trim();
    if (rowSrc !== srcF.trim()) return false;
  }

  if (opts.searchNeedle && !memoryRowMatchesSearchNeedle(row, opts.searchNeedle, opts.characterMap, opts.channelById)) {
    return false;
  }
  return true;
}

// ── Filter option + date-input derivation (pure) ────────────────────────────

/**
 * Source dropdown options derived from the loaded rows: distinct non-empty sources sorted
 * alphabetically, prefixed with a "(no source)" sentinel option when any row has no source.
 */
export function memorySourceOptions(
  rows: Record<string, unknown>[]
): { value: string; label: string }[] {
  const raw = new Set<string>();
  let anyEmpty = false;
  for (const row of rows) {
    const s = String(memoryField(row, 'source') ?? '').trim();
    if (s === '') anyEmpty = true;
    else raw.add(s);
  }
  const out: { value: string; label: string }[] = [];
  if (anyEmpty) out.push({ value: '__empty__', label: '(no source)' });
  for (const s of [...raw].sort((a, b) => a.localeCompare(b))) {
    out.push({ value: s, label: s });
  }
  return out;
}

/**
 * Parse a `yyyy-mm-dd` date-input value into ms epoch (NaN when blank). `endOfDay` snaps to the
 * inclusive end of the day so a "to" bound includes that whole date.
 */
export function memoryDateInputMs(value: string, endOfDay = false): number {
  const v = value.trim();
  if (!v) return NaN;
  return new Date(`${v}T${endOfDay ? '23:59:59.999' : '00:00:00'}`).getTime();
}

// ── Table filter keys (URL-synced) ──────────────────────────────────────────
// Namespaced (`mem_*`) so they never collide with the page-level `?tab=` param or the
// Graph tab. Shared by the controller (write path) and the panel (typed bindings).
export const MEMORY_FILTER_KEYS = ['mem_group', 'mem_char', 'mem_source', 'mem_from', 'mem_to', 'mem_q'] as const;
export type MemoryFilterKey = (typeof MEMORY_FILTER_KEYS)[number];

// ── Sorting (Memories table column headers) ─────────────────────────────────
// Pure, deterministic ordering driven by the `useTableSort` controller. Kept here
// (not in the controller) so column ordering stays unit-testable.

export type MemorySortColumn =
  | 'kind'
  | 'created'
  | 'validity'
  | 'character'
  | 'memory'
  | 'entities'
  | 'group'
  | 'origin'
  | 'id';

export const MEMORY_SORT_COLUMNS: readonly MemorySortColumn[] = [
  'kind',
  'created',
  'validity',
  'character',
  'memory',
  'entities',
  'group',
  'origin',
  'id'
] as const;

/** Most-recent-first is the default, matching the historical hard-coded order. */
export const DEFAULT_MEMORY_SORT: { column: MemorySortColumn; direction: TableSortDirection } = {
  column: 'created',
  direction: 'desc'
};

export type MemorySortOpts = {
  characterMap: Record<string, CharacterRow>;
  channelById: Map<number, ChatChannelRow>;
  /** group_id → logical label; falls back to the raw id for ordering when absent. */
  groupLabelById?: Map<string, string>;
};

/** The text a column compares on (entity columns flatten to a single comparable string). */
function memoryEntitiesText(row: Record<string, unknown>): string {
  const e = memoryEntities(row);
  if (!e) return '';
  return e.kind === 'relation' ? `${e.source} ${e.relation} ${e.target}` : `${e.entity} ${e.type}`;
}

function compareMemoryColumn(
  a: Record<string, unknown>,
  b: Record<string, unknown>,
  column: MemorySortColumn,
  opts: MemorySortOpts
): number {
  switch (column) {
    case 'created':
      return memorySortSeconds(a) - memorySortSeconds(b);
    case 'validity':
      // current (false → 0) sorts before expired (true → 1)
      return Number(memoryValidity(a).expired) - Number(memoryValidity(b).expired);
    case 'origin':
      return memoryChunkIds(a).length - memoryChunkIds(b).length;
    case 'kind':
      return memoryKindLabel(a).localeCompare(memoryKindLabel(b));
    case 'character':
      return memoryCharacter(a, opts.characterMap, opts.channelById).name.localeCompare(
        memoryCharacter(b, opts.characterMap, opts.channelById).name
      );
    case 'memory':
      return memoryPrimaryText(a).localeCompare(memoryPrimaryText(b));
    case 'entities':
      return memoryEntitiesText(a).localeCompare(memoryEntitiesText(b));
    case 'group': {
      const label = (row: Record<string, unknown>) =>
        opts.groupLabelById?.get(memoryGroupId(row)) ?? memoryGroupId(row);
      return label(a).localeCompare(label(b));
    }
    case 'id':
      return memoryId(a).localeCompare(memoryId(b));
    default:
      return 0;
  }
}

/** Stable, direction-aware sort. Ties break by recency then id so order never jitters. */
export function sortMemories(
  rows: Record<string, unknown>[],
  column: MemorySortColumn,
  direction: TableSortDirection,
  opts: MemorySortOpts
): Record<string, unknown>[] {
  const factor = direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const primary = compareMemoryColumn(a, b, column, opts);
    if (primary !== 0) return factor * primary;
    const recency = memorySortSeconds(b) - memorySortSeconds(a);
    if (recency !== 0) return recency;
    return memoryId(a).localeCompare(memoryId(b));
  });
}
