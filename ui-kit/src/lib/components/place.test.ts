import { describe, expect, it } from 'vitest';
import { everyoneIs, inBannerOrder, placeOf } from './place';

describe('the place in who-is-asking', () => {
	it('is none in live, in env0, and for an app whose answer has none', () => {
		expect(placeOf(null)).toBeNull();
		expect(placeOf({ name: 'Michel' })).toBeNull();
		expect(placeOf({ name: 'Michel', place: null })).toBeNull();
	});

	it('is the test environment the backend says', () => {
		expect(placeOf({ place: { place: 'env2', preset: 'Safe' } })?.place).toBe('env2');
	});

	it('says who everyone is only where the sign-in screen is off', () => {
		expect(everyoneIs({ place: 'env2', preset: 'Safe' })).toBeNull();
		expect(everyoneIs({ place: 'env2', preset: 'Safe', sign_in: 'on' })).toBeNull();
		expect(everyoneIs({ place: 'env2', preset: 'Safe', sign_in: 'off' })).toBe('No sign-in: everyone is the owner');
		expect(everyoneIs({ place: 'env2', preset: 'Safe', sign_in: 'as', sign_in_as: 'Mark' })).toBe('No sign-in: everyone is Mark');
	});

	it('shows the real systems first', () => {
		const place = { place: 'env2', preset: 'AI', systems: [
			{ id: 'ha', name: 'Home Assistant', mode: 'read' as const },
			{ id: 'ai', name: 'AI', mode: 'real' as const }
		] };
		expect(inBannerOrder(place).map((s) => s.id)).toEqual(['ai', 'ha']);
	});
});
