// What the graph viewer remembers in this browser: its fact-filter modes, the hidden node ids and fact types, the
// active group and each group's episode selection. All through $kit/state/persist (keys from the app's prefs.ts).
import { isRecord, load, save } from '$kit/state/persist';
import {
	EDGE_FILTER_DEFAULTS,
	LOW_CONN_THRESHOLD_MIN,
	MAX_CONN_PER_NODE_CAP,
	VISIBLE_EDGES_CAP,
	VISIBLE_EDGES_MIN,
	type EdgeFilterModes,
	type EdgeValidity
} from './graph-types';

export const HIDE_NODES_KEY = 'graph.hideNodes';
export const HIDE_EDGES_KEY = 'graph.hideEdges';
const EDGE_FILTERS_KEY = 'graph.edgeFilters';
const ACTIVE_GROUP_KEY = 'graph.group';
const EPISODE_SEL_KEY = 'graph.episodes';

export type HiddenKey = typeof HIDE_NODES_KEY | typeof HIDE_EDGES_KEY;

const isStringArray = (v: unknown): v is string[] => Array.isArray(v) && v.every((s) => typeof s === 'string');

/** The stored modes, each field clamped to its range; defaults for what is absent or broken. */
export function readEdgeFilterModes(): EdgeFilterModes {
	const p = load<Record<string, unknown> | null>(EDGE_FILTERS_KEY, null, isRecord);
	if (!p) return { ...EDGE_FILTER_DEFAULTS };
	const cap = Number(p.maxConnPerNode);
	const vis = Number(p.visibleEdgesPerPair);
	return {
		edgeValidity: (['all', 'valid', 'invalid'] as const).includes(p.edgeValidity as EdgeValidity)
			? (p.edgeValidity as EdgeValidity)
			: EDGE_FILTER_DEFAULTS.edgeValidity,
		includeUndatedEdges:
			typeof p.includeUndatedEdges === 'boolean'
				? p.includeUndatedEdges
				: EDGE_FILTER_DEFAULTS.includeUndatedEdges,
		maxConnPerNode: Number.isFinite(cap)
			? Math.min(MAX_CONN_PER_NODE_CAP, Math.max(1, Math.round(cap)))
			: EDGE_FILTER_DEFAULTS.maxConnPerNode,
		maxConnBy: p.maxConnBy === 'oldest' ? 'oldest' : 'newest',
		visibleEdgesPerPair: Number.isFinite(vis)
			? Math.min(VISIBLE_EDGES_CAP, Math.max(VISIBLE_EDGES_MIN, Math.round(vis)))
			: EDGE_FILTER_DEFAULTS.visibleEdgesPerPair,
		lowConnTreatment: p.lowConnTreatment === 'hide' ? 'hide' : 'dim',
		lowConnThreshold: Number.isFinite(Number(p.lowConnThreshold))
			? Math.max(LOW_CONN_THRESHOLD_MIN, Math.round(Number(p.lowConnThreshold)))
			: EDGE_FILTER_DEFAULTS.lowConnThreshold
	};
}

export function persistEdgeFilterModes(modes: EdgeFilterModes): void {
	save(EDGE_FILTERS_KEY, modes);
}

/** Every group's episode selection: `{ group_id: chunk_id[] }`. */
function readEpisodeMap(): Record<string, string[]> {
	const map = load<Record<string, unknown>>(EPISODE_SEL_KEY, {}, isRecord);
	const out: Record<string, string[]> = {};
	for (const [gid, ids] of Object.entries(map)) if (isStringArray(ids)) out[gid] = ids;
	return out;
}

export function readEpisodeSel(groupId: string): string[] {
	return readEpisodeMap()[groupId] ?? [];
}

export function writeEpisodeSel(groupId: string, ids: string[]): void {
	const map = readEpisodeMap();
	if (ids.length > 0) map[groupId] = ids;
	else delete map[groupId];
	save(EPISODE_SEL_KEY, map);
}

export function readHidden(key: HiddenKey): Set<string> {
	return new Set(load<string[]>(key, [], isStringArray).filter(Boolean));
}

export function writeHidden(key: HiddenKey, hidden: Set<string>): void {
	save(key, [...hidden]);
}

export function readActiveGroup(): string | null {
	return load<string | null>(ACTIVE_GROUP_KEY, null, (v) => typeof v === 'string' && v !== '');
}

export function writeActiveGroup(id: string | null): void {
	save(ACTIVE_GROUP_KEY, id);
}

/**
 * Open the graph focused on ONE episode of ONE group: makes `groupId` the active group and `[episodeId]` its episode
 * selection (other groups' selections stay). The model restores both when it starts (`loadGroups` → the active group,
 * `loadEpisodes` → the selection), so a link from another page (an eval corpus row's "graph" button) lands filtered.
 * Call it before navigating to the page that shows the graph.
 */
export function seedGraphEpisodeFocus(groupId: string, episodeId: string): void {
	if (!groupId || !episodeId) return;
	writeActiveGroup(groupId);
	writeEpisodeSel(groupId, [episodeId]);
}
