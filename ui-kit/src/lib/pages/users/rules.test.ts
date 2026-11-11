import { describe, expect, it } from 'vitest';
import { change, choiceOf, hasScope, isWaiting, NO_ACCESS, roleSummary } from './rules';
import type { AppUser } from './types';

const user = (role_id: string | null, denied = false) => ({ role_id, denied }) as AppUser;

describe('users', () => {
	it('waits only without a role and without No access', () => {
		expect(isWaiting(user(null))).toBe(true);
		expect(isWaiting(user(null, true))).toBe(false);
		expect(isWaiting(user('kid'))).toBe(false);
	});

	it('turns a choice into what is saved, and back', () => {
		expect(change(NO_ACCESS)).toEqual({ role_id: null, denied: true });
		expect(change('adult')).toEqual({ role_id: 'adult', denied: false });
		expect(change(NO_ACCESS, { areas: [], things: [] })).toEqual({ role_id: null, denied: true, areas: [], things: [] });
		expect(change('kid', { areas: ['boys_bedroom'], things: ['t1'] })).toEqual({ role_id: 'kid', denied: false, areas: ['boys_bedroom'], things: ['t1'] });
		expect(choiceOf(user(null, true))).toBe(NO_ACCESS);
		expect(choiceOf(user('adult'))).toBe('adult');
		expect(choiceOf(user(null))).toBeNull();
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
