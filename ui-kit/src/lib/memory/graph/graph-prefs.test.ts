import { describe, expect, it, beforeEach, vi } from 'vitest';
import { APP } from '$hiro-app/app';
import {
	GRAPH_OPTION_DEFAULTS,
	decodeGraphOptions,
	readGraphOptionSections,
	readGraphOptions,
	readGraphPanelSide,
	writeGraphOptionSections,
	writeGraphOptions,
	writeGraphPanelSide
} from './graph-prefs';

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

describe('graph options', () => {
	it('defaults when nothing or garbage is stored', () => {
		expect(readGraphOptions()).toEqual(GRAPH_OPTION_DEFAULTS);
		expect(decodeGraphOptions('nope')).toEqual(GRAPH_OPTION_DEFAULTS);
	});

	it('round-trips and clamps stored options', () => {
		writeGraphOptions({ ...GRAPH_OPTION_DEFAULTS, linkDistance: 120, searchFocusMode: 'hide' });
		expect(readGraphOptions().linkDistance).toBe(120);
		expect(readGraphOptions().searchFocusMode).toBe('hide');
		local.set(APP.storagePrefix + 'graph.options', JSON.stringify({ linkStrength: 9, selectionFocusMode: 'x' }));
		const read = readGraphOptions();
		expect(read.linkStrength).toBe(1);
		expect(read.selectionFocusMode).toBe(GRAPH_OPTION_DEFAULTS.selectionFocusMode);
		expect(read.linkDistance).toBe(GRAPH_OPTION_DEFAULTS.linkDistance);
	});
});

describe('option sections and panel side', () => {
	it('round-trip, with defaults for what is missing', () => {
		expect(readGraphOptionSections()).toEqual({ filters: true, view: true, physics: true });
		writeGraphOptionSections({ filters: false, view: true, physics: false });
		expect(readGraphOptionSections()).toEqual({ filters: false, view: true, physics: false });

		expect(readGraphPanelSide()).toBe('auto');
		writeGraphPanelSide('left');
		expect(readGraphPanelSide()).toBe('left');
		local.set(APP.storagePrefix + 'graph.panelSide', JSON.stringify('middle'));
		expect(readGraphPanelSide()).toBe('auto');
	});
});
