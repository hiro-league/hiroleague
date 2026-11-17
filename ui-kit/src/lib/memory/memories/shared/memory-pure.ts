// The memories table's rules, free of Svelte: reading a row's fields (flat or under `metadata`), its bi-temporal
// validity, the entities or relation it encodes, its provenance chunk ids, the search and filter predicates, and
// the column ordering. Names for the character and channel ids rows carry come from the app's `MemorySource`
// (`NamedItem`); without them, the ids show.
// UI kit: from the HiroLeague admin's Memories page (features/memories/shared/memory-pure.ts).
import type { MemoryRow, NamedItem } from '$kit/memory/source';
import type { SortDirection } from '$kit/ui/sort.svelte';
import { distinctOptionsWithSentinel } from '$kit/ui/distinct-options';
import { formatCompactDateTime, parseFlexibleDate } from '$kit/format/timestamp';
import { shortGraphId } from '$kit/memory/short-id';
import { rowMatches } from '$kit/search/match';

/** Characters by id. */
export type CharacterMap = Record<string, NamedItem>;
/** Channels by id; rows carry numeric channel ids, so the key is the id as a string. */
export type ChannelMap = Map<string, NamedItem>;

export function memoryPrimaryText(m: MemoryRow): string {
	const raw = m.memory ?? m.text ?? m.content ?? m['data'];
	if (typeof raw === 'string') {
		// A bare entity (kind="entity") has no summarized memory yet: fall back to its name so the Memory cell
		// identifies the entity instead of rendering blank.
		if (raw.trim() === '' && memoryKind(m) === 'entity') {
			return String(memoryField(m, 'entity_name') ?? '').trim();
		}
		return raw;
	}
	if (raw !== null && typeof raw === 'object') return JSON.stringify(raw);
	return raw === null || raw === undefined ? '' : String(raw as string | number | boolean);
}

export function memoryStableKey(m: MemoryRow, index: number): string {
	const id = m.id ?? m.memory_id;
	if (typeof id === 'string' && id.length > 0) return id;
	if (typeof id === 'number' && Number.isFinite(id)) return String(id);
	return `mem-${index}`;
}

export function memoryId(row: MemoryRow): string {
	const raw = row.id ?? row.memory_id;
	return raw === null || raw === undefined ? '' : String(raw as string | number).trim();
}

export function memoryMetadata(row: MemoryRow): Record<string, unknown> {
	const metadata = row.metadata;
	return metadata && typeof metadata === 'object' && !Array.isArray(metadata)
		? (metadata as Record<string, unknown>)
		: {};
}

export function memoryField(row: MemoryRow, ...keys: string[]): unknown {
	const metadata = memoryMetadata(row);
	for (const key of keys) {
		const direct = row[key];
		if (direct !== null && direct !== undefined && direct !== '') return direct;
		const meta = metadata[key];
		if (meta !== null && meta !== undefined && meta !== '') return meta;
	}
	return null;
}

/** A field as trimmed text ('' when absent). */
function fieldText(row: MemoryRow, ...keys: string[]): string {
	return String((memoryField(row, ...keys) ?? '') as string | number | boolean).trim();
}

/** Flexible epoch/ISO timestamp parsing (the kit's timestamp helper). */
export const parseMemoryDate = parseFlexibleDate;

export function memoryUpdatedRaw(row: MemoryRow): unknown {
	return memoryField(row, 'updated_at', 'updatedAt', 'updated');
}

export function memoryCreatedRaw(row: MemoryRow): unknown {
	return memoryField(row, 'created_at', 'createdAt', 'created');
}

export function memorySortSeconds(row: MemoryRow): number {
	const updated = parseMemoryDate(memoryUpdatedRaw(row));
	const created = parseMemoryDate(memoryCreatedRaw(row));
	return (updated ?? created)?.getTime() ?? 0;
}

/** Compact date/time cell formatting (the kit's timestamp helper). */
export const memoryDateDisplay = formatCompactDateTime;

export function memoryChannelId(row: MemoryRow): number | null {
	const raw = memoryField(row, 'channel_id', 'chat_channel_id');
	if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) return raw;
	if (typeof raw === 'string') {
		const numeric = Number(raw.trim());
		if (Number.isFinite(numeric) && numeric > 0) return numeric;
	}
	return null;
}

export function memoryChannel(row: MemoryRow, channelById: ChannelMap): NamedItem | undefined {
	const id = memoryChannelId(row);
	return id === null ? undefined : channelById.get(String(id));
}

export function memoryChannelName(row: MemoryRow, channelById: ChannelMap): string {
	const id = memoryChannelId(row);
	if (id === null) return '—';
	const name = channelById.get(String(id))?.name?.trim();
	return name || `Channel ${id}`;
}

