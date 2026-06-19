import { PREF_KEYS } from '$lib/preferences/keys';
import {
  readLocalString,
  readSessionString,
  removeSessionString,
  writeLocalString,
  writeSessionString
} from '$lib/preferences/storage';
import {
  EDGE_FILTER_DEFAULTS,
  LOW_CONN_THRESHOLD_MIN,
  MAX_CONN_PER_NODE_CAP,
  VISIBLE_EDGES_CAP,
  VISIBLE_EDGES_MIN,
  type EdgeFilterModes,
  type EdgeValidity,
  type LowConnTreatment,
  type MaxConnBy
} from './graph-types';

export const SESSION_HIDE_NODES = PREF_KEYS.knowledgeGraphHideNodes;
export const SESSION_HIDE_EDGES = PREF_KEYS.knowledgeGraphHideEdges;
export const SESSION_ACTIVE_GROUP = PREF_KEYS.knowledgeGraphActiveGroup;
export const SESSION_EPISODE_SEL = PREF_KEYS.knowledgeGraphEpisodeSel;

export function readEdgeFilterModes(): EdgeFilterModes {
  const raw = readLocalString(PREF_KEYS.knowledgeGraphEdgeFilters);
  if (!raw) return { ...EDGE_FILTER_DEFAULTS };
  try {
    const p = JSON.parse(raw) as Partial<EdgeFilterModes>;
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
  } catch {
    return { ...EDGE_FILTER_DEFAULTS };
  }
}

export function persistEdgeFilterModes(modes: EdgeFilterModes): void {
  writeLocalString(PREF_KEYS.knowledgeGraphEdgeFilters, JSON.stringify(modes));
}

export function readEpisodeSel(groupId: string): string[] {
  const raw = readSessionString(SESSION_EPISODE_SEL);
  if (!raw) return [];
  try {
    const map = JSON.parse(raw) as Record<string, string[]>;
    const ids = map[groupId];
    return Array.isArray(ids) ? ids.filter((s): s is string => typeof s === 'string') : [];
  } catch {
    return [];
  }
}

export function writeEpisodeSel(groupId: string, ids: string[]): void {
  const raw = readSessionString(SESSION_EPISODE_SEL);
  let map: Record<string, string[]> = {};
  if (raw) {
    try {
      map = JSON.parse(raw) as Record<string, string[]>;
    } catch {
      map = {};
    }
  }
  if (ids.length > 0) map[groupId] = ids;
  else delete map[groupId];
  if (Object.keys(map).length > 0) writeSessionString(SESSION_EPISODE_SEL, JSON.stringify(map));
  else removeSessionString(SESSION_EPISODE_SEL);
}

export function readHidden(key: string): Set<string> {
  const raw = readSessionString(key);
  if (!raw) return new Set();
  return new Set(
    raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  );
}

export function writeHidden(key: string, hidden: Set<string>): void {
  if (hidden.size > 0) writeSessionString(key, [...hidden].join(','));
  else removeSessionString(key);
}

export function readActiveGroup(): string | null {
  return readSessionString(SESSION_ACTIVE_GROUP);
}

export function writeActiveGroup(id: string | null): void {
  if (id) writeSessionString(SESSION_ACTIVE_GROUP, id);
  else removeSessionString(SESSION_ACTIVE_GROUP);
}
