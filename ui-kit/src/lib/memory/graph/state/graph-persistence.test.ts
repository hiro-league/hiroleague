import { describe, expect, it, beforeEach, vi } from 'vitest';
import { APP } from '$hiro-app/app';
import { EDGE_FILTER_DEFAULTS } from './graph-types';
import {
	HIDE_EDGES_KEY,
	HIDE_NODES_KEY,
	persistEdgeFilterModes,
	readActiveGroup,
	readEdgeFilterModes,
	readEpisodeSel,
	readHidden,
	seedGraphEpisodeFocus,
	writeActiveGroup,
	writeEpisodeSel,
	writeHidden
} from './graph-persistence';

let local: Map<string, string>;

beforeEach(() => {
	local = new Map<string, string>();
	vi.stubGlobal('localStorage', {
		getItem: (k: string) => (local.has(k) ? local.get(k)! : null),
		setItem: (k: string, v: string) => void local.set(k, String(v)),
		removeItem: (k: string) => void local.delete(k),
		clear: () => local.clear()
	});
});

const stored = (key: string) => local.get(APP.storagePrefix + key);

describe('readEdgeFilterModes / persistEdgeFilterModes', () => {
	it('round-trips edge filter modes through the browser', () => {
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
		expect(stored('graph.edgeFilters')).toBeTruthy();
	});

	it('returns defaults when unset or corrupt', () => {
		expect(readEdgeFilterModes()).toEqual({ ...EDGE_FILTER_DEFAULTS });
		local.set(APP.storagePrefix + 'graph.edgeFilters', '{not json');
		expect(readEdgeFilterModes()).toEqual({ ...EDGE_FILTER_DEFAULTS });
	});

	it('clamps out-of-range stored values', () => {
		local.set(APP.storagePrefix + 'graph.edgeFilters', JSON.stringify({ maxConnPerNode: 999, edgeValidity: 'nope' }));
		const read = readEdgeFilterModes();
		expect(read.maxConnPerNode).toBe(EDGE_FILTER_DEFAULTS.maxConnPerNode);
		expect(read.edgeValidity).toBe('all');
	});
});

describe('readHidden / writeHidden', () => {
	it('round-trips hidden ids', () => {
		writeHidden(HIDE_NODES_KEY, new Set(['a', 'b']));
		expect(readHidden(HIDE_NODES_KEY)).toEqual(new Set(['a', 'b']));
		writeHidden(HIDE_NODES_KEY, new Set());
		expect(readHidden(HIDE_NODES_KEY)).toEqual(new Set());
	});

	it('isolates node vs edge hide keys', () => {
		writeHidden(HIDE_NODES_KEY, new Set(['n1']));
		writeHidden(HIDE_EDGES_KEY, new Set(['REL']));
		expect(readHidden(HIDE_NODES_KEY)).toEqual(new Set(['n1']));
		expect(readHidden(HIDE_EDGES_KEY)).toEqual(new Set(['REL']));
	});

	it('ignores a stored value that is not a list of ids', () => {
		local.set(APP.storagePrefix + HIDE_NODES_KEY, JSON.stringify({ a: 1 }));
		expect(readHidden(HIDE_NODES_KEY)).toEqual(new Set());
	});
});

describe('readEpisodeSel / writeEpisodeSel', () => {
	it('stores per-group episode selections', () => {
		writeEpisodeSel('g1', ['ep1', 'ep2']);
		expect(readEpisodeSel('g1')).toEqual(['ep1', 'ep2']);
		expect(readEpisodeSel('g2')).toEqual([]);
		writeEpisodeSel('g1', []);
		expect(readEpisodeSel('g1')).toEqual([]);
	});
});

describe('readActiveGroup / writeActiveGroup', () => {
	it('round-trips the active group id', () => {
		writeActiveGroup('partition-a');
		expect(readActiveGroup()).toBe('partition-a');
		writeActiveGroup(null);
		expect(readActiveGroup()).toBeNull();
	});
});

describe('seedGraphEpisodeFocus', () => {
	it('sets the active group and that group’s selection, keeping the others', () => {
		writeEpisodeSel('g2', ['x']);
		seedGraphEpisodeFocus('g1', 'ep9');
		expect(readActiveGroup()).toBe('g1');
		expect(readEpisodeSel('g1')).toEqual(['ep9']);
		expect(readEpisodeSel('g2')).toEqual(['x']);
	});

	it('does nothing without both ids', () => {
		seedGraphEpisodeFocus('', 'ep9');
		expect(readActiveGroup()).toBeNull();
	});
});