export function memoryAgentId(row: MemoryRow): string {
	return fieldText(row, 'agent_id', 'character_id');
}

/** The character a row belongs to: its own character's name and photo, else its channel's character, else the id. */
export function memoryCharacter(
	row: MemoryRow,
	characterMap: CharacterMap,
	channelById: ChannelMap
): { name: string; photo: string | null } {
	const agentId = memoryAgentId(row);
	const ch = memoryChannel(row, channelById);
	const character = agentId ? characterMap[agentId] : undefined;
	const name = character?.name?.trim() || ch?.characterName?.trim() || agentId || '—';
	const photo = character?.photo || ch?.photo || null;
	return { name, photo };
}

export function memorySharedLabel(row: MemoryRow): string {
	const raw = memoryField(row, 'shared');
	if (typeof raw === 'boolean') return raw ? 'Yes' : 'No';
	if (typeof raw === 'string') {
		const lower = raw.trim().toLowerCase();
		if (['true', '1', 'yes'].includes(lower)) return 'Yes';
		if (['false', '0', 'no'].includes(lower)) return 'No';
	}
	return '—';
}

export function memorySourceLabel(row: MemoryRow): string {
	return fieldText(row, 'source') || '—';
}

// ---- The graph behind each fact (the table's columns) ----------------------------------------------------------
// Its kind (a relation edge or an entity's summary), bi-temporal validity, the entities or relation it encodes, the
// partition it lives in, and its provenance chunk ids: fields the backend adds to each row.

export type MemoryKind = 'relation' | 'summary' | 'entity' | '';

/** 'relation' = a fact edge between two entities; 'summary' = an entity attribute summary;
 *  'entity' = an entity with no summary yet (shown so the list covers every entity). */
export function memoryKind(row: MemoryRow): MemoryKind {
	const k = String((row.kind ?? '') as string).trim().toLowerCase();
	return k === 'relation' || k === 'summary' || k === 'entity' ? k : '';
}

