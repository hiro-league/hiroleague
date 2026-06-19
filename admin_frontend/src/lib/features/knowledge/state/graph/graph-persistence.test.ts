import { describe, expect, it, beforeEach, vi } from 'vitest';

vi.mock('$app/environment', () => ({ browser: true }));

beforeEach(() => {
  const local = new Map<string, string>();
  const session = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (local.has(k) ? local.get(k)! : null),
    setItem: (k: string, v: string) => void local.set(k, String(v)),
    removeItem: (k: string) => void local.delete(k),
    clear: () => local.clear()
  });
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => (session.has(k) ? session.get(k)! : null),
    setItem: (k: string, v: string) => void session.set(k, String(v)),
    removeItem: (k: string) => void session.delete(k),
    clear: () => session.clear()
  });
});

import { PREF_KEYS } from '$lib/preferences/keys';
import { EDGE_FILTER_DEFAULTS } from './graph-types';
import {
  persistEdgeFilterModes,
  readActiveGroup,
  readEdgeFilterModes,
  readEpisodeSel,
  readHidden,
  SESSION_HIDE_EDGES,
  SESSION_HIDE_NODES,
  writeActiveGroup,
  writeEpisodeSel,
  writeHidden
} from './graph-persistence';

describe('readEdgeFilterModes / persistEdgeFilterModes', () => {
  it('round-trips edge filter modes via localStorage', () => {
    const modes = {
      ...EDGE_FILTER_DEFAULTS,
      edgeValidity: 'valid' as const,
      maxConnPerNode: 5,
      lowConnTreatment: 'hide' as const,
      lowConnThreshold: 2
    };
    persistEdgeFilterModes(modes);
    const read = readEdgeFilterModes();
    expect(read.edgeValidity).toBe('valid');
    expect(read.maxConnPerNode).toBe(5);
    expect(read.lowConnTreatment).toBe('hide');
    expect(read.lowConnThreshold).toBe(2);
    expect(localStorage.getItem(PREF_KEYS.knowledgeGraphEdgeFilters)).toBeTruthy();
  });

  it('returns defaults when unset or corrupt', () => {
    localStorage.setItem(PREF_KEYS.knowledgeGraphEdgeFilters, '{not json');
    expect(readEdgeFilterModes()).toEqual({ ...EDGE_FILTER_DEFAULTS });
  });
});

describe('readHidden / writeHidden', () => {
  it('round-trips comma-separated session ids', () => {
    writeHidden(SESSION_HIDE_NODES, new Set(['a', 'b']));
    expect(readHidden(SESSION_HIDE_NODES)).toEqual(new Set(['a', 'b']));
    writeHidden(SESSION_HIDE_NODES, new Set());
    expect(readHidden(SESSION_HIDE_NODES)).toEqual(new Set());
  });

  it('isolates node vs edge hide keys', () => {
    writeHidden(SESSION_HIDE_NODES, new Set(['n1']));
    writeHidden(SESSION_HIDE_EDGES, new Set(['REL']));
    expect(readHidden(SESSION_HIDE_NODES)).toEqual(new Set(['n1']));
    expect(readHidden(SESSION_HIDE_EDGES)).toEqual(new Set(['REL']));
  });
});

describe('readEpisodeSel / writeEpisodeSel', () => {
  it('stores per-group episode selections in session', () => {
    writeEpisodeSel('g1', ['ep1', 'ep2']);
    expect(readEpisodeSel('g1')).toEqual(['ep1', 'ep2']);
    expect(readEpisodeSel('g2')).toEqual([]);
    writeEpisodeSel('g1', []);
    expect(readEpisodeSel('g1')).toEqual([]);
  });
});

describe('readActiveGroup / writeActiveGroup', () => {
  it('round-trips active group id in session', () => {
    writeActiveGroup('partition-a');
    expect(readActiveGroup()).toBe('partition-a');
    writeActiveGroup(null);
    expect(readActiveGroup()).toBeNull();
  });
});
