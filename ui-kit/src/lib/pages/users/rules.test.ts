import { describe, expect, it } from 'vitest';
import { change, hasScope, isWaiting, rightsText, roleSummary, toggleRole } from './rules';

describe('users', () => {
	it('waits only without a role and without No access', () => {
		expect(isWaiting({ role_ids: [], denied: false })).toBe(true);
		expect(isWaiting({ role_ids: [], denied: true })).toBe(false);
		expect(isWaiting({ role_ids: ['kid'], denied: false })).toBe(false);
	});

	it('holds roles in the roles order, and lets one go', () => {
		const order = ['owner', 'adult', 'kid'];
		expect(toggleRole(['kid'], 'adult', order)).toEqual(['adult', 'kid']);
		expect(toggleRole(['adult', 'kid'], 'adult', order)).toEqual(['kid']);
		expect(toggleRole([], 'kid', order)).toEqual(['kid']);
	});

	it('never gives or takes the Owner role: that is done in HiroLeague', () => {
		const order = ['owner', 'adult', 'kid'];
		expect(toggleRole([], 'owner', order)).toEqual([]);
		expect(toggleRole(['owner', 'kid'], 'owner', order)).toEqual(['owner', 'kid']);
	});

	it('sends the roles and No access, and the scope only where the app has one', () => {
		expect(change(['adult', 'kid'], false)).toEqual({ role_ids: ['adult', 'kid'], denied: false });
		expect(change(['kid'], true)).toEqual({ role_ids: ['kid'], denied: true });
		expect(change(['kid'], false, { areas: ['boys_bedroom'], things: ['t1'] })).toEqual({
			role_ids: ['kid'],
			denied: false,
			areas: ['boys_bedroom'],
			things: ['t1']
		});
	});
});

describe('roles', () => {
	const features = [{ id: 'overview' }, { id: 'control' }, { id: 'logs' }, { id: 'myroom' }];

	it('reads as what it uses and looks at', () => {
		expect(roleSummary({ access: { overview: 'see', control: 'use', logs: 'see', myroom: 'no' } }, features)).toBe('uses 1 feature · looks at 2 features');
		expect(roleSummary({ access: { overview: 'no', control: 'no', logs: 'no', myroom: 'no' } }, features)).toBe('nothing yet');
	});

	it('knows when the scope feature needs areas or things', () => {
		expect(hasScope({ access: { myroom: 'use' } }, 'myroom')).toBe(true);
		expect(hasScope({ access: { myroom: 'no' } }, 'myroom')).toBe(false);
		expect(hasScope(undefined, 'myroom')).toBe(false);
		expect(hasScope({ access: { myroom: 'use' } }, undefined)).toBe(false);
	});
});

describe('rightsText', () => {
	const see = { id: 'see', name: 'See', says: '' };
	const notes = { id: 'notes', rights: [see, { id: 'change', name: 'Change', says: '' }] };

	it('says what a role may do in a feature, their own things included', () => {
		expect(rightsText(['notes.see', 'notes.change'], notes)).toBe('Everything');
		expect(rightsText(['notes.see', 'notes.change:own'], notes)).toBe('See, Change (their own)');
		expect(rightsText([], notes)).toBe('');
	});

	it('reads a feature by its declared keys, not by its id as a prefix', () => {
		expect(rightsText(['notes.runs.see'], notes)).toBe(''); // another feature's key
	});
});