export function memoryKindLabel(row: MemoryRow): string {
	const k = memoryKind(row);
	if (k === 'relation') return 'Relation';
	if (k === 'summary') return 'Summary';
	if (k === 'entity') return 'Entity';
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
export function memoryValidity(row: MemoryRow): MemoryValidity {
	const invalidAt = memoryField(row, 'invalid_at', 'invalidAt');
	const expiredAt = memoryField(row, 'expired_at', 'expiredAt');
	const validAt = memoryCreatedRaw(row); // created_at IS the edge's valid_at
	return { expired: invalidAt != null || expiredAt != null, invalidAt, expiredAt, validAt };
}

export type MemoryEntities =
	| { kind: 'relation'; source: string; relation: string; target: string }
	| { kind: 'summary'; entity: string; type: string }
	| null;

/** The structured entities/relation a fact encodes: `Source —[REL]→ Target` for relations, `Entity (Type)` for
 *  summaries. Endpoint names fall back to a short uuid when unresolved. */
export function memoryEntities(row: MemoryRow): MemoryEntities {
	const k = memoryKind(row);
	if (k === 'relation') {
		const source = fieldText(row, 'source_name') || shortGraphId(String((row.source_id ?? '') as string));
		const target = fieldText(row, 'target_name') || shortGraphId(String((row.target_id ?? '') as string));
		const relation = fieldText(row, 'relation');
		if (!source && !target && !relation) return null;
		return { kind: 'relation', source, relation, target };
	}
	if (k === 'summary' || k === 'entity') {
		const entity = fieldText(row, 'entity_name');
		const type = fieldText(row, 'entity_type');
		if (!entity && !type) return null;
		return { kind: 'summary', entity, type };
	}
	return null;
}

export function memoryGroupId(row: MemoryRow): string {
	return fieldText(row, 'group_id', 'groupId');
}

/** Supporting episode/message ids (provenance): the turns a fact was extracted from. */
export function memoryChunkIds(row: MemoryRow): string[] {
	const raw = row.chunk_ids;
	if (!Array.isArray(raw)) return [];
	return raw.map((c) => String((c ?? '') as string).trim()).filter(Boolean);
}

/** Case-insensitive substring match across the common row fields (the search box). */
export function memoryRowMatchesSearch(
	row: MemoryRow,
	query: string,
	characterMap: CharacterMap,
	channelById: ChannelMap
): boolean {
	return rowMatches(row, query, (r) => [
		memoryPrimaryText(r),
		memoryId(r),
		fieldText(r, 'source'),
		memoryChannelName(r, channelById),
		memoryCharacter(r, characterMap, channelById).name
	]);
}

export type MemoryRowFilterOpts = {
	characterId: string;
	sourceFilter: string;
	searchQuery: string;
	// Date-range scope (ms epoch, NaN when unset); also defines what "Clear memories" deletes.
	dateFromMs: number;
	dateToMs: number;
	characterMap: CharacterMap;
	channelById: ChannelMap;
};

export function memoryRowPassesFilters(row: MemoryRow, opts: MemoryRowFilterOpts): boolean {
	const charF = opts.characterId.trim();
	if (charF && memoryAgentId(row) !== charF) return false;

	// Date-range filter by the memory's effective timestamp (valid_at / created). Undated rows fall outside any
	// explicit range so a date scope never silently deletes them.
	if (Number.isFinite(opts.dateFromMs) || Number.isFinite(opts.dateToMs)) {
		const ts = memorySortSeconds(row);
		if (ts === 0) return false;
		if (Number.isFinite(opts.dateFromMs) && ts < opts.dateFromMs) return false;
		if (Number.isFinite(opts.dateToMs) && ts > opts.dateToMs) return false;
	}

	const srcF = opts.sourceFilter;
	if (srcF === '__empty__') {
		if (fieldText(row, 'source') !== '') return false;
	} else if (srcF.trim()) {
		if (fieldText(row, 'source') !== srcF.trim()) return false;
	}

	if (opts.searchQuery.trim() && !memoryRowMatchesSearch(row, opts.searchQuery, opts.characterMap, opts.channelById)) {
		return false;
	}
	return true;
}

// ---- Filter options and date inputs ----------------------------------------------------------------------------

/** Source dropdown options from the loaded rows: distinct non-empty sources sorted alphabetically, after a
 *  "(no source)" choice when any row has none. */
export function memorySourceOptions(rows: MemoryRow[]): { value: string; label: string }[] {
	return distinctOptionsWithSentinel(rows, (row) => fieldText(row, 'source'), {
		emptyLabel: '(no source)'
	});
}

/** A `yyyy-mm-dd` date-input value as ms epoch (NaN when blank). `endOfDay` snaps to the inclusive end of the day
 *  so a "to" bound includes that whole date. */
export function memoryDateInputMs(value: string, endOfDay = false): number {
	const v = value.trim();
	if (!v) return NaN;
	return new Date(`${v}T${endOfDay ? '23:59:59.999' : '00:00:00'}`).getTime();
}

// ---- The table's filters, kept in the address -------------------------------------------------------------------
// Namespaced (`mem_*`) so they never collide with the page's `?tab=` or the graph's own parameters.
export const MEMORY_FILTER_KEYS = ['mem_group', 'mem_char', 'mem_source', 'mem_from', 'mem_to', 'mem_q'] as const;
export type MemoryFilterKey = (typeof MEMORY_FILTER_KEYS)[number];

// ---- Sorting (the column headers) -------------------------------------------------------------------------------

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

/** Most recent first. */
export const DEFAULT_MEMORY_SORT: { column: MemorySortColumn; direction: SortDirection } = {
	column: 'created',
	direction: 'desc'
};

export type MemorySortOpts = {
	characterMap: CharacterMap;
	channelById: ChannelMap;
	/** group_id → logical label; the raw id orders when absent. */
	groupLabelById?: Map<string, string>;
};

/** The text a column compares on (the entities column flattens to one comparable string). */
function memoryEntitiesText(row: MemoryRow): string {
	const e = memoryEntities(row);
	if (!e) return '';
	return e.kind === 'relation' ? `${e.source} ${e.relation} ${e.target}` : `${e.entity} ${e.type}`;
}

function compareMemoryColumn(a: MemoryRow, b: MemoryRow, column: MemorySortColumn, opts: MemorySortOpts): number {
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
			const label = (row: MemoryRow) => opts.groupLabelById?.get(memoryGroupId(row)) ?? memoryGroupId(row);
			return label(a).localeCompare(label(b));
		}
		case 'id':
			return memoryId(a).localeCompare(memoryId(b));
		default:
			return 0;
	}
}

/** Stable, direction-aware sort. Ties break by recency then id so the order never jitters. */
export function sortMemories(
	rows: MemoryRow[],
	column: MemorySortColumn,
	direction: SortDirection,
	opts: MemorySortOpts
): MemoryRow[] {
	const factor = direction === 'asc' ? 1 : -1;
	return [...rows].sort((a, b) => {
		const primary = compareMemoryColumn(a, b, column, opts);
		if (primary !== 0) return factor * primary;
		const recency = memorySortSeconds(b) - memorySortSeconds(a);
		if (recency !== 0) return recency;
		return memoryId(a).localeCompare(memoryId(b));
	});
}
